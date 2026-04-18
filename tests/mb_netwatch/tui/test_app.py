"""Tests for TUI sparkline rendering."""

import pytest

from mb_netwatch.core.db import ProbeLatencyCold, ProbeLatencyWarm
from mb_netwatch.tui.widgets.latency import build_sparkline

# build_sparkline accepts either warm or cold rows — same shape, same rendering.
_ROW_CLASSES = [
    pytest.param(ProbeLatencyWarm, id="warm"),
    pytest.param(ProbeLatencyCold, id="cold"),
]


class TestBuildSparkline:
    """Sparkline rendering from latency history (both kinds)."""

    def test_empty_history(self):
        """Empty history returns 'no data'."""
        result = build_sparkline([], 300, 800)
        assert result.plain == "no data"

    @pytest.mark.parametrize("row_cls", _ROW_CLASSES)
    def test_renders_chars(self, row_cls):
        """Non-empty history renders sparkline characters."""
        history = [row_cls(created_at=float(i), latency_ms=float(i * 100), endpoint=None) for i in range(1, 5)]
        result = build_sparkline(history, 300, 800)
        assert len(result.plain) == 4
        assert all(c in "▁▂▃▄▅▆▇█" for c in result.plain)

    @pytest.mark.parametrize("row_cls", _ROW_CLASSES)
    def test_down_shows_cross(self, row_cls):
        """None latency renders as ✕."""
        history = [row_cls(created_at=1.0, latency_ms=None, endpoint=None)]
        result = build_sparkline(history, 300, 800)
        assert "✕" in result.plain
