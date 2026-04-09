"""Tests for TUI sparkline rendering."""

from mb_netwatch.core.db import ProbeLatency
from mb_netwatch.tui.widgets.latency import build_sparkline


class TestBuildSparkline:
    """Sparkline rendering from latency history."""

    def test_empty_history(self):
        """Empty history returns 'no data'."""
        result = build_sparkline([], 300, 800)
        assert result.plain == "no data"

    def test_renders_chars(self):
        """Non-empty history renders sparkline characters."""
        history = [ProbeLatency(created_at=float(i), latency_ms=float(i * 100), winner_endpoint=None) for i in range(1, 5)]
        result = build_sparkline(history, 300, 800)
        assert len(result.plain) == 4
        assert all(c in "▁▂▃▄▅▆▇█" for c in result.plain)

    def test_down_shows_cross(self):
        """None latency renders as ✕."""
        history = [ProbeLatency(created_at=1.0, latency_ms=None, winner_endpoint=None)]
        result = build_sparkline(history, 300, 800)
        assert "✕" in result.plain
