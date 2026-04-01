"""Core business logic."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import aiohttp

from mb_netwatch.config import Config
from mb_netwatch.db import Db, IpCheckRow, LatencyRow, VpnCheckRow
from mb_netwatch.probes.ip import IpResult, check_ip
from mb_netwatch.probes.latency import check_latency
from mb_netwatch.probes.vpn import check_vpn

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Result of a one-shot connectivity probe."""

    latency_ms: float | None
    winner_endpoint: str | None
    vpn_active: bool
    tunnel_mode: str
    vpn_provider: str | None
    ip: str | None
    country_code: str | None


class Service:
    """Main application service."""

    def __init__(self, db: Db, cfg: Config) -> None:
        """Initialize with database and configuration.

        Args:
            db: Database access object.
            cfg: Application configuration.

        """
        self._db = db
        self._cfg = cfg
        # Daemon state: lazy-created HTTP session for latency probes (reused for connection keep-alive)
        self._latency_session: aiohttp.ClientSession | None = None
        # Daemon state: last IP result for skipping redundant country lookups
        self._last_ip_result: IpResult | None = None
        self._ip_state_seeded = False

    @property
    def cfg(self) -> Config:
        """Application configuration."""
        return self._cfg

    # -- One-shot probe --------------------------------------------------------

    async def run_probe(self) -> ProbeResult:
        """Run all checks concurrently and return a combined result."""
        latency, vpn, ip_result = await asyncio.gather(
            check_latency(http_timeout=self._cfg.probed.latency_timeout),
            asyncio.to_thread(check_vpn),
            check_ip(http_timeout=self._cfg.probed.ip_timeout),
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
        cfg = self._cfg.probed
        if self._latency_session is None:
            self._latency_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=cfg.latency_timeout))

        result = await check_latency(self._latency_session)
        ts = datetime.now(tz=UTC)
        log.debug("latency=%s ms, endpoint=%s", result.latency_ms, result.winner_endpoint)
        self._db.insert_latency_check(ts, result.latency_ms, result.winner_endpoint)

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
        self._db.insert_vpn_check(ts, status.is_active, status.tunnel_mode, status.provider)
        return status.is_active

    async def run_ip_check(self, *, vpn_changed: bool = False) -> None:
        """Run a single IP check, log and store the result.

        Args:
            vpn_changed: When True, forces fresh country lookup (IP likely changed after VPN toggle).

        """
        # Seed from DB on first call so we skip country lookup on restart if IP is unchanged
        if not self._ip_state_seeded:
            last = self._db.fetch_latest_ip_check()
            self._last_ip_result = IpResult(ip=last.ip, country_code=last.country_code) if last else None
            self._ip_state_seeded = True

        if vpn_changed:
            self._last_ip_result = None

        result = await check_ip(previous=self._last_ip_result, http_timeout=self._cfg.probed.ip_timeout)
        ts = datetime.now(tz=UTC)
        log.debug("ip=%s, country=%s", result.ip, result.country_code)
        self._db.insert_ip_check(ts, result.ip, result.country_code)
        self._last_ip_result = result

    async def close_latency_session(self) -> None:
        """Close the persistent latency HTTP session if open."""
        if self._latency_session is not None:
            await self._latency_session.close()
            self._latency_session = None

    # -- Latency checks --------------------------------------------------------

    def fetch_latest_latency_check(self) -> LatencyRow | None:
        """Return the most recent latency check, or None if table is empty."""
        return self._db.fetch_latest_latency_check()

    def fetch_latency_checks_since(self, since_ts: float) -> list[LatencyRow]:
        """Return all latency checks with ts > since_ts, ordered by ts ascending."""
        return self._db.fetch_latency_checks_since(since_ts)

    def purge_old_latency_checks(self, retention_days: int) -> int:
        """Delete latency checks older than *retention_days*. Return rows deleted."""
        return self._db.purge_old_latency_checks(retention_days)

    # -- VPN checks ------------------------------------------------------------

    def fetch_latest_vpn_check(self) -> VpnCheckRow | None:
        """Return the most recent VPN check, or None if table is empty."""
        return self._db.fetch_latest_vpn_check()

    def fetch_vpn_checks_since(self, since_ts: float) -> list[VpnCheckRow]:
        """Return all VPN checks with ts > since_ts, ordered by ts ascending."""
        return self._db.fetch_vpn_checks_since(since_ts)

    def purge_old_vpn_checks(self, retention_days: int) -> int:
        """Delete VPN checks older than *retention_days*. Return rows deleted."""
        return self._db.purge_old_vpn_checks(retention_days)

    # -- IP checks -------------------------------------------------------------

    def fetch_latest_ip_check(self) -> IpCheckRow | None:
        """Return the most recent IP check, or None if table is empty."""
        return self._db.fetch_latest_ip_check()

    def fetch_ip_checks_since(self, since_ts: float) -> list[IpCheckRow]:
        """Return all IP checks with ts > since_ts, ordered by ts ascending."""
        return self._db.fetch_ip_checks_since(since_ts)

    def purge_old_ip_checks(self, retention_days: int) -> int:
        """Delete IP checks older than *retention_days*. Return rows deleted."""
        return self._db.purge_old_ip_checks(retention_days)
