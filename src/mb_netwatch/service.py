"""Core business logic."""

import asyncio
from dataclasses import dataclass
from datetime import datetime

from mb_netwatch.config import Config
from mb_netwatch.db import Db, IpCheckRow, LatencyRow, VpnCheckRow
from mb_netwatch.probes.ip import check_ip
from mb_netwatch.probes.latency import check_latency
from mb_netwatch.probes.vpn import check_vpn


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

    # -- Latency checks --------------------------------------------------------

    def insert_latency_check(self, ts: datetime, latency_ms: float | None, winner_endpoint: str | None) -> None:
        """Insert a single latency check result."""
        self._db.insert_latency_check(ts, latency_ms, winner_endpoint)

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

    def insert_vpn_check(self, ts: datetime, is_active: bool, tunnel_mode: str, provider: str | None) -> None:
        """Insert a single VPN check result."""
        self._db.insert_vpn_check(ts, is_active, tunnel_mode, provider)

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

    def insert_ip_check(self, ts: datetime, ip: str | None, country_code: str | None) -> None:
        """Insert a single IP check result."""
        self._db.insert_ip_check(ts, ip, country_code)

    def fetch_latest_ip_check(self) -> IpCheckRow | None:
        """Return the most recent IP check, or None if table is empty."""
        return self._db.fetch_latest_ip_check()

    def fetch_ip_checks_since(self, since_ts: float) -> list[IpCheckRow]:
        """Return all IP checks with ts > since_ts, ordered by ts ascending."""
        return self._db.fetch_ip_checks_since(since_ts)

    def purge_old_ip_checks(self, retention_days: int) -> int:
        """Delete IP checks older than *retention_days*. Return rows deleted."""
        return self._db.purge_old_ip_checks(retention_days)
