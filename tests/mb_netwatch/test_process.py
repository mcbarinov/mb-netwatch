"""Tests for process lifecycle management."""

import os

import pytest

from mb_netwatch.process import Component, is_alive, pid_path, read_pid, write_pid_file


class TestPidPath:
    """PID file path resolution."""

    def test_probed(self, tmp_path):
        """PROBED component resolves to probed.pid."""
        assert pid_path(Component.PROBED, tmp_path) == tmp_path / "probed.pid"

    def test_tray(self, tmp_path):
        """TRAY component resolves to tray.pid."""
        assert pid_path(Component.TRAY, tmp_path) == tmp_path / "tray.pid"


class TestReadPid:
    """PID file parsing edge cases."""

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            ("1234\n", 1234),
            ("99999", 99999),
            ("", None),
            ("abc", None),
            ("-1\n", None),
            ("0\n", None),
            ("  \n", None),
        ],
        ids=["valid", "valid-no-newline", "empty", "non-numeric", "negative", "zero", "whitespace-only"],
    )
    def test_content_variants(self, tmp_path, content, expected):
        """Various PID file contents parse correctly."""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text(content)
        assert read_pid(pid_file) == expected

    def test_missing_file(self, tmp_path):
        """Missing file returns None."""
        assert read_pid(tmp_path / "nonexistent.pid") is None


class TestWritePidFile:
    """PID file writing."""

    def test_writes_current_pid(self, tmp_path):
        """Writes current PID, reads back correctly."""
        pid_file = tmp_path / "test.pid"
        write_pid_file(pid_file)
        assert read_pid(pid_file) == os.getpid()

    def test_creates_parent_dirs(self, tmp_path):
        """Creates parent directories if missing."""
        pid_file = tmp_path / "nested" / "deep" / "test.pid"
        write_pid_file(pid_file)
        assert read_pid(pid_file) == os.getpid()


class TestIsAlive:
    """Liveness checks and stale PID file cleanup."""

    def test_nonexistent_pid(self, tmp_path):
        """Nonexistent PID returns False and stale PID file is removed."""
        pid_file = tmp_path / "test.pid"
        # PID 4_000_000 is extremely unlikely to exist
        pid_file.write_text("4000000\n")
        assert is_alive(pid_file) is False
        assert not pid_file.exists()

    def test_current_process_skipped(self, tmp_path):
        """Current process PID returns False (self-skip logic)."""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text(f"{os.getpid()}\n")
        assert is_alive(pid_file) is False

    def test_missing_pid_file(self, tmp_path):
        """Missing PID file returns False."""
        assert is_alive(tmp_path / "nonexistent.pid") is False
