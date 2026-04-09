"""SQLite storage for probe results: latency, VPN, and IP."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Self

from mm_clikit import SqliteDb, SqliteRow


class ProbeLatency(SqliteRow):
    """Single latency probe row."""

    created_at: float  # UTC Unix timestamp (seconds since epoch)
    latency_ms: float | None  # Round-trip time in milliseconds; None when all endpoints failed
    winner_endpoint: str | None  # URL that responded first; None when down

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Construct from a sqlite3.Row."""
        return cls(created_at=row["created_at"], latency_ms=row["latency_ms"], winner_endpoint=row["winner_endpoint"])


class ProbeVpn(SqliteRow):
    """Single VPN probe row."""

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


class ProbeIp(SqliteRow):
    """Single IP probe row."""

    created_at: float  # UTC Unix timestamp when this (ip, country_code) pair first appeared
    updated_at: float  # UTC Unix timestamp of most recent confirmation
    ip: str | None  # Public IPv4 address; None when all lookups failed
    country_code: str | None  # 2-letter ISO country code; None when lookup failed

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Construct from a sqlite3.Row."""
        return cls(created_at=row["created_at"], updated_at=row["updated_at"], ip=row["ip"], country_code=row["country_code"])


_MIGRATE_V1 = """
CREATE TABLE probe_latency (
    created_at REAL NOT NULL, latency_ms REAL, winner_endpoint TEXT
);
CREATE INDEX idx_probe_latency_created_at ON probe_latency(created_at);

CREATE TABLE probe_vpn (
    created_at REAL NOT NULL, updated_at REAL NOT NULL,
    is_active INTEGER NOT NULL, tunnel_mode TEXT NOT NULL, provider TEXT
);
CREATE INDEX idx_probe_vpn_created_at ON probe_vpn(created_at);
CREATE INDEX idx_probe_vpn_updated_at ON probe_vpn(updated_at);

CREATE TABLE probe_ip (
    created_at REAL NOT NULL, updated_at REAL NOT NULL,
    ip TEXT, country_code TEXT
);
CREATE INDEX idx_probe_ip_created_at ON probe_ip(created_at);
CREATE INDEX idx_probe_ip_updated_at ON probe_ip(updated_at);
"""


class Db(SqliteDb):
    """Database access object for probe data."""

    def __init__(self, db_path: Path) -> None:
        """Open database and run pending migrations.

        Args:
            db_path: Path to the SQLite database file.

        """
        super().__init__(db_path, migrations=(_MIGRATE_V1,))

    # -- Latency probes --------------------------------------------------------

    def insert_probe_latency(self, ts: datetime, latency_ms: float | None, winner_endpoint: str | None) -> None:
        """Insert a single latency probe result."""
        self.conn.execute(
            "INSERT INTO probe_latency (created_at, latency_ms, winner_endpoint) VALUES (?, ?, ?)",
            (ts.timestamp(), latency_ms, winner_endpoint),
        )
        self.conn.commit()

    def fetch_latest_probe_latency(self) -> ProbeLatency | None:
        """Return the most recent latency probe, or None if table is empty."""
        row = self.conn.execute(
            "SELECT created_at, latency_ms, winner_endpoint FROM probe_latency ORDER BY created_at DESC LIMIT 1",
        ).fetchone()
        return ProbeLatency.from_row(row) if row else None

    def fetch_probe_latency_since(self, since_ts: float) -> list[ProbeLatency]:
        """Return all latency probes with created_at > since_ts, ordered ascending."""
        rows = self.conn.execute(
            "SELECT created_at, latency_ms, winner_endpoint FROM probe_latency WHERE created_at > ? ORDER BY created_at ASC",
            (since_ts,),
        ).fetchall()
        return [ProbeLatency.from_row(r) for r in rows]

    def purge_old_probe_latency(self, retention_days: int) -> int:
        """Delete latency probes older than *retention_days*. Return rows deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
        cursor = self.conn.execute("DELETE FROM probe_latency WHERE created_at < ?", (cutoff.timestamp(),))
        self.conn.commit()
        return cursor.rowcount

    # -- VPN probes ------------------------------------------------------------

    def upsert_probe_vpn(self, ts: datetime, is_active: bool, tunnel_mode: str, provider: str | None) -> None:
        """Insert or update a VPN probe result. Deduplicates consecutive identical states."""
        ts_val = ts.timestamp()
        latest = self.conn.execute(
            "SELECT rowid, is_active, tunnel_mode, provider FROM probe_vpn ORDER BY updated_at DESC LIMIT 1",
        ).fetchone()
        same = latest is not None and (bool(latest["is_active"]), latest["tunnel_mode"], latest["provider"]) == (
            is_active,
            tunnel_mode,
            provider,
        )
        if same:
            self.conn.execute("UPDATE probe_vpn SET updated_at = ? WHERE rowid = ?", (ts_val, latest["rowid"]))
        else:
            self.conn.execute(
                "INSERT INTO probe_vpn (created_at, updated_at, is_active, tunnel_mode, provider) VALUES (?, ?, ?, ?, ?)",
                (ts_val, ts_val, int(is_active), tunnel_mode, provider),
            )
        self.conn.commit()

    def fetch_latest_probe_vpn(self) -> ProbeVpn | None:
        """Return the most recently confirmed VPN probe, or None if table is empty."""
        row = self.conn.execute(
            "SELECT created_at, updated_at, is_active, tunnel_mode, provider FROM probe_vpn ORDER BY updated_at DESC LIMIT 1",
        ).fetchone()
        return ProbeVpn.from_row(row) if row else None

    def fetch_probe_vpn_since(self, since_ts: float) -> list[ProbeVpn]:
        """Return VPN state changes with created_at > since_ts, ordered ascending."""
        rows = self.conn.execute(
            "SELECT created_at, updated_at, is_active, tunnel_mode, provider FROM probe_vpn"
            " WHERE created_at > ? ORDER BY created_at ASC",
            (since_ts,),
        ).fetchall()
        return [ProbeVpn.from_row(r) for r in rows]

    def purge_old_probe_vpn(self, retention_days: int) -> int:
        """Delete VPN probes not confirmed within *retention_days*. Return rows deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
        cursor = self.conn.execute("DELETE FROM probe_vpn WHERE updated_at < ?", (cutoff.timestamp(),))
        self.conn.commit()
        return cursor.rowcount

    # -- IP probes -------------------------------------------------------------

    def upsert_probe_ip(self, ts: datetime, ip: str | None, country_code: str | None) -> None:
        """Insert or update an IP probe result. Deduplicates consecutive identical values."""
        ts_val = ts.timestamp()
        latest = self.conn.execute("SELECT rowid, ip, country_code FROM probe_ip ORDER BY updated_at DESC LIMIT 1").fetchone()
        if latest is not None and (latest["ip"], latest["country_code"]) == (ip, country_code):
            self.conn.execute("UPDATE probe_ip SET updated_at = ? WHERE rowid = ?", (ts_val, latest["rowid"]))
        else:
            self.conn.execute(
                "INSERT INTO probe_ip (created_at, updated_at, ip, country_code) VALUES (?, ?, ?, ?)",
                (ts_val, ts_val, ip, country_code),
            )
        self.conn.commit()

    def fetch_latest_probe_ip(self) -> ProbeIp | None:
        """Return the most recently confirmed IP probe, or None if table is empty."""
        row = self.conn.execute(
            "SELECT created_at, updated_at, ip, country_code FROM probe_ip ORDER BY updated_at DESC LIMIT 1",
        ).fetchone()
        return ProbeIp.from_row(row) if row else None

    def fetch_probe_ip_since(self, since_ts: float) -> list[ProbeIp]:
        """Return IP state changes with created_at > since_ts, ordered ascending."""
        rows = self.conn.execute(
            "SELECT created_at, updated_at, ip, country_code FROM probe_ip WHERE created_at > ? ORDER BY created_at ASC",
            (since_ts,),
        ).fetchall()
        return [ProbeIp.from_row(r) for r in rows]

    def purge_old_probe_ip(self, retention_days: int) -> int:
        """Delete IP probes not confirmed within *retention_days*. Return rows deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
        cursor = self.conn.execute("DELETE FROM probe_ip WHERE updated_at < ?", (cutoff.timestamp(),))
        self.conn.commit()
        return cursor.rowcount
