"""SQLite storage for latency, VPN, and IP check results."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mm_clikit import SqliteDb

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
    conn.execute("CREATE TABLE IF NOT EXISTS latency_checks (ts REAL NOT NULL, latency_ms REAL, winner_endpoint TEXT)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_latency_checks_ts ON latency_checks(ts)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vpn_checks (
            ts REAL NOT NULL, is_active INTEGER NOT NULL,
            tunnel_mode TEXT NOT NULL, provider TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vpn_checks_ts ON vpn_checks(ts)")
    conn.execute("CREATE TABLE IF NOT EXISTS ip_checks (ts REAL NOT NULL, ip TEXT, country_code TEXT)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_checks_ts ON ip_checks(ts)")


class Db(SqliteDb):
    """Database access object for latency, VPN, and IP check data."""

    def __init__(self, db_path: Path) -> None:
        """Open database and run pending migrations.

        Args:
            db_path: Path to the SQLite database file.

        """
        super().__init__(db_path, migrations=(_migrate_v1,))

    # -- Latency checks --------------------------------------------------------

    def insert_latency_check(self, ts: datetime, latency_ms: float | None, winner_endpoint: str | None) -> None:
        """Insert a single latency check result."""
        self.conn.execute(
            "INSERT INTO latency_checks (ts, latency_ms, winner_endpoint) VALUES (?, ?, ?)",
            (ts.timestamp(), latency_ms, winner_endpoint),
        )
        self.conn.commit()

    def fetch_latest_latency_check(self) -> LatencyRow | None:
        """Return the most recent latency check, or None if table is empty."""
        row = self.conn.execute("SELECT ts, latency_ms, winner_endpoint FROM latency_checks ORDER BY ts DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return LatencyRow(ts=row["ts"], latency_ms=row["latency_ms"], winner_endpoint=row["winner_endpoint"])

    def fetch_latency_checks_since(self, since_ts: float) -> list[LatencyRow]:
        """Return all latency checks with ts > since_ts, ordered by ts ascending."""
        rows = self.conn.execute(
            "SELECT ts, latency_ms, winner_endpoint FROM latency_checks WHERE ts > ? ORDER BY ts ASC", (since_ts,)
        ).fetchall()
        return [LatencyRow(ts=r["ts"], latency_ms=r["latency_ms"], winner_endpoint=r["winner_endpoint"]) for r in rows]

    def purge_old_latency_checks(self, retention_days: int) -> int:
        """Delete latency checks older than *retention_days*. Return rows deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
        cursor = self.conn.execute("DELETE FROM latency_checks WHERE ts < ?", (cutoff.timestamp(),))
        self.conn.commit()
        return cursor.rowcount

    # -- VPN checks ------------------------------------------------------------

    def insert_vpn_check(self, ts: datetime, is_active: bool, tunnel_mode: str, provider: str | None) -> None:
        """Insert a single VPN check result."""
        self.conn.execute(
            "INSERT INTO vpn_checks (ts, is_active, tunnel_mode, provider) VALUES (?, ?, ?, ?)",
            (ts.timestamp(), int(is_active), tunnel_mode, provider),
        )
        self.conn.commit()

    def fetch_latest_vpn_check(self) -> VpnCheckRow | None:
        """Return the most recent VPN check, or None if table is empty."""
        row = self.conn.execute("SELECT ts, is_active, tunnel_mode, provider FROM vpn_checks ORDER BY ts DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return VpnCheckRow(
            ts=row["ts"], is_active=bool(row["is_active"]), tunnel_mode=row["tunnel_mode"], provider=row["provider"]
        )

    def fetch_vpn_checks_since(self, since_ts: float) -> list[VpnCheckRow]:
        """Return all VPN checks with ts > since_ts, ordered by ts ascending."""
        rows = self.conn.execute(
            "SELECT ts, is_active, tunnel_mode, provider FROM vpn_checks WHERE ts > ? ORDER BY ts ASC", (since_ts,)
        ).fetchall()
        return [
            VpnCheckRow(ts=r["ts"], is_active=bool(r["is_active"]), tunnel_mode=r["tunnel_mode"], provider=r["provider"])
            for r in rows
        ]

    def purge_old_vpn_checks(self, retention_days: int) -> int:
        """Delete VPN checks older than *retention_days*. Return rows deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
        cursor = self.conn.execute("DELETE FROM vpn_checks WHERE ts < ?", (cutoff.timestamp(),))
        self.conn.commit()
        return cursor.rowcount

    # -- IP checks -------------------------------------------------------------

    def insert_ip_check(self, ts: datetime, ip: str | None, country_code: str | None) -> None:
        """Insert a single IP check result."""
        self.conn.execute("INSERT INTO ip_checks (ts, ip, country_code) VALUES (?, ?, ?)", (ts.timestamp(), ip, country_code))
        self.conn.commit()

    def fetch_latest_ip_check(self) -> IpCheckRow | None:
        """Return the most recent IP check, or None if table is empty."""
        row = self.conn.execute("SELECT ts, ip, country_code FROM ip_checks ORDER BY ts DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return IpCheckRow(ts=row["ts"], ip=row["ip"], country_code=row["country_code"])

    def fetch_ip_checks_since(self, since_ts: float) -> list[IpCheckRow]:
        """Return all IP checks with ts > since_ts, ordered by ts ascending."""
        rows = self.conn.execute(
            "SELECT ts, ip, country_code FROM ip_checks WHERE ts > ? ORDER BY ts ASC", (since_ts,)
        ).fetchall()
        return [IpCheckRow(ts=r["ts"], ip=r["ip"], country_code=r["country_code"]) for r in rows]

    def purge_old_ip_checks(self, retention_days: int) -> int:
        """Delete IP checks older than *retention_days*. Return rows deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
        cursor = self.conn.execute("DELETE FROM ip_checks WHERE ts < ?", (cutoff.timestamp(),))
        self.conn.commit()
        return cursor.rowcount
