"""Core business logic."""

import asyncio
import logging
from datetime import UTC, datetime

import aiohttp
from pydantic import BaseModel, ConfigDict

from mb_netwatch.config import Config
from mb_netwatch.core.db import Db
from mb_netwatch.core.probes.ip import IpResult, check_ip
from mb_netwatch.core.probes.latency import check_latency
from mb_netwatch.core.probes.vpn import check_vpn

log = logging.getLogger(__name__)


class ProbeResult(BaseModel):
    """Result of a one-shot connectivity probe."""

    model_config = ConfigDict(frozen=True)

    latency_ms: float | None  # Round-trip time in milliseconds; None when down
    winner_endpoint: str | None  # URL that responded first; None when down
    vpn_active: bool  # Whether VPN tunnel is active
    tunnel_mode: str  # "full", "split", or "unknown"
    vpn_provider: str | None  # VPN app name; None when not identified
    ip: str | None  # Public IPv4 address; None when lookup failed
    country_code: str | None  # 2-letter ISO country code; None when lookup failed


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
        # Daemon state: lazy-created HTTP session for latency probes (reused for connection keep-alive)
        self._latency_session: aiohttp.ClientSession | None = None
        # Daemon state: last IP result for skipping redundant country lookups
        self._last_ip_result: IpResult | None = None
        self._ip_state_seeded = False

    # -- One-shot probe --------------------------------------------------------

    async def run_probe(self) -> ProbeResult:
        """Run all checks concurrently and return a combined result."""
        latency, vpn, ip_result = await asyncio.gather(
            check_latency(http_timeout=self._config.probed.latency_timeout),
            asyncio.to_thread(check_vpn),
            check_ip(http_timeout=self._config.probed.ip_timeout),
        )
        return ProbeResult(
            latency_ms=latency.latency_ms,
            winner_endpoint=latency.winner_endpoint,
            vpn_active=vpn.is_active,
            tunnel_mode=vpn.tunnel_mode,
            vpn_provider=vpn.provider,
            ip=ip_result.ip,
            country_code=ip_result.country_code,
        )

    # -- Daemon check methods --------------------------------------------------

    async def run_latency_check(self) -> None:
        """Run a single latency probe, log and store the result. Manages HTTP session lifecycle."""
        cfg = self._config.probed
        if self._latency_session is None:
            self._latency_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=cfg.latency_timeout))

        result = await check_latency(self._latency_session)
        ts = datetime.now(tz=UTC)
        log.debug("latency=%s ms, endpoint=%s", result.latency_ms, result.winner_endpoint)
        self._db.insert_probe_latency(ts, result.latency_ms, result.winner_endpoint)

        # Self-healing: recreate session on failure to drop stale connections
        if result.latency_ms is None:
            log.debug("Latency check failed, recreating HTTP session.")
            await self._latency_session.close()
            self._latency_session = None

    async def run_vpn_check(self) -> bool:
        """Run a single VPN check, log and store the result. Return whether VPN is active."""
        status = await asyncio.to_thread(check_vpn)
        ts = datetime.now(tz=UTC)
        log.debug("vpn=%s, mode=%s, provider=%s", status.is_active, status.tunnel_mode, status.provider)
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

        result = await check_ip(previous=self._last_ip_result, http_timeout=self._config.probed.ip_timeout)
        ts = datetime.now(tz=UTC)
        log.debug("ip=%s, country=%s", result.ip, result.country_code)
        self._db.upsert_probe_ip(ts, result.ip, result.country_code)
        self._last_ip_result = result

    async def close_latency_session(self) -> None:
        """Close the persistent latency HTTP session if open."""
        if self._latency_session is not None:
            await self._latency_session.close()
            self._latency_session = None
