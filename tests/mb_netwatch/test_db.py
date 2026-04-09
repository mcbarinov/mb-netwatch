"""Tests for SQLite database operations."""

from datetime import UTC, datetime, timedelta

import pytest

from mb_netwatch.core.db import Db, ProbeIp, ProbeLatency, ProbeVpn


@pytest.fixture
def db(tmp_path):
    """Create a Db instance backed by a temp file."""
    database = Db(tmp_path / "test.db")
    yield database
    database.close()


# -- Latency probes ------------------------------------------------------------


class TestProbeLatency:
    """Insert, fetch, and purge latency probe rows."""

    def test_insert_and_fetch_latest(self, db):
        """Insert a row and read it back via fetch_latest."""
        ts = datetime.now(tz=UTC)
        db.insert_probe_latency(ts, 42.5, "https://example.com")
        row = db.fetch_latest_probe_latency()
        assert row is not None
        assert isinstance(row, ProbeLatency)
        assert row.created_at == pytest.approx(ts.timestamp())
        assert row.latency_ms == pytest.approx(42.5)
        assert row.winner_endpoint == "https://example.com"

    def test_fetch_latest_empty(self, db):
        """Empty table returns None."""
        assert db.fetch_latest_probe_latency() is None

    def test_fetch_latest_returns_most_recent(self, db):
        """Multiple inserts — fetch_latest returns the newest row."""
        now = datetime.now(tz=UTC)
        db.insert_probe_latency(now - timedelta(seconds=10), 100.0, "a")
        db.insert_probe_latency(now - timedelta(seconds=5), 200.0, "b")
        db.insert_probe_latency(now, 300.0, "c")
        row = db.fetch_latest_probe_latency()
        assert row is not None
        assert row.latency_ms == pytest.approx(300.0)
        assert row.winner_endpoint == "c"

    def test_fetch_since(self, db):
        """fetch_since returns only rows newer than the threshold, ascending."""
        now = datetime.now(tz=UTC)
        t1 = now - timedelta(seconds=30)
        t2 = now - timedelta(seconds=20)
        t3 = now - timedelta(seconds=10)
        db.insert_probe_latency(t1, 10.0, "a")
        db.insert_probe_latency(t2, 20.0, "b")
        db.insert_probe_latency(t3, 30.0, "c")

        rows = db.fetch_probe_latency_since(t1.timestamp())
        assert len(rows) == 2
        assert rows[0].latency_ms == pytest.approx(20.0)
        assert rows[1].latency_ms == pytest.approx(30.0)

    def test_purge_old(self, db):
        """Purge deletes old rows and keeps recent ones."""
        now = datetime.now(tz=UTC)
        old = now - timedelta(days=60)
        db.insert_probe_latency(old, 1.0, "old")
        db.insert_probe_latency(now, 2.0, "recent")

        deleted = db.purge_old_probe_latency(retention_days=30)
        assert deleted == 1
        rows = db.fetch_probe_latency_since(0.0)
        assert len(rows) == 1
        assert rows[0].winner_endpoint == "recent"

    def test_null_latency(self, db):
        """None latency_ms and winner_endpoint stored and retrieved correctly."""
        ts = datetime.now(tz=UTC)
        db.insert_probe_latency(ts, None, None)
        row = db.fetch_latest_probe_latency()
        assert row is not None
        assert row.latency_ms is None
        assert row.winner_endpoint is None


# -- VPN probes ----------------------------------------------------------------


class TestProbeVpn:
    """Upsert, fetch, and purge VPN probe rows."""

    def test_upsert_and_fetch_latest(self, db):
        """Upsert a row and read it back via fetch_latest."""
        ts = datetime.now(tz=UTC)
        db.upsert_probe_vpn(ts, True, "full", "WireGuard")
        row = db.fetch_latest_probe_vpn()
        assert row is not None
        assert isinstance(row, ProbeVpn)
        assert row.created_at == pytest.approx(ts.timestamp())
        assert row.updated_at == pytest.approx(ts.timestamp())
        assert row.is_active is True
        assert row.tunnel_mode == "full"
        assert row.provider == "WireGuard"

    def test_upsert_dedup(self, db):
        """Same state twice creates one row with advanced updated_at."""
        t1 = datetime.now(tz=UTC) - timedelta(seconds=10)
        t2 = datetime.now(tz=UTC)
        db.upsert_probe_vpn(t1, True, "full", "WireGuard")
        db.upsert_probe_vpn(t2, True, "full", "WireGuard")
        rows = db.fetch_probe_vpn_since(0.0)
        assert len(rows) == 1
        assert rows[0].created_at == pytest.approx(t1.timestamp())
        assert rows[0].updated_at == pytest.approx(t2.timestamp())

    def test_upsert_change_creates_new_row(self, db):
        """Different state creates a new row."""
        t1 = datetime.now(tz=UTC) - timedelta(seconds=10)
        t2 = datetime.now(tz=UTC)
        db.upsert_probe_vpn(t1, True, "full", None)
        db.upsert_probe_vpn(t2, False, "split", None)
        rows = db.fetch_probe_vpn_since(0.0)
        assert len(rows) == 2

    def test_is_active_bool_conversion(self, db):
        """is_active stored as int(1/0), read back as bool."""
        ts = datetime.now(tz=UTC)
        db.upsert_probe_vpn(ts - timedelta(seconds=1), True, "full", None)
        db.upsert_probe_vpn(ts, False, "split", None)

        latest = db.fetch_latest_probe_vpn()
        assert latest is not None
        assert latest.is_active is False
        assert isinstance(latest.is_active, bool)

        rows = db.fetch_probe_vpn_since(0.0)
        assert rows[0].is_active is True
        assert isinstance(rows[0].is_active, bool)

    def test_fetch_latest_empty(self, db):
        """Empty table returns None."""
        assert db.fetch_latest_probe_vpn() is None

    def test_fetch_since(self, db):
        """fetch_since returns only state changes after the cursor."""
        now = datetime.now(tz=UTC)
        t1 = now - timedelta(seconds=20)
        t2 = now - timedelta(seconds=10)
        db.upsert_probe_vpn(t1, True, "full", None)
        db.upsert_probe_vpn(t2, False, "split", "NordVPN")

        rows = db.fetch_probe_vpn_since(t1.timestamp())
        assert len(rows) == 1
        assert rows[0].tunnel_mode == "split"
        assert rows[0].provider == "NordVPN"

    def test_purge_old(self, db):
        """Purge deletes rows not confirmed recently, keeps recent."""
        now = datetime.now(tz=UTC)
        old = now - timedelta(days=60)
        db.upsert_probe_vpn(old, True, "full", None)
        db.upsert_probe_vpn(now, False, "split", None)

        deleted = db.purge_old_probe_vpn(retention_days=30)
        assert deleted == 1
        rows = db.fetch_probe_vpn_since(0.0)
        assert len(rows) == 1
        assert rows[0].is_active is False

    def test_purge_spares_recently_updated(self, db):
        """Row with old created_at but recent updated_at survives purge."""
        old = datetime.now(tz=UTC) - timedelta(days=60)
        recent = datetime.now(tz=UTC)
        db.upsert_probe_vpn(old, True, "full", None)
        db.upsert_probe_vpn(recent, True, "full", None)  # same state — bumps updated_at
        deleted = db.purge_old_probe_vpn(retention_days=30)
        assert deleted == 0


# -- IP probes ----------------------------------------------------------------


class TestProbeIp:
    """Upsert, fetch, and purge IP probe rows."""

    def test_upsert_and_fetch_latest(self, db):
        """Upsert a row and read it back via fetch_latest."""
        ts = datetime.now(tz=UTC)
        db.upsert_probe_ip(ts, "1.2.3.4", "US")
        row = db.fetch_latest_probe_ip()
        assert row is not None
        assert isinstance(row, ProbeIp)
        assert row.created_at == pytest.approx(ts.timestamp())
        assert row.updated_at == pytest.approx(ts.timestamp())
        assert row.ip == "1.2.3.4"
        assert row.country_code == "US"

    def test_upsert_dedup(self, db):
        """Same (ip, country_code) twice creates one row with advanced updated_at."""
        t1 = datetime.now(tz=UTC) - timedelta(seconds=10)
        t2 = datetime.now(tz=UTC)
        db.upsert_probe_ip(t1, "1.2.3.4", "US")
        db.upsert_probe_ip(t2, "1.2.3.4", "US")
        rows = db.fetch_probe_ip_since(0.0)
        assert len(rows) == 1
        assert rows[0].created_at == pytest.approx(t1.timestamp())
        assert rows[0].updated_at == pytest.approx(t2.timestamp())

    def test_upsert_different_ip_creates_new_row(self, db):
        """Different IP creates a new row."""
        t1 = datetime.now(tz=UTC) - timedelta(seconds=10)
        t2 = datetime.now(tz=UTC)
        db.upsert_probe_ip(t1, "1.1.1.1", "US")
        db.upsert_probe_ip(t2, "2.2.2.2", "DE")
        rows = db.fetch_probe_ip_since(0.0)
        assert len(rows) == 2

    def test_upsert_country_change_creates_new_row(self, db):
        """Same IP but different country_code creates a new row."""
        t1 = datetime.now(tz=UTC) - timedelta(seconds=10)
        t2 = datetime.now(tz=UTC)
        db.upsert_probe_ip(t1, "1.1.1.1", "US")
        db.upsert_probe_ip(t2, "1.1.1.1", "DE")
        rows = db.fetch_probe_ip_since(0.0)
        assert len(rows) == 2

    def test_upsert_null_dedup(self, db):
        """None ip and country_code deduplicated correctly."""
        t1 = datetime.now(tz=UTC) - timedelta(seconds=10)
        t2 = datetime.now(tz=UTC)
        db.upsert_probe_ip(t1, None, None)
        db.upsert_probe_ip(t2, None, None)
        rows = db.fetch_probe_ip_since(0.0)
        assert len(rows) == 1
        assert rows[0].ip is None
        assert rows[0].country_code is None

    def test_fetch_latest_empty(self, db):
        """Empty table returns None."""
        assert db.fetch_latest_probe_ip() is None

    def test_fetch_since(self, db):
        """fetch_since returns only IP changes after the cursor."""
        now = datetime.now(tz=UTC)
        t1 = now - timedelta(seconds=20)
        t2 = now - timedelta(seconds=10)
        db.upsert_probe_ip(t1, "1.1.1.1", "US")
        db.upsert_probe_ip(t2, "2.2.2.2", "DE")

        rows = db.fetch_probe_ip_since(t1.timestamp())
        assert len(rows) == 1
        assert rows[0].ip == "2.2.2.2"
        assert rows[0].country_code == "DE"

    def test_purge_old(self, db):
        """Purge deletes rows not confirmed recently, keeps recent."""
        now = datetime.now(tz=UTC)
        old = now - timedelta(days=60)
        db.upsert_probe_ip(old, "1.1.1.1", "US")
        db.upsert_probe_ip(now, "2.2.2.2", "DE")

        deleted = db.purge_old_probe_ip(retention_days=30)
        assert deleted == 1
        rows = db.fetch_probe_ip_since(0.0)
        assert len(rows) == 1
        assert rows[0].ip == "2.2.2.2"

    def test_purge_spares_recently_updated(self, db):
        """Row with old created_at but recent updated_at survives purge."""
        old = datetime.now(tz=UTC) - timedelta(days=60)
        recent = datetime.now(tz=UTC)
        db.upsert_probe_ip(old, "1.1.1.1", "US")
        db.upsert_probe_ip(recent, "1.1.1.1", "US")  # same — bumps updated_at
        deleted = db.purge_old_probe_ip(retention_days=30)
        assert deleted == 0


# -- Migrations ----------------------------------------------------------------


class TestMigrations:
    """Schema creation and idempotency."""

    def test_fresh_db_has_tables(self, db):
        """Fresh DB gets schema — all three tables can accept inserts."""
        ts = datetime.now(tz=UTC)
        db.insert_probe_latency(ts, 1.0, "a")
        db.upsert_probe_vpn(ts, False, "split", None)
        db.upsert_probe_ip(ts, "1.2.3.4", "US")
        assert db.fetch_latest_probe_latency() is not None
        assert db.fetch_latest_probe_vpn() is not None
        assert db.fetch_latest_probe_ip() is not None

    def test_reopen_idempotent(self, tmp_path):
        """Re-opening the same DB file doesn't fail — migrations are idempotent."""
        db_path = tmp_path / "test.db"
        db1 = Db(db_path)
        db1.insert_probe_latency(datetime.now(tz=UTC), 10.0, "a")
        db1.close()

        db2 = Db(db_path)
        row = db2.fetch_latest_probe_latency()
        assert row is not None
        assert row.latency_ms == pytest.approx(10.0)
        db2.close()
