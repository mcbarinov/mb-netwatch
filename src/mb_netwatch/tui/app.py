"""Textual TUI dashboard for mb-netwatch."""

import os
import time
from typing import ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from mb_netwatch.core.core import Core
from mb_netwatch.core.db import ProbeIp, ProbeLatencyCold, ProbeLatencyWarm, ProbeVpn
from mb_netwatch.tui.screens.ip_history import IpHistoryScreen
from mb_netwatch.tui.screens.latency_history import LatencyHistoryScreen
from mb_netwatch.tui.screens.probe_result import ProbeResultScreen
from mb_netwatch.tui.screens.vpn_history import VpnHistoryScreen
from mb_netwatch.tui.widgets.events import EventsWidget
from mb_netwatch.tui.widgets.latency import LatencyWidget, latency_style


def _format_status_latency(
    label: str,
    latency: ProbeLatencyWarm | ProbeLatencyCold | None,
    ok_ms: int,
    slow_ms: int,
    *,
    stale: bool,
) -> Text:
    """Format a latency series for the status banner. Prefix with *label* (``warm``/``cold``)."""
    if stale:
        return Text(f"● {label} stale", style="dim")
    if latency is None:
        return Text(f"● {label} ?", style="dim")
    ms = latency.latency_ms
    style = latency_style(ms, ok_ms, slow_ms)
    if ms is None:
        return Text(f"✕ {label} down", style=style)
    return Text(f"● {label} {ms:.0f}ms", style=style)


def _format_status_vpn(vpn: ProbeVpn | None) -> Text:
    """Format VPN status for the status banner."""
    if vpn is None:
        return Text("VPN ?", style="dim")
    if not vpn.is_active:
        return Text("VPN off", style="dim")
    label = f"VPN {vpn.tunnel_mode or 'on'}"
    if vpn.provider:
        label += f" · {vpn.provider}"
    return Text(label, style="green")


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
        overflow: hidden;
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
        Binding("w", "show_warm_history", "Warm"),
        Binding("c", "show_cold_history", "Cold"),
        Binding("v", "show_vpn_history", "VPN"),
        Binding("i", "show_ip_history", "IP"),
        Binding("r", "run_probes_now", "Run now"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, core: Core) -> None:
        """Initialize TUI with the application core."""
        super().__init__()
        self._core = core  # Shared application services (db, config)

    def compose(self) -> ComposeResult:
        """Build the widget tree."""
        yield Static(id="status-row")
        yield LatencyWidget(kind="warm")
        yield LatencyWidget(kind="cold")
        yield EventsWidget()
        yield Static(id="footer-bar")

    def on_mount(self) -> None:
        """Start periodic data refresh on mount."""
        self._refresh_data()
        self.set_interval(self._core.config.tui.poll_interval, self._refresh_data)

    def _refresh_data(self) -> None:
        """Poll DB and update all widgets."""
        config = self._core.config
        db = self._core.db
        warm_ok = config.warm_latency_threshold.ok_ms
        warm_slow = config.warm_latency_threshold.slow_ms
        cold_ok = config.cold_latency_threshold.ok_ms
        cold_slow = config.cold_latency_threshold.slow_ms

        latency_warm = db.fetch_latest_probe_latency_warm()
        latency_cold = db.fetch_latest_probe_latency_cold()
        vpn = db.fetch_latest_probe_vpn()
        ip_probe = db.fetch_latest_probe_ip()
        recent_vpn = db.fetch_recent_probe_vpn(10)
        recent_ip = db.fetch_recent_probe_ip(10)
        now = time.time()
        warm_stale = latency_warm is not None and (now - latency_warm.created_at) > config.warm_latency_threshold.stale_seconds
        cold_stale = latency_cold is not None and (now - latency_cold.created_at) > config.cold_latency_threshold.stale_seconds

        status = Text("mb-netwatch", style="bold")
        status.append("    ")
        status.append_text(_format_status_latency("warm", latency_warm, warm_ok, warm_slow, stale=warm_stale))
        status.append("    ")
        status.append_text(_format_status_latency("cold", latency_cold, cold_ok, cold_slow, stale=cold_stale))
        status.append("    ")
        status.append_text(_format_status_vpn(vpn))
        status.append("    ")
        status.append_text(_format_status_ip(ip_probe))
        self.query_one("#status-row", Static).update(status)

        warm_widget = self.query_one("#latency-warm", LatencyWidget)
        warm_width = warm_widget.content_width
        warm_count = min(warm_width, config.tui.sparkline_history_max) if warm_width > 0 else 60
        warm_widget.update_data(db.fetch_recent_probe_latency_warm(warm_count), warm_ok, warm_slow)

        cold_widget = self.query_one("#latency-cold", LatencyWidget)
        cold_width = cold_widget.content_width
        cold_count = min(cold_width, config.tui.sparkline_history_max) if cold_width > 0 else 60
        cold_widget.update_data(db.fetch_recent_probe_latency_cold(cold_count), cold_ok, cold_slow)

        self.query_one(EventsWidget).update_data(recent_vpn, recent_ip)

        pid_status = self._get_probed_status()
        footer_text = Text()
        footer_text.append_text(pid_status)
        footer_text.append("w warm  c cold  v vpn  i ip  r run  q quit", style="dim")
        self.query_one("#footer-bar", Static).update(footer_text)

    def _get_probed_status(self) -> Text:
        """Check if probed is running via PID file."""
        pid_path = self._core.config.probed_pid_path
        if not pid_path.exists():
            return Text("probed: not running    ", style="dim red")
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, 0)
            return Text(f"probed: running · pid {pid}    ", style="dim green")
        except ValueError, ProcessLookupError, PermissionError, OSError:
            return Text("probed: not running    ", style="dim red")

    def action_show_warm_history(self) -> None:
        """Open the warm-latency history screen."""
        self.push_screen(LatencyHistoryScreen(self._core, kind="warm"))

    def action_show_cold_history(self) -> None:
        """Open the cold-latency history screen."""
        self.push_screen(LatencyHistoryScreen(self._core, kind="cold"))

    def action_show_vpn_history(self) -> None:
        """Open the VPN history screen."""
        self.push_screen(VpnHistoryScreen(self._core))

    def action_show_ip_history(self) -> None:
        """Open the IP history screen."""
        self.push_screen(IpHistoryScreen(self._core))

    def action_run_probes_now(self) -> None:
        """Open the on-demand probe result screen."""
        self.push_screen(ProbeResultScreen(self._core))
