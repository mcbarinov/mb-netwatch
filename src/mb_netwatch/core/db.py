"""SQLite storage for probe results: warm/cold latency, VPN, IP, and DNS."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Self

from mm_clikit import SqliteDb, SqliteRow

from mb_netwatch.core.probes.dns import DnsResolverSample, DnsResult

TunnelMode = Literal["full", "split"]


class ProbeLatencyWarm(SqliteRow):
    """Single warm-latency probe row (reused keep-alive HTTP session)."""

    created_at: float  # UTC Unix timestamp (seconds since epoch)
    latency_ms: float | None  # Round-trip time in milliseconds; None when all endpoints failed
    endpoint: str | None  # URL that responded first; None when down

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Construct from a sqlite3.Row."""
        return cls(created_at=row["created_at"], latency_ms=row["latency_ms"], endpoint=row["endpoint"])


class ProbeLatencyCold(SqliteRow):
    """Single cold-latency probe row (fresh HTTP session — full TCP+TLS setup each cycle)."""

    created_at: float  # UTC Unix timestamp (seconds since epoch)
    latency_ms: float | None  # Round-trip time in milliseconds; None when all endpoints failed
    endpoint: str | None  # URL that responded first; None when down

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Construct from a sqlite3.Row."""
        return cls(created_at=row["created_at"], latency_ms=row["latency_ms"], endpoint=row["endpoint"])


class ProbeVpn(SqliteRow):
    """Single VPN probe row."""

    created_at: float  # UTC Unix timestamp when this state first appeared
    updated_at: float  # UTC Unix timestamp of most recent confirmation
    is_active: bool  # Whether traffic is routed through a tunnel interface
    tunnel_mode: TunnelMode | None  # "full"/"split"; None when inactive or detection failed
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


class ProbeDns(SqliteRow):
    """Single DNS probe row — one cycle across every system resolver."""

    created_at: float  # UTC Unix timestamp
    primary_ms: float | None  # resolvers[0].resolve_ms; None on empty list or when primary had no latency
    primary_error: str | None  # resolvers[0].error; None on clean success or empty list
    primary_address: str | None  # resolvers[0].address; None when resolver list is empty
    resolvers: list[DnsResolverSample]  # Full per-resolver list reconstructed from resolvers_json

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Construct from a sqlite3.Row — parses resolvers_json back into DnsResolverSample models."""
        raw = json.loads(row["resolvers_json"])
        resolvers = [DnsResolverSample.model_validate(s) for s in raw]
        return cls(
            created_at=row["created_at"],
            primary_ms=row["primary_ms"],
            primary_error=row["primary_error"],
            primary_address=row["primary_address"],
            resolvers=resolvers,
        )


_MIGRATE_V1 = """
CREATE TABLE probe_latency_warm (
    created_at REAL NOT NULL, latency_ms REAL, endpoint TEXT
);
CREATE INDEX idx_probe_latency_warm_created_at ON probe_latency_warm(created_at);

CREATE TABLE probe_latency_cold (
    created_at REAL NOT NULL, latency_ms REAL, endpoint TEXT
);
CREATE INDEX idx_probe_latency_cold_created_at ON probe_latency_cold(created_at);

CREATE TABLE probe_vpn (
    created_at REAL NOT NULL, updated_at REAL NOT NULL,
    is_active INTEGER NOT NULL, tunnel_mode TEXT, provider TEXT
);
CREATE INDEX idx_probe_vpn_created_at ON probe_vpn(created_at);
CREATE INDEX idx_probe_vpn_updated_at ON probe_vpn(updated_at);

CREATE TABLE probe_ip (
    created_at REAL NOT NULL, updated_at REAL NOT NULL,
    ip TEXT, country_code TEXT
);
CREATE INDEX idx_probe_ip_created_at ON probe_ip(created_at);
CREATE INDEX idx_probe_ip_updated_at ON probe_ip(updated_at);

CREATE TABLE probe_dns (
    created_at REAL NOT NULL,
    primary_ms REAL,
    primary_error TEXT,
    primary_address TEXT,
    resolvers_json TEXT NOT NULL
);
CREATE INDEX idx_probe_dns_created_at ON probe_dns(created_at);
"""


class Db(SqliteDb):
    """Database access object for probe data."""

    def __init__(self, db_path: Path) -> None:
        """Open database and run pending migrations.

        Args:
            db_path: Path to the SQLite database file.

        """
        super().__init__(db_path, migrations=(_MIGRATE_V1,))

    # -- Warm latency probes ---------------------------------------------------

    def insert_probe_latency_warm(self, ts: datetime, latency_ms: float | None, endpoint: str | None) -> None:
        """Insert a single warm-latency probe result."""
        self.conn.execute(
            "INSERT INTO probe_latency_warm (created_at, latency_ms, endpoint) VALUES (?, ?, ?)",
            (ts.timestamp(), latency_ms, endpoint),
        )
        self.conn.commit()

    def fetch_latest_probe_latency_warm(self) -> ProbeLatencyWarm | None:
        """Return the most recent warm-latency probe, or None if table is empty."""
        row = self.conn.execute(
            "SELECT created_at, latency_ms, endpoint FROM probe_latency_warm ORDER BY created_at DESC LIMIT 1",
        ).fetchone()
        return ProbeLatencyWarm.from_row(row) if row else None

    def fetch_recent_probe_latency_warm(self, limit: int) -> list[ProbeLatencyWarm]:
        """Return the last *limit* warm-latency probes, ordered oldest-first (for sparkline)."""
        rows = self.conn.execute(
            "SELECT created_at, latency_ms, endpoint FROM probe_latency_warm ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [ProbeLatencyWarm.from_row(r) for r in reversed(rows)]

    def purge_old_probe_latency_warm(self, retention_days: int) -> int:
        """Delete warm-latency probes older than *retention_days*. Return rows deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
        cursor = self.conn.execute("DELETE FROM probe_latency_warm WHERE created_at < ?", (cutoff.timestamp(),))
        self.conn.commit()
        return cursor.rowcount

    # -- Cold latency probes ---------------------------------------------------

    def insert_probe_latency_cold(self, ts: datetime, latency_ms: float | None, endpoint: str | None) -> None:
        """Insert a single cold-latency probe result."""
        self.conn.execute(
            "INSERT INTO probe_latency_cold (created_at, latency_ms, endpoint) VALUES (?, ?, ?)",
            (ts.timestamp(), latency_ms, endpoint),
        )
        self.conn.commit()

    def fetch_latest_probe_latency_cold(self) -> ProbeLatencyCold | None:
        """Return the most recent cold-latency probe, or None if table is empty."""
        row = self.conn.execute(
            "SELECT created_at, latency_ms, endpoint FROM probe_latency_cold ORDER BY created_at DESC LIMIT 1",
        ).fetchone()
        return ProbeLatencyCold.from_row(row) if row else None

    def fetch_recent_probe_latency_cold(self, limit: int) -> list[ProbeLatencyCold]:
        """Return the last *limit* cold-latency probes, ordered oldest-first (for sparkline)."""
        rows = self.conn.execute(
            "SELECT created_at, latency_ms, endpoint FROM probe_latency_cold ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [ProbeLatencyCold.from_row(r) for r in reversed(rows)]

    def purge_old_probe_latency_cold(self, retention_days: int) -> int:
        """Delete cold-latency probes older than *retention_days*. Return rows deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
        cursor = self.conn.execute("DELETE FROM probe_latency_cold WHERE created_at < ?", (cutoff.timestamp(),))
        self.conn.commit()
        return cursor.rowcount

    # -- VPN probes ------------------------------------------------------------

    def upsert_probe_vpn(self, ts: datetime, is_active: bool, tunnel_mode: TunnelMode | None, provider: str | None) -> None:
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

    def fetch_recent_probe_vpn(self, limit: int) -> list[ProbeVpn]:
        """Return the last *limit* VPN state changes, ordered newest-first."""
        rows = self.conn.execute(
            "SELECT created_at, updated_at, is_active, tunnel_mode, provider FROM probe_vpn ORDER BY created_at DESC LIMIT ?",
            (limit,),
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

    def fetch_country_for_ip(self, ip: str) -> str | None:
        """Return the most recent known country_code for *ip*, or None if unseen."""
        row = self.conn.execute(
            "SELECT country_code FROM probe_ip WHERE ip = ? AND country_code IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
            (ip,),
        ).fetchone()
        return row["country_code"] if row else None

    def fetch_recent_probe_ip(self, limit: int) -> list[ProbeIp]:
        """Return the last *limit* IP state changes, ordered newest-first."""
        rows = self.conn.execute(
            "SELECT created_at, updated_at, ip, country_code FROM probe_ip ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [ProbeIp.from_row(r) for r in rows]

    def purge_old_probe_ip(self, retention_days: int) -> int:
        """Delete IP probes not confirmed within *retention_days*. Return rows deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
        cursor = self.conn.execute("DELETE FROM probe_ip WHERE updated_at < ?", (cutoff.timestamp(),))
        self.conn.commit()
        return cursor.rowcount

    # -- DNS probes ------------------------------------------------------------

    def insert_probe_dns(self, ts: datetime, result: DnsResult) -> None:
        """Insert a single DNS probe result. Primary scalars are derived from resolvers[0]."""
        primary = result.resolvers[0] if result.resolvers else None
        resolvers_json = json.dumps([s.model_dump() for s in result.resolvers])
        self.conn.execute(
            "INSERT INTO probe_dns (created_at, primary_ms, primary_error, primary_address, resolvers_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                ts.timestamp(),
                primary.resolve_ms if primary else None,
                primary.error if primary else None,
                primary.address if primary else None,
                resolvers_json,
            ),
        )
        self.conn.commit()

    def fetch_latest_probe_dns(self) -> ProbeDns | None:
        """Return the most recent DNS probe, or None if table is empty."""
        row = self.conn.execute(
            "SELECT created_at, primary_ms, primary_error, primary_address, resolvers_json "
            "FROM probe_dns ORDER BY created_at DESC LIMIT 1",
        ).fetchone()
        return ProbeDns.from_row(row) if row else None

    def fetch_recent_probe_dns(self, limit: int) -> list[ProbeDns]:
        """Return the last *limit* DNS probes, ordered oldest-first (for sparkline / history consistency)."""
        rows = self.conn.execute(
            "SELECT created_at, primary_ms, primary_error, primary_address, resolvers_json "
            "FROM probe_dns ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [ProbeDns.from_row(r) for r in reversed(rows)]

    def purge_old_probe_dns(self, retention_days: int) -> int:
        """Delete DNS probes older than *retention_days*. Return rows deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
        cursor = self.conn.execute("DELETE FROM probe_dns WHERE created_at < ?", (cutoff.timestamp(),))
        self.conn.commit()
        return cursor.rowcount
