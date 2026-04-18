"""DNS sparkline widget — primary-resolver latency over time with error markers."""

from collections.abc import Sequence

from rich.text import Text
from textual.widget import Widget

from mb_netwatch.core.db import ProbeDns

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _build_sparkline(history: Sequence[ProbeDns]) -> Text:
    """Build a colored sparkline Text from DNS history (primary resolver only)."""
    if not history:
        return Text("no data", style="dim")

    # Values used for bar scaling: successful samples only (error=None, ms present).
    success_values = [r.primary_ms for r in history if r.primary_error is None and r.primary_ms is not None]
    max_val = max(success_values) if success_values else 1.0

    text = Text()
    for row in history:
        # Any error (including rcode errors that carry latency) is a visible failure.
        if row.primary_error is not None or row.primary_ms is None:
            text.append("✕", style="dim red")
            continue
        idx = min(int(row.primary_ms / max_val * (len(_SPARK_CHARS) - 1)), len(_SPARK_CHARS) - 1)
        text.append(_SPARK_CHARS[idx], style="cyan")
    return text


def _build_stats_line(history: Sequence[ProbeDns]) -> Text:
    """Build stats summary: resolver address + min/avg/p95/max + error count + extra-resolver hint."""
    if not history:
        return Text("", style="dim")

    latest = history[-1]
    nums = sorted(r.primary_ms for r in history if r.primary_error is None and r.primary_ms is not None)
    error_count = sum(1 for r in history if r.primary_error is not None)

    text = Text()
    if latest.primary_address is None:
        text.append("no config", style="dim red")
    else:
        text.append(latest.primary_address, style="dim")

    if nums:
        avg = sum(nums) / len(nums)
        p95_idx = max(0, int(len(nums) * 0.95) - 1)
        text.append(f"    min {nums[0]:.0f}    avg {avg:.0f}    p95 {nums[p95_idx]:.0f}    max {nums[-1]:.0f}", style="dim")

    if error_count:
        text.append(f"    errors {error_count}", style="dim red")

    extra = len(latest.resolvers) - 1
    if extra > 0:
        text.append(f"    +{extra}", style="dim")

    return text


class DnsWidget(Widget):
    """DNS sparkline with stats line. Shows the primary resolver only."""

    DEFAULT_CSS = """
    DnsWidget {
        height: auto;
        max-height: 6;
        border: round $accent;
        border-title-color: $text;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        """Initialize the DNS widget."""
        super().__init__(id="dns")
        self.border_title = "DNS"
        self._history: Sequence[ProbeDns] = []  # Latest DNS readings (oldest-first)

    @property
    def content_width(self) -> int:
        """Usable width for sparkline characters."""
        return self.scrollable_content_region.width

    def update_data(self, history: Sequence[ProbeDns]) -> None:
        """Set new DNS data and trigger re-render."""
        self._history = history
        self.refresh()

    def render(self) -> Text:
        """Render sparkline and stats, right-aligned like the latency widgets."""
        spark_text = _build_sparkline(self._history)
        width = self.scrollable_content_region.width
        if width > 0 and len(spark_text) < width:
            spark_text.pad_left(width - len(spark_text))
        spark_text.append("\n")
        spark_text.append_text(_build_stats_line(self._history))
        return spark_text
