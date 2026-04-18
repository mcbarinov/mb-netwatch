"""Latency sparkline widget (shared by warm and cold probes)."""

from collections.abc import Sequence
from typing import Literal

from rich.text import Text
from textual.widget import Widget

from mb_netwatch.core.db import ProbeLatencyCold, ProbeLatencyWarm

_LatencyRow = ProbeLatencyWarm | ProbeLatencyCold

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def latency_style(ms: float | None, ok_ms: int, slow_ms: int) -> str:
    """Return a Rich style string for a latency value."""
    if ms is None:
        return "bold red"
    if ms < ok_ms:
        return "green"
    if ms < slow_ms:
        return "yellow"
    return "red"


def build_sparkline(history: Sequence[_LatencyRow], ok_ms: int, slow_ms: int) -> Text:
    """Build a colored sparkline Text from latency history."""
    values = [r.latency_ms for r in history]
    if not values:
        return Text("no data", style="dim")

    nums = [v for v in values if v is not None]
    max_val = max(nums) if nums else 1.0

    text = Text()
    for v in values:
        if v is None:
            text.append("✕", style="dim red")
        else:
            idx = min(int(v / max_val * (len(_SPARK_CHARS) - 1)), len(_SPARK_CHARS) - 1)
            text.append(_SPARK_CHARS[idx], style=latency_style(v, ok_ms, slow_ms))
    return text


def _build_stats_line(history: Sequence[_LatencyRow]) -> Text:
    """Build stats summary line: min / avg / p95 / max / down count."""
    values = [r.latency_ms for r in history]
    nums = sorted(v for v in values if v is not None)
    down_count = sum(1 for v in values if v is None)

    if not nums:
        return Text(f"down {down_count}", style="dim")

    avg = sum(nums) / len(nums)
    p95_idx = max(0, int(len(nums) * 0.95) - 1)
    text = Text()
    text.append(f"min {nums[0]:.0f}    avg {avg:.0f}    p95 {nums[p95_idx]:.0f}    max {nums[-1]:.0f}", style="dim")
    if down_count:
        text.append(f"    down {down_count}", style="dim red")
    return text


class LatencyWidget(Widget):
    """Latency sparkline with stats line. Parametrized by probe kind (warm or cold)."""

    DEFAULT_CSS = """
    LatencyWidget {
        height: auto;
        max-height: 6;
        border: round $accent;
        border-title-color: $text;
        padding: 0 1;
    }
    """

    def __init__(self, kind: Literal["warm", "cold"]) -> None:
        """Initialize for the given probe kind.

        Args:
            kind: Probe kind. Drives the widget's DOM id (``latency-warm`` / ``latency-cold``)
                and the border title shown to the user.

        """
        super().__init__(id=f"latency-{kind}")
        self._kind = kind  # Probe kind ("warm" or "cold") — determines title and callers' data source
        self.border_title = f"Latency ({kind})"
        self._history: Sequence[_LatencyRow] = []  # Latest latency readings for this kind
        self._ok_ms: int = 300  # OK threshold (milliseconds); overwritten on first update_data
        self._slow_ms: int = 800  # Slow threshold (milliseconds); overwritten on first update_data

    @property
    def content_width(self) -> int:
        """Usable width for sparkline characters."""
        return self.scrollable_content_region.width

    def update_data(self, history: Sequence[_LatencyRow], ok_ms: int, slow_ms: int) -> None:
        """Set new latency data and trigger re-render."""
        self._history = history
        self._ok_ms = ok_ms
        self._slow_ms = slow_ms
        self.refresh()

    def render(self) -> Text:
        """Render sparkline and stats, right-aligned."""
        spark_text = build_sparkline(self._history, self._ok_ms, self._slow_ms)
        width = self.scrollable_content_region.width
        # Right-align: newest data hugs the right edge, grows leftward
        if width > 0 and len(spark_text) < width:
            spark_text.pad_left(width - len(spark_text))
        spark_text.append("\n")
        spark_text.append_text(_build_stats_line(self._history))
        return spark_text
