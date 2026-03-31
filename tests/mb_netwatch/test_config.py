"""Tests for application configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from mb_netwatch.config import Config


class TestDefaults:
    """Default Config values and computed paths."""

    def test_default_intervals(self):
        """Default probed intervals match documented values."""
        cfg = Config()
        assert cfg.probed.latency_interval == 2.0
        assert cfg.probed.vpn_interval == 10.0
        assert cfg.probed.ip_interval == 60.0
        assert cfg.probed.purge_interval == 3600.0
        assert cfg.probed.latency_timeout == 5.0
        assert cfg.probed.ip_timeout == 5.0
        assert cfg.probed.retention_days == 30

    def test_default_tray(self):
        """Default tray settings match documented values."""
        cfg = Config()
        assert cfg.tray.poll_interval == 2.0
        assert cfg.tray.ok_threshold_ms == 300
        assert cfg.tray.slow_threshold_ms == 800
        assert cfg.tray.stale_threshold == 10.0

    def test_default_watch(self):
        """Default watch poll interval."""
        cfg = Config()
        assert cfg.watch.poll_interval == 0.5

    def test_computed_paths(self):
        """Computed paths resolve relative to data_dir."""
        cfg = Config(data_dir=Path("/test/dir"))
        assert cfg.db_path == Path("/test/dir/netwatch.db")
        assert cfg.config_path == Path("/test/dir/config.toml")
        assert cfg.probed_pid_path == Path("/test/dir/probed.pid")
        assert cfg.tray_pid_path == Path("/test/dir/tray.pid")
        assert cfg.probed_log_path == Path("/test/dir/probed.log")
        assert cfg.tray_log_path == Path("/test/dir/tray.log")


class TestTrayThresholdOrdering:
    """ok_threshold_ms must be strictly less than slow_threshold_ms."""

    @pytest.mark.parametrize(
        ("ok", "slow", "should_pass"),
        [
            (100, 500, True),
            (300, 800, True),
            (500, 500, False),
            (800, 300, False),
            (1, 2, True),
        ],
    )
    def test_threshold_ordering(self, ok, slow, should_pass):
        """Threshold ordering validation accepts valid, rejects invalid."""
        if should_pass:
            cfg = Config(tray={"ok_threshold_ms": ok, "slow_threshold_ms": slow})
            assert cfg.tray.ok_threshold_ms == ok
            assert cfg.tray.slow_threshold_ms == slow
        else:
            with pytest.raises(ValidationError, match="ok_threshold_ms"):
                Config(tray={"ok_threshold_ms": ok, "slow_threshold_ms": slow})


class TestFieldValidation:
    """Field constraints and extra="forbid" enforcement."""

    @pytest.mark.parametrize(
        ("section", "field", "value"),
        [
            ("probed", "latency_interval", 0),
            ("probed", "latency_interval", -1),
            ("probed", "vpn_interval", 0),
            ("probed", "ip_interval", -5.0),
            ("probed", "retention_days", 0),
            ("probed", "retention_days", -1),
            ("probed", "latency_timeout", 0),
            ("tray", "poll_interval", 0),
            ("tray", "poll_interval", -1),
            ("tray", "ok_threshold_ms", 0),
            ("tray", "slow_threshold_ms", 0),
            ("tray", "stale_threshold", -1),
            ("watch", "poll_interval", 0),
        ],
    )
    def test_zero_and_negative_values_rejected(self, section, field, value):
        """Zero and negative values for gt=0 fields raise ValidationError."""
        with pytest.raises(ValidationError):
            Config(**{section: {field: value}})

    @pytest.mark.parametrize("section", ["probed", "tray", "watch"])
    def test_extra_fields_forbidden(self, section):
        """Unknown keys within a known section raise ValidationError."""
        with pytest.raises(ValidationError):
            Config(**{section: {"nonexistent_key": 42}})

    def test_extra_top_level_field_forbidden(self):
        """Unknown top-level field raises ValidationError."""
        with pytest.raises(ValidationError):
            Config(unknown_section="oops")


class TestConfigBuild:
    """Config.build() reads TOML from disk or returns defaults."""

    def test_no_config_file_returns_defaults(self, tmp_path):
        """Missing config file returns default Config."""
        cfg = Config.build(data_dir=tmp_path)
        assert cfg.probed.latency_interval == 2.0
        assert cfg.tray.ok_threshold_ms == 300

    def test_partial_override(self, tmp_path):
        """Valid TOML with partial overrides merges with defaults."""
        (tmp_path / "config.toml").write_text("[probed]\nlatency_interval = 5.0\n\n[tray]\nok_threshold_ms = 100\n")

        cfg = Config.build(data_dir=tmp_path)
        assert cfg.probed.latency_interval == 5.0
        assert cfg.probed.vpn_interval == 10.0  # default preserved
        assert cfg.tray.ok_threshold_ms == 100
        assert cfg.tray.slow_threshold_ms == 800  # default preserved

    def test_unknown_section_raises(self, tmp_path):
        """Unknown TOML section raises ValueError."""
        (tmp_path / "config.toml").write_text("[bogus]\nfoo = 1\n")

        with pytest.raises(ValueError, match="Unknown config sections"):
            Config.build(data_dir=tmp_path)

    def test_unknown_key_in_known_section_raises(self, tmp_path):
        """Unknown key inside a known section raises ValidationError (extra=forbid)."""
        (tmp_path / "config.toml").write_text("[probed]\nno_such_key = 99\n")

        with pytest.raises(ValidationError):
            Config.build(data_dir=tmp_path)
