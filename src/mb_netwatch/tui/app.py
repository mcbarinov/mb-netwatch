"""Textual TUI dashboard for mb-netwatch."""

import os
import time
from typing import ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from mb_netwatch.config import Config
from mb_netwatch.core.db import Db, ProbeIp, ProbeLatency, ProbeVpn
from mb_netwatch.tui.widgets.events import EventsWidget
from mb_netwatch.tui.widgets.latency import LatencyWidget, latency_style


def _format_status_latency(latency: ProbeLatency | None, ok_ms: int, slow_ms: int) -> Text:
    """Format latency for the status banner."""
    if latency is None:
        return Text("● ?", style="dim")
    ms = latency.latency_ms
    style = latency_style(ms, ok_ms, slow_ms)
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
        yield LatencyWidget()
        yield EventsWidget()
        yield Static(id="footer-bar")

    def on_mount(self) -> None:
        """Start periodic data refresh on mount."""
        self._refresh_data()
        self.set_interval(self._config.tui.poll_interval, self._refresh_data)

    def _refresh_data(self) -> None:
        """Poll DB and update all widgets."""
        ok_ms = self._config.latency_threshold.ok_ms
        slow_ms = self._config.latency_threshold.slow_ms

        latency = self._db.fetch_latest_probe_latency()
        vpn = self._db.fetch_latest_probe_vpn()
        ip_probe = self._db.fetch_latest_probe_ip()
        recent_vpn = self._db.fetch_recent_probe_vpn(10)
        recent_ip = self._db.fetch_recent_probe_ip(10)
        stale = latency is not None and (time.time() - latency.created_at) > self._config.latency_threshold.stale_seconds

        status = Text("mb-netwatch", style="bold")
        status.append("    ")
        if stale:
            status.append("● stale", style="dim")
        else:
            status.append_text(_format_status_latency(latency, ok_ms, slow_ms))
        status.append("    ")
        status.append_text(_format_status_vpn(vpn))
        status.append("    ")
        status.append_text(_format_status_ip(ip_probe))
        self.query_one("#status-row", Static).update(status)

        latency_widget = self.query_one(LatencyWidget)
        content_width = latency_widget.content_width
        fetch_count = min(content_width, self._config.tui.latency_history_max) if content_width > 0 else 60
        history = self._db.fetch_recent_probe_latency(fetch_count)
        latency_widget.update_data(history, ok_ms, slow_ms)

        self.query_one(EventsWidget).update_data(recent_vpn, recent_ip)

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
