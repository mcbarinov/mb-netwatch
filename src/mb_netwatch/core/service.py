"""Core business logic."""

import asyncio
import logging
from datetime import UTC, datetime

import aiohttp
from pydantic import BaseModel, ConfigDict

from mb_netwatch.config import Config
from mb_netwatch.core.db import Db, TunnelMode
from mb_netwatch.core.probes.dns import DnsResolverSample, check_dns
from mb_netwatch.core.probes.ip import IpResult, check_ip
from mb_netwatch.core.probes.latency import check_latency_cold, check_latency_warm
from mb_netwatch.core.probes.vpn import check_vpn

log = logging.getLogger(__name__)


class ProbeResult(BaseModel):
    """Result of a one-shot connectivity probe."""

    model_config = ConfigDict(frozen=True)

    latency_warm_ms: float | None  # Warm (reused session) round-trip time in ms; None when down
    latency_warm_endpoint: str | None  # URL that responded first for warm probe; None when down
    latency_cold_ms: float | None  # Cold (fresh session, full TCP+TLS) round-trip time in ms; None when down
    latency_cold_endpoint: str | None  # URL that responded first for cold probe; None when down
    vpn_active: bool  # Whether VPN tunnel is active
    tunnel_mode: TunnelMode | None  # "full"/"split"; None when inactive or detection failed
    vpn_provider: str | None  # VPN app name; None when not identified
    ip: str | None  # Public IPv4 address; None when lookup failed
    country_code: str | None  # 2-letter ISO country code; None when lookup failed
    dns_resolvers: list[DnsResolverSample]  # System DNS resolvers with measurements; [0] is primary; empty = no DNS config


class Service:
    """Main application service."""

    def __init__(self, db: Db, config: Config) -> None:
        """Initialize with database and configuration.

        Args:
            db: Database access object.
            config: Application configuration.

        """
        self._db = db
        self._config = config
        # Daemon state: lazy-created HTTP session for the warm-latency probe (reused for connection keep-alive)
        self._warm_latency_session: aiohttp.ClientSession | None = None
        # Daemon state: last IP result for skipping redundant country lookups
        self._last_ip_result: IpResult | None = None
        self._ip_state_seeded = False

    # -- One-shot probe --------------------------------------------------------

    async def run_probe(self) -> ProbeResult:
        """Run all checks concurrently and return a combined result.

        The one-shot path has no long-lived session. To make the "warm" number
        actually reflect steady-state (and not just another cold measurement
        running alongside the cold probe), we pre-open the connection pool with a
        throwaway request against ``warm_session`` before measuring.
        """
        cfg = self._config.probed
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=cfg.warm_latency_timeout)) as warm_session:
            # Pre-warm: open the pool so the measured warm request reuses a live connection.
            # Without this, warm would measure the full setup cost — same as cold.
            await check_latency_warm(warm_session)
            latency_warm, latency_cold, vpn, ip_result, dns_result = await asyncio.gather(
                check_latency_warm(warm_session),
                check_latency_cold(http_timeout=cfg.cold_latency_timeout),
                asyncio.to_thread(check_vpn),
                check_ip(http_timeout=cfg.ip_timeout),
                check_dns(timeout=cfg.dns_timeout),
            )
        return ProbeResult(
            latency_warm_ms=latency_warm.latency_ms,
            latency_warm_endpoint=latency_warm.endpoint,
            latency_cold_ms=latency_cold.latency_ms,
            latency_cold_endpoint=latency_cold.endpoint,
            vpn_active=vpn.is_active,
            tunnel_mode=vpn.tunnel_mode,
            vpn_provider=vpn.provider,
            ip=ip_result.ip,
            country_code=ip_result.country_code,
            dns_resolvers=dns_result.resolvers,
        )

    # -- Daemon check methods --------------------------------------------------

    async def run_latency_warm_check(self) -> None:
        """Run a single warm-latency probe (reused session), log and store the result.

        Manages HTTP session lifecycle: lazy creation, self-healing recreation on failure.
        """
        cfg = self._config.probed
        if self._warm_latency_session is None:
            self._warm_latency_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=cfg.warm_latency_timeout))

        result = await check_latency_warm(self._warm_latency_session)
        ts = datetime.now(tz=UTC)
        self._db.insert_probe_latency_warm(ts, result.latency_ms, result.endpoint)

        # Self-healing: recreate session on failure to drop stale connections
        if result.latency_ms is None:
            log.warning("Warm latency check failed, recreating HTTP session.")
            await self._warm_latency_session.close()
            self._warm_latency_session = None

    async def run_latency_cold_check(self) -> None:
        """Run a single cold-latency probe (fresh session), log and store the result.

        No session state to manage — ``check_latency_cold`` builds and tears down its own session.
        """
        cfg = self._config.probed
        result = await check_latency_cold(http_timeout=cfg.cold_latency_timeout)
        ts = datetime.now(tz=UTC)
        self._db.insert_probe_latency_cold(ts, result.latency_ms, result.endpoint)

    async def run_dns_check(self) -> None:
        """Run a single DNS probe across all system resolvers and store the result.

        No shared state — ``check_dns`` rediscovers the resolver set each cycle via ``scutil --dns``.
        """
        cfg = self._config.probed
        result = await check_dns(timeout=cfg.dns_timeout)
        ts = datetime.now(tz=UTC)
        self._db.insert_probe_dns(ts, result)

    async def run_vpn_check(self) -> bool:
        """Run a single VPN check, log and store the result. Return whether VPN is active."""
        status = await asyncio.to_thread(check_vpn)
        ts = datetime.now(tz=UTC)
        self._db.upsert_probe_vpn(ts, status.is_active, status.tunnel_mode, status.provider)
        return status.is_active

    async def run_ip_check(self, *, vpn_changed: bool = False) -> None:
        """Run a single IP check, log and store the result.

        Args:
            vpn_changed: When True, forces fresh country lookup (IP likely changed after VPN toggle).

        """
        # Seed from DB on first call so we skip country lookup on restart if IP is unchanged
        if not self._ip_state_seeded:
            last = self._db.fetch_latest_probe_ip()
            self._last_ip_result = IpResult(ip=last.ip, country_code=last.country_code) if last else None
            self._ip_state_seeded = True

        if vpn_changed:
            self._last_ip_result = None

        result = await check_ip(
            previous=self._last_ip_result,
            known_country_lookup=self._db.fetch_country_for_ip,
            http_timeout=self._config.probed.ip_timeout,
        )
        ts = datetime.now(tz=UTC)
        self._db.upsert_probe_ip(ts, result.ip, result.country_code)
        self._last_ip_result = result

    async def close_warm_latency_session(self) -> None:
        """Close the persistent warm-latency HTTP session if open."""
        if self._warm_latency_session is not None:
            await self._warm_latency_session.close()
            self._warm_latency_session = None
