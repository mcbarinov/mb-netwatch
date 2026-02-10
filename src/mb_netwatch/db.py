"""SQLite storage for latency, VPN, and IP check results."""

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

# -- Row types -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LatencyRow:
    """Single latency row from the database."""

    ts: float
    latency_ms: float | None
    winner_endpoint: str | None


@dataclass(frozen=True, slots=True)
class VpnCheckRow:
    """Single VPN check row from the database."""

    ts: float
    is_active: bool
    tunnel_mode: str
    provider: str | None


@dataclass(frozen=True, slots=True)
class IpCheckRow:
    """Single IP check row from the database."""

    ts: float
    ip: str | None
    country_code: str | None


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """Create initial schema: latency_checks, vpn_checks, ip_checks."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS latency_checks (ts REAL NOT NULL, latency_ms REAL, winner_endpoint TEXT);
        CREATE INDEX IF NOT EXISTS idx_latency_checks_ts ON latency_checks(ts);

        CREATE TABLE IF NOT EXISTS vpn_checks (
            ts REAL NOT NULL, is_active INTEGER NOT NULL,
            tunnel_mode TEXT NOT NULL, provider TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_vpn_checks_ts ON vpn_checks(ts);

        CREATE TABLE IF NOT EXISTS ip_checks (ts REAL NOT NULL, ip TEXT, country_code TEXT);
        CREATE INDEX IF NOT EXISTS idx_ip_checks_ts ON ip_checks(ts);
    """)


_MIGRATIONS: tuple[Callable[[sqlite3.Connection], None], ...] = (_migrate_v1,)


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Run all pending schema migrations based on PRAGMA user_version."""
    current_version: int = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, migrate_fn in enumerate(_MIGRATIONS):
        target_version = i + 1
        if current_version < target_version:
            migrate_fn(conn)
            conn.execute(f"PRAGMA user_version = {target_version}")
            log.info("Applied migration v%d (%s)", target_version, migrate_fn.__doc__)


class Db:
    """Database access object holding a SQLite connection."""

    def __init__(self, db_path: Path) -> None:
        """Open a SQLite connection with WAL mode, busy timeout, and create schema if needed.

        Args:
            db_path: Path to the SQLite database file.

        """
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        _run_migrations(self._conn)

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    # -- Latency checks --------------------------------------------------------

    def insert_latency_check(self, ts: datetime, latency_ms: float | None, winner_endpoint: str | None) -> None:
        """Insert a single latency check result."""
        self._conn.execute(
            "INSERT INTO latency_checks (ts, latency_ms, winner_endpoint) VALUES (?, ?, ?)",
            (ts.timestamp(), latency_ms, winner_endpoint),
        )
        self._conn.commit()

    def fetch_latest_latency_check(self) -> LatencyRow | None:
        """Return the most recent latency check, or None if table is empty."""
        row = self._conn.execute("SELECT ts, latency_ms, winner_endpoint FROM latency_checks ORDER BY ts DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return LatencyRow(ts=row[0], latency_ms=row[1], winner_endpoint=row[2])

    def fetch_latency_checks_since(self, since_ts: float) -> list[LatencyRow]:
        """Return all latency checks with ts > since_ts, ordered by ts ascending."""
        rows = self._conn.execute(
            "SELECT ts, latency_ms, winner_endpoint FROM latency_checks WHERE ts > ? ORDER BY ts ASC", (since_ts,)
        ).fetchall()
        return [LatencyRow(ts=r[0], latency_ms=r[1], winner_endpoint=r[2]) for r in rows]

    def purge_old_latency_checks(self, retention_days: int) -> int:
        """Delete latency checks older than *retention_days*. Return rows deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
        cursor = self._conn.execute("DELETE FROM latency_checks WHERE ts < ?", (cutoff.timestamp(),))
        self._conn.commit()
        return cursor.rowcount

    # -- VPN checks ------------------------------------------------------------

    def insert_vpn_check(self, ts: datetime, is_active: bool, tunnel_mode: str, provider: str | None) -> None:
        """Insert a single VPN check result."""
        self._conn.execute(
            "INSERT INTO vpn_checks (ts, is_active, tunnel_mode, provider) VALUES (?, ?, ?, ?)",
            (ts.timestamp(), int(is_active), tunnel_mode, provider),
        )
        self._conn.commit()

    def fetch_latest_vpn_check(self) -> VpnCheckRow | None:
        """Return the most recent VPN check, or None if table is empty."""
        row = self._conn.execute(
            "SELECT ts, is_active, tunnel_mode, provider FROM vpn_checks ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return VpnCheckRow(ts=row[0], is_active=bool(row[1]), tunnel_mode=row[2], provider=row[3])

    def fetch_vpn_checks_since(self, since_ts: float) -> list[VpnCheckRow]:
        """Return all VPN checks with ts > since_ts, ordered by ts ascending."""
        rows = self._conn.execute(
            "SELECT ts, is_active, tunnel_mode, provider FROM vpn_checks WHERE ts > ? ORDER BY ts ASC", (since_ts,)
        ).fetchall()
        return [VpnCheckRow(ts=r[0], is_active=bool(r[1]), tunnel_mode=r[2], provider=r[3]) for r in rows]

    def purge_old_vpn_checks(self, retention_days: int) -> int:
        """Delete VPN checks older than *retention_days*. Return rows deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
        cursor = self._conn.execute("DELETE FROM vpn_checks WHERE ts < ?", (cutoff.timestamp(),))
        self._conn.commit()
        return cursor.rowcount

    # -- IP checks -------------------------------------------------------------

    def insert_ip_check(self, ts: datetime, ip: str | None, country_code: str | None) -> None:
        """Insert a single IP check result."""
        self._conn.execute("INSERT INTO ip_checks (ts, ip, country_code) VALUES (?, ?, ?)", (ts.timestamp(), ip, country_code))
        self._conn.commit()

    def fetch_latest_ip_check(self) -> IpCheckRow | None:
        """Return the most recent IP check, or None if table is empty."""
        row = self._conn.execute("SELECT ts, ip, country_code FROM ip_checks ORDER BY ts DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return IpCheckRow(ts=row[0], ip=row[1], country_code=row[2])

    def fetch_ip_checks_since(self, since_ts: float) -> list[IpCheckRow]:
        """Return all IP checks with ts > since_ts, ordered by ts ascending."""
        rows = self._conn.execute(
            "SELECT ts, ip, country_code FROM ip_checks WHERE ts > ? ORDER BY ts ASC", (since_ts,)
        ).fetchall()
        return [IpCheckRow(ts=r[0], ip=r[1], country_code=r[2]) for r in rows]

    def purge_old_ip_checks(self, retention_days: int) -> int:
        """Delete IP checks older than *retention_days*. Return rows deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
        cursor = self._conn.execute("DELETE FROM ip_checks WHERE ts < ?", (cutoff.timestamp(),))
        self._conn.commit()
        return cursor.rowcount
