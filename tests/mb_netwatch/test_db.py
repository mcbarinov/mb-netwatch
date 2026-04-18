"""Tests for SQLite database operations."""

from datetime import UTC, datetime, timedelta

import pytest

from mb_netwatch.core.db import Db, ProbeIp, ProbeLatencyCold, ProbeLatencyWarm, ProbeVpn


@pytest.fixture
def db(tmp_path):
    """Create a Db instance backed by a temp file."""
    database = Db(tmp_path / "test.db")
    yield database
    database.close()


# -- Latency probes ------------------------------------------------------------

# Both warm and cold latency tables have identical schemas and DB APIs.
# We parametrize every test across the two probe kinds to guarantee both stay in sync.
_LATENCY_KINDS = [
    pytest.param(
        (
            "insert_probe_latency_warm",
            "fetch_latest_probe_latency_warm",
            "fetch_recent_probe_latency_warm",
            "purge_old_probe_latency_warm",
            ProbeLatencyWarm,
        ),
        id="warm",
    ),
    pytest.param(
        (
            "insert_probe_latency_cold",
            "fetch_latest_probe_latency_cold",
            "fetch_recent_probe_latency_cold",
            "purge_old_probe_latency_cold",
            ProbeLatencyCold,
        ),
        id="cold",
    ),
]


class TestProbeLatency:
    """Insert, fetch, and purge latency probe rows — same behaviour for warm and cold."""

    @pytest.mark.parametrize("api", _LATENCY_KINDS)
    def test_insert_and_fetch_latest(self, db, api):
        """Insert a row and read it back via fetch_latest."""
        insert_name, fetch_latest_name, _, _, row_cls = api
        insert = getattr(db, insert_name)
        fetch_latest = getattr(db, fetch_latest_name)

        ts = datetime.now(tz=UTC)
        insert(ts, 42.5, "https://example.com")
        row = fetch_latest()
        assert row is not None
        assert isinstance(row, row_cls)
        assert row.created_at == pytest.approx(ts.timestamp())
        assert row.latency_ms == pytest.approx(42.5)
        assert row.endpoint == "https://example.com"

    @pytest.mark.parametrize("api", _LATENCY_KINDS)
    def test_fetch_latest_empty(self, db, api):
        """Empty table returns None."""
        _, fetch_latest_name, _, _, _ = api
        assert getattr(db, fetch_latest_name)() is None

    @pytest.mark.parametrize("api", _LATENCY_KINDS)
    def test_fetch_latest_returns_most_recent(self, db, api):
        """Multiple inserts — fetch_latest returns the newest row."""
        insert_name, fetch_latest_name, _, _, _ = api
        insert = getattr(db, insert_name)
        fetch_latest = getattr(db, fetch_latest_name)

        now = datetime.now(tz=UTC)
        insert(now - timedelta(seconds=10), 100.0, "a")
        insert(now - timedelta(seconds=5), 200.0, "b")
        insert(now, 300.0, "c")
        row = fetch_latest()
        assert row is not None
        assert row.latency_ms == pytest.approx(300.0)
        assert row.endpoint == "c"

    @pytest.mark.parametrize("api", _LATENCY_KINDS)
    def test_fetch_recent(self, db, api):
        """fetch_recent returns last N rows oldest-first."""
        insert_name, _, fetch_recent_name, _, _ = api
        insert = getattr(db, insert_name)
        fetch_recent = getattr(db, fetch_recent_name)

        now = datetime.now(tz=UTC)
        for i in range(5):
            insert(now - timedelta(seconds=10 - i * 2), float(i * 10), f"e{i}")
        rows = fetch_recent(3)
        assert len(rows) == 3
        assert rows[0].latency_ms == pytest.approx(20.0)
        assert rows[2].latency_ms == pytest.approx(40.0)
        assert rows[0].created_at < rows[1].created_at < rows[2].created_at

    @pytest.mark.parametrize("api", _LATENCY_KINDS)
    def test_fetch_recent_empty(self, db, api):
        """fetch_recent on empty table returns empty list."""
        _, _, fetch_recent_name, _, _ = api
        assert getattr(db, fetch_recent_name)(10) == []

    @pytest.mark.parametrize("api", _LATENCY_KINDS)
    def test_purge_old(self, db, api):
        """Purge deletes old rows and keeps recent ones."""
        insert_name, _, fetch_recent_name, purge_name, _ = api
        insert = getattr(db, insert_name)
        fetch_recent = getattr(db, fetch_recent_name)
        purge = getattr(db, purge_name)

        now = datetime.now(tz=UTC)
        old = now - timedelta(days=60)
        insert(old, 1.0, "old")
        insert(now, 2.0, "recent")

        deleted = purge(retention_days=30)
        assert deleted == 1
        rows = fetch_recent(100)
        assert len(rows) == 1
        assert rows[0].endpoint == "recent"

    @pytest.mark.parametrize("api", _LATENCY_KINDS)
    def test_null_latency(self, db, api):
        """None latency_ms and endpoint stored and retrieved correctly."""
        insert_name, fetch_latest_name, _, _, _ = api
        insert = getattr(db, insert_name)
        fetch_latest = getattr(db, fetch_latest_name)

        ts = datetime.now(tz=UTC)
        insert(ts, None, None)
        row = fetch_latest()
        assert row is not None
        assert row.latency_ms is None
        assert row.endpoint is None

    def test_warm_and_cold_are_isolated(self, db):
        """Writes to one latency table do not appear in the other."""
        ts = datetime.now(tz=UTC)
        db.insert_probe_latency_warm(ts, 50.0, "warm-endpoint")
        db.insert_probe_latency_cold(ts, 200.0, "cold-endpoint")

        warm = db.fetch_latest_probe_latency_warm()
        cold = db.fetch_latest_probe_latency_cold()
        assert warm is not None and warm.endpoint == "warm-endpoint"
        assert cold is not None and cold.endpoint == "cold-endpoint"
        assert warm.latency_ms == pytest.approx(50.0)
        assert cold.latency_ms == pytest.approx(200.0)


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
        rows = db.fetch_recent_probe_vpn(100)
        assert len(rows) == 1
        assert rows[0].created_at == pytest.approx(t1.timestamp())
        assert rows[0].updated_at == pytest.approx(t2.timestamp())

    def test_upsert_change_creates_new_row(self, db):
        """Different state creates a new row."""
        t1 = datetime.now(tz=UTC) - timedelta(seconds=10)
        t2 = datetime.now(tz=UTC)
        db.upsert_probe_vpn(t1, True, "full", None)
        db.upsert_probe_vpn(t2, False, "split", None)
        rows = db.fetch_recent_probe_vpn(100)
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

        rows = db.fetch_recent_probe_vpn(100)
        # newest-first, so rows[1] is the older (active) row
        assert rows[1].is_active is True
        assert isinstance(rows[1].is_active, bool)

    def test_fetch_latest_empty(self, db):
        """Empty table returns None."""
        assert db.fetch_latest_probe_vpn() is None

    def test_fetch_recent(self, db):
        """fetch_recent returns last N state changes newest-first."""
        now = datetime.now(tz=UTC)
        db.upsert_probe_vpn(now - timedelta(seconds=30), True, "full", None)
        db.upsert_probe_vpn(now - timedelta(seconds=20), False, "split", None)
        db.upsert_probe_vpn(now - timedelta(seconds=10), True, "full", "NordVPN")
        rows = db.fetch_recent_probe_vpn(2)
        assert len(rows) == 2
        assert rows[0].provider == "NordVPN"
        assert rows[1].tunnel_mode == "split"

    def test_purge_old(self, db):
        """Purge deletes rows not confirmed recently, keeps recent."""
        now = datetime.now(tz=UTC)
        old = now - timedelta(days=60)
        db.upsert_probe_vpn(old, True, "full", None)
        db.upsert_probe_vpn(now, False, "split", None)

        deleted = db.purge_old_probe_vpn(retention_days=30)
        assert deleted == 1
        rows = db.fetch_recent_probe_vpn(100)
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

    def test_null_tunnel_mode_dedup(self, db):
        """Consecutive inactive states with tunnel_mode=None are deduplicated."""
        t1 = datetime.now(tz=UTC) - timedelta(seconds=10)
        t2 = datetime.now(tz=UTC)
        db.upsert_probe_vpn(t1, False, None, None)
        db.upsert_probe_vpn(t2, False, None, None)
        rows = db.fetch_recent_probe_vpn(100)
        assert len(rows) == 1
        assert rows[0].tunnel_mode is None
        assert rows[0].is_active is False
        assert rows[0].created_at == pytest.approx(t1.timestamp())
        assert rows[0].updated_at == pytest.approx(t2.timestamp())


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
        rows = db.fetch_recent_probe_ip(100)
        assert len(rows) == 1
        assert rows[0].created_at == pytest.approx(t1.timestamp())
        assert rows[0].updated_at == pytest.approx(t2.timestamp())

    def test_upsert_different_ip_creates_new_row(self, db):
        """Different IP creates a new row."""
        t1 = datetime.now(tz=UTC) - timedelta(seconds=10)
        t2 = datetime.now(tz=UTC)
        db.upsert_probe_ip(t1, "1.1.1.1", "US")
        db.upsert_probe_ip(t2, "2.2.2.2", "DE")
        rows = db.fetch_recent_probe_ip(100)
        assert len(rows) == 2

    def test_upsert_country_change_creates_new_row(self, db):
        """Same IP but different country_code creates a new row."""
        t1 = datetime.now(tz=UTC) - timedelta(seconds=10)
        t2 = datetime.now(tz=UTC)
        db.upsert_probe_ip(t1, "1.1.1.1", "US")
        db.upsert_probe_ip(t2, "1.1.1.1", "DE")
        rows = db.fetch_recent_probe_ip(100)
        assert len(rows) == 2

    def test_upsert_null_dedup(self, db):
        """None ip and country_code deduplicated correctly."""
        t1 = datetime.now(tz=UTC) - timedelta(seconds=10)
        t2 = datetime.now(tz=UTC)
        db.upsert_probe_ip(t1, None, None)
        db.upsert_probe_ip(t2, None, None)
        rows = db.fetch_recent_probe_ip(100)
        assert len(rows) == 1
        assert rows[0].ip is None
        assert rows[0].country_code is None

    def test_fetch_latest_empty(self, db):
        """Empty table returns None."""
        assert db.fetch_latest_probe_ip() is None

    def test_fetch_recent(self, db):
        """fetch_recent returns last N IP state changes newest-first."""
        now = datetime.now(tz=UTC)
        db.upsert_probe_ip(now - timedelta(seconds=30), "1.1.1.1", "US")
        db.upsert_probe_ip(now - timedelta(seconds=20), "2.2.2.2", "DE")
        db.upsert_probe_ip(now - timedelta(seconds=10), "3.3.3.3", "FR")
        rows = db.fetch_recent_probe_ip(2)
        assert len(rows) == 2
        assert rows[0].ip == "3.3.3.3"
        assert rows[1].ip == "2.2.2.2"

    def test_purge_old(self, db):
        """Purge deletes rows not confirmed recently, keeps recent."""
        now = datetime.now(tz=UTC)
        old = now - timedelta(days=60)
        db.upsert_probe_ip(old, "1.1.1.1", "US")
        db.upsert_probe_ip(now, "2.2.2.2", "DE")

        deleted = db.purge_old_probe_ip(retention_days=30)
        assert deleted == 1
        rows = db.fetch_recent_probe_ip(100)
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
        """Fresh DB gets schema — every table can accept inserts."""
        ts = datetime.now(tz=UTC)
        db.insert_probe_latency_warm(ts, 1.0, "a")
        db.insert_probe_latency_cold(ts, 2.0, "b")
        db.upsert_probe_vpn(ts, False, "split", None)
        db.upsert_probe_ip(ts, "1.2.3.4", "US")
        assert db.fetch_latest_probe_latency_warm() is not None
        assert db.fetch_latest_probe_latency_cold() is not None
        assert db.fetch_latest_probe_vpn() is not None
        assert db.fetch_latest_probe_ip() is not None

    def test_reopen_idempotent(self, tmp_path):
        """Re-opening the same DB file doesn't fail — migrations are idempotent."""
        db_path = tmp_path / "test.db"
        db1 = Db(db_path)
        db1.insert_probe_latency_warm(datetime.now(tz=UTC), 10.0, "a")
        db1.insert_probe_latency_cold(datetime.now(tz=UTC), 20.0, "b")
        db1.close()

        db2 = Db(db_path)
        warm = db2.fetch_latest_probe_latency_warm()
        cold = db2.fetch_latest_probe_latency_cold()
        assert warm is not None and warm.latency_ms == pytest.approx(10.0)
        assert cold is not None and cold.latency_ms == pytest.approx(20.0)
        db2.close()
