"""SQLite storage for latency, VPN, and IP check results."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Self

from mm_clikit import SqliteDb, SqliteRow


class LatencyRow(SqliteRow):
    """Single latency row from the database."""

    ts: float  # UTC Unix timestamp (seconds since epoch)
    latency_ms: float | None  # Round-trip time in milliseconds; None when all endpoints failed
    winner_endpoint: str | None  # URL that responded first; None when down

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Construct from a sqlite3.Row."""
        return cls(ts=row["ts"], latency_ms=row["latency_ms"], winner_endpoint=row["winner_endpoint"])


class VpnCheckRow(SqliteRow):
    """Single VPN check row from the database."""

    created_at: float  # UTC Unix timestamp when this state first appeared
    updated_at: float  # UTC Unix timestamp of most recent confirmation
    is_active: bool  # Whether traffic is routed through a tunnel interface
    tunnel_mode: str  # "full", "split", or "unknown"
    provider: str | None  # VPN app name; None when not identified

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Construct from a sqlite3.Row."""
        return cls(
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            is_active=bool(row["is_active"]),
            tunnel_mode=row["tunnel_mode"],
            provider=row["provider"],
        )


class IpCheckRow(SqliteRow):
    """Single IP check row from the database."""

    created_at: float  # UTC Unix timestamp when this (ip, country_code) pair first appeared
    updated_at: float  # UTC Unix timestamp of most recent confirmation
    ip: str | None  # Public IPv4 address; None when all lookups failed
    country_code: str | None  # 2-letter ISO country code; None when lookup failed

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Construct from a sqlite3.Row."""
        return cls(created_at=row["created_at"], updated_at=row["updated_at"], ip=row["ip"], country_code=row["country_code"])


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """Create initial schema: latency_checks, vpn_checks, ip_checks."""
    conn.execute("CREATE TABLE IF NOT EXISTS latency_checks (ts REAL NOT NULL, latency_ms REAL, winner_endpoint TEXT)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_latency_checks_ts ON latency_checks(ts)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vpn_checks (
            created_at REAL NOT NULL, updated_at REAL NOT NULL,
            is_active INTEGER NOT NULL, tunnel_mode TEXT NOT NULL, provider TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vpn_checks_created_at ON vpn_checks(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vpn_checks_updated_at ON vpn_checks(updated_at)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ip_checks (
            created_at REAL NOT NULL, updated_at REAL NOT NULL,
            ip TEXT, country_code TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_checks_created_at ON ip_checks(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_checks_updated_at ON ip_checks(updated_at)")


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
        return LatencyRow.from_row(row) if row else None

    def fetch_latency_checks_since(self, since_ts: float) -> list[LatencyRow]:
        """Return all latency checks with ts > since_ts, ordered by ts ascending."""
        rows = self.conn.execute(
            "SELECT ts, latency_ms, winner_endpoint FROM latency_checks WHERE ts > ? ORDER BY ts ASC", (since_ts,)
        ).fetchall()
        return [LatencyRow.from_row(r) for r in rows]

    def purge_old_latency_checks(self, retention_days: int) -> int:
        """Delete latency checks older than *retention_days*. Return rows deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
        cursor = self.conn.execute("DELETE FROM latency_checks WHERE ts < ?", (cutoff.timestamp(),))
        self.conn.commit()
        return cursor.rowcount

    # -- VPN checks ------------------------------------------------------------

    def upsert_vpn_check(self, ts: datetime, is_active: bool, tunnel_mode: str, provider: str | None) -> None:
        """Insert or update a VPN check result. Deduplicates consecutive identical states."""
        ts_val = ts.timestamp()
        latest = self.conn.execute(
            "SELECT rowid, is_active, tunnel_mode, provider FROM vpn_checks ORDER BY updated_at DESC LIMIT 1",
        ).fetchone()
        same = latest is not None and (bool(latest["is_active"]), latest["tunnel_mode"], latest["provider"]) == (
            is_active,
            tunnel_mode,
            provider,
        )
        if same:
            self.conn.execute("UPDATE vpn_checks SET updated_at = ? WHERE rowid = ?", (ts_val, latest["rowid"]))
        else:
            self.conn.execute(
                "INSERT INTO vpn_checks (created_at, updated_at, is_active, tunnel_mode, provider) VALUES (?, ?, ?, ?, ?)",
                (ts_val, ts_val, int(is_active), tunnel_mode, provider),
            )
        self.conn.commit()

    def fetch_latest_vpn_check(self) -> VpnCheckRow | None:
        """Return the most recently confirmed VPN check, or None if table is empty."""
        row = self.conn.execute(
            "SELECT created_at, updated_at, is_active, tunnel_mode, provider FROM vpn_checks ORDER BY updated_at DESC LIMIT 1",
        ).fetchone()
        return VpnCheckRow.from_row(row) if row else None

    def fetch_vpn_checks_since(self, since_ts: float) -> list[VpnCheckRow]:
        """Return VPN state changes with created_at > since_ts, ordered ascending."""
        rows = self.conn.execute(
            "SELECT created_at, updated_at, is_active, tunnel_mode, provider FROM vpn_checks"
            " WHERE created_at > ? ORDER BY created_at ASC",
            (since_ts,),
        ).fetchall()
        return [VpnCheckRow.from_row(r) for r in rows]

    def purge_old_vpn_checks(self, retention_days: int) -> int:
        """Delete VPN checks not confirmed within *retention_days*. Return rows deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
        cursor = self.conn.execute("DELETE FROM vpn_checks WHERE updated_at < ?", (cutoff.timestamp(),))
        self.conn.commit()
        return cursor.rowcount

    # -- IP checks -------------------------------------------------------------

    def upsert_ip_check(self, ts: datetime, ip: str | None, country_code: str | None) -> None:
        """Insert or update an IP check result. Deduplicates consecutive identical values."""
        ts_val = ts.timestamp()
        latest = self.conn.execute("SELECT rowid, ip, country_code FROM ip_checks ORDER BY updated_at DESC LIMIT 1").fetchone()
        if latest is not None and (latest["ip"], latest["country_code"]) == (ip, country_code):
            self.conn.execute("UPDATE ip_checks SET updated_at = ? WHERE rowid = ?", (ts_val, latest["rowid"]))
        else:
            self.conn.execute(
                "INSERT INTO ip_checks (created_at, updated_at, ip, country_code) VALUES (?, ?, ?, ?)",
                (ts_val, ts_val, ip, country_code),
            )
        self.conn.commit()

    def fetch_latest_ip_check(self) -> IpCheckRow | None:
        """Return the most recently confirmed IP check, or None if table is empty."""
        row = self.conn.execute(
            "SELECT created_at, updated_at, ip, country_code FROM ip_checks ORDER BY updated_at DESC LIMIT 1",
        ).fetchone()
        return IpCheckRow.from_row(row) if row else None

    def fetch_ip_checks_since(self, since_ts: float) -> list[IpCheckRow]:
        """Return IP state changes with created_at > since_ts, ordered ascending."""
        rows = self.conn.execute(
            "SELECT created_at, updated_at, ip, country_code FROM ip_checks WHERE created_at > ? ORDER BY created_at ASC",
            (since_ts,),
        ).fetchall()
        return [IpCheckRow.from_row(r) for r in rows]

    def purge_old_ip_checks(self, retention_days: int) -> int:
        """Delete IP checks not confirmed within *retention_days*. Return rows deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
        cursor = self.conn.execute("DELETE FROM ip_checks WHERE updated_at < ?", (cutoff.timestamp(),))
        self.conn.commit()
        return cursor.rowcount
