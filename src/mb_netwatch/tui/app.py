"""Textual TUI dashboard for mb-netwatch."""

import os
from datetime import UTC, datetime
from typing import ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from mb_netwatch.config import Config
from mb_netwatch.core.db import Db, ProbeIp, ProbeLatency, ProbeVpn

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _latency_style(ms: float | None, ok_ms: int, slow_ms: int) -> str:
    """Return a Rich style string for a latency value."""
    if ms is None:
        return "bold red"
    if ms < ok_ms:
        return "green"
    if ms < slow_ms:
        return "yellow"
    return "red"


def build_sparkline(history: list[ProbeLatency], ok_ms: int, slow_ms: int) -> Text:
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
            text.append(_SPARK_CHARS[idx], style=_latency_style(v, ok_ms, slow_ms))
    return text


def _build_stats_line(history: list[ProbeLatency]) -> Text:
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


def _format_status_latency(latency: ProbeLatency | None, ok_ms: int, slow_ms: int) -> Text:
    """Format latency for the status banner."""
    if latency is None:
        return Text("● ?", style="dim")
    ms = latency.latency_ms
    style = _latency_style(ms, ok_ms, slow_ms)
    if ms is None:
        return Text("✕ down", style=style)
    return Text(f"● {ms:.0f}ms", style=style)


def _format_status_vpn(vpn: ProbeVpn | None) -> Text:
    """Format VPN status for the status banner."""
    if vpn is None:
        return Text("VPN ?", style="dim")
    if not vpn.is_active:
        return Text("VPN off", style="dim")
    parts = ["VPN on"]
    if vpn.provider:
        parts.append(f"· {vpn.provider}")
    parts.append(f"· {vpn.tunnel_mode}")
    return Text(" ".join(parts), style="green")


def _format_status_ip(ip_probe: ProbeIp | None) -> Text:
    """Format IP for the status banner."""
    if ip_probe is None or ip_probe.ip is None:
        return Text("IP ?", style="dim")
    if ip_probe.country_code:
        return Text(f"{ip_probe.ip} ({ip_probe.country_code})")
    return Text(ip_probe.ip)


def _build_events(vpn_rows: list[ProbeVpn], ip_rows: list[ProbeIp]) -> Text:
    """Build merged events list, newest first."""
    events: list[tuple[float, str]] = []

    for v in vpn_rows:
        ts = datetime.fromtimestamp(v.created_at, tz=UTC).astimezone().strftime("%H:%M:%S")
        if v.is_active:
            parts = ["on"]
            if v.provider:
                parts.append(v.provider)
            parts.append(v.tunnel_mode)
            events.append((v.created_at, f"  {ts}  VPN  {' '.join(parts)}"))
        else:
            events.append((v.created_at, f"  {ts}  VPN  off"))

    for ip in ip_rows:
        ts = datetime.fromtimestamp(ip.created_at, tz=UTC).astimezone().strftime("%H:%M:%S")
        if ip.ip:
            cc = f" ({ip.country_code})" if ip.country_code else ""
            events.append((ip.created_at, f"  {ts}  IP   {ip.ip}{cc}"))
        else:
            events.append((ip.created_at, f"  {ts}  IP   ?"))

    events.sort(key=lambda e: e[0], reverse=True)

    if not events:
        return Text("  no events", style="dim")

    return Text("\n".join(line for _, line in events))


class TuiApp(App[None]):
    """TUI dashboard for mb-netwatch."""

    TITLE = "mb-netwatch"
    CSS = """
    Screen {
        layout: vertical;
    }
    #status-row {
        height: 1;
        padding: 0 1;
    }
    #sparkline-box {
        height: auto;
        max-height: 6;
        border: round $accent;
        border-title-color: $text;
        padding: 0 1;
    }
    #events-box {
        border: round $accent;
        border-title-color: $text;
        padding: 0 1;
        min-height: 4;
    }
    #footer-bar {
        height: 1;
        dock: bottom;
        padding: 0 1;
    }
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, db: Db, config: Config) -> None:
        """Initialize TUI with database and config references."""
        super().__init__()
        self._db = db  # Database access layer
        self._config = config  # Application configuration

    def compose(self) -> ComposeResult:
        """Build the widget tree."""
        yield Static(id="status-row")
        yield Static(id="sparkline-box")
        yield Static(id="events-box")
        yield Static(id="footer-bar")

    def on_mount(self) -> None:
        """Start periodic data refresh on mount."""
        self._refresh_data()
        self.set_interval(self._config.tui.poll_interval, self._refresh_data)

    def _refresh_data(self) -> None:
        """Poll DB and update all widgets."""
        ok_ms = self._config.tray.ok_threshold_ms
        slow_ms = self._config.tray.slow_threshold_ms

        latency = self._db.fetch_latest_probe_latency()
        vpn = self._db.fetch_latest_probe_vpn()
        ip_probe = self._db.fetch_latest_probe_ip()
        history = self._db.fetch_recent_probe_latency(self._config.tui.history_size)
        recent_vpn = self._db.fetch_recent_probe_vpn(10)
        recent_ip = self._db.fetch_recent_probe_ip(10)

        status = Text("mb-netwatch", style="bold")
        status.append("    ")
        status.append_text(_format_status_latency(latency, ok_ms, slow_ms))
        status.append("    ")
        status.append_text(_format_status_vpn(vpn))
        status.append("    ")
        status.append_text(_format_status_ip(ip_probe))
        self.query_one("#status-row", Static).update(status)

        sparkline_widget = self.query_one("#sparkline-box", Static)
        sparkline_widget.border_title = "Latency History"
        spark_text = build_sparkline(history, ok_ms, slow_ms)
        spark_text.append("\n")
        spark_text.append_text(_build_stats_line(history))
        sparkline_widget.update(spark_text)

        events_widget = self.query_one("#events-box", Static)
        events_widget.border_title = "Events"
        events_widget.update(_build_events(recent_vpn, recent_ip))

        pid_status = self._get_probed_status()
        footer_text = Text()
        footer_text.append_text(pid_status)
        footer_text.append("q quit", style="dim")
        self.query_one("#footer-bar", Static).update(footer_text)

    def _get_probed_status(self) -> Text:
        """Check if probed is running via PID file."""
        pid_path = self._config.probed_pid_path
        if not pid_path.exists():
            return Text("probed: not running    ", style="dim red")
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, 0)
            return Text(f"probed: running · pid {pid}    ", style="dim green")
        except ValueError, ProcessLookupError, PermissionError, OSError:
            return Text("probed: not running    ", style="dim red")
