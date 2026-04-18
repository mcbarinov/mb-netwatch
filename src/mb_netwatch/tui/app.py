"""Textual TUI dashboard for mb-netwatch."""

import os
import time
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import ClassVar

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.widgets import Static

from mb_netwatch.core.core import Core
from mb_netwatch.core.db import ProbeDns, ProbeIp, ProbeLatencyCold, ProbeLatencyWarm, ProbeVpn
from mb_netwatch.tui.screens.dns_history import DnsHistoryScreen
from mb_netwatch.tui.screens.ip_history import IpHistoryScreen
from mb_netwatch.tui.screens.latency_history import LatencyHistoryScreen
from mb_netwatch.tui.screens.probe_result import ProbeResultScreen
from mb_netwatch.tui.screens.vpn_history import VpnHistoryScreen
from mb_netwatch.tui.widgets.dns import DnsWidget
from mb_netwatch.tui.widgets.events import EventsWidget
from mb_netwatch.tui.widgets.latency import LatencyWidget

try:
    _VERSION = _pkg_version("mb-netwatch")
except PackageNotFoundError:
    # Distribution metadata is missing (e.g. source tree without install). Degrade gracefully
    # rather than crash the whole TUI module on import.
    _VERSION = "?"


def _dot(glyph: str, glyph_style: str, body: str) -> Text:
    """Return a ``Text`` with a styled *glyph* followed by a neutral-styled *body*."""
    text = Text()
    text.append(glyph, style=glyph_style)
    text.append(body)
    return text


def _format_status_latency(
    label: str,
    latency: ProbeLatencyWarm | ProbeLatencyCold | None,
    ok_ms: int,
    slow_ms: int,
    *,
    stale: bool,
) -> Text:
    """Format a latency series for the status banner. Prefix with *label* (``warm``/``cold``).

    Healthy / degraded / down states color only the leading glyph and keep the text neutral.
    Stale and unknown states dim the entire item so the eye skips over untrustworthy data.
    """
    if stale:
        return Text(f"● {label} stale", style="dim")
    if latency is None:
        return Text(f"● {label} ?", style="dim")
    ms = latency.latency_ms
    if ms is None:
        return _dot("✕ ", "bold red", f"{label} down")
    if ms < ok_ms:
        color = "green"
    elif ms < slow_ms:
        color = "yellow"
    else:
        color = "red"
    return _dot("● ", color, f"{label} {ms:.0f}ms")


def _format_status_dns(dns: ProbeDns | None, *, stale: bool) -> Text:
    """Format DNS status for the status banner (primary resolver only)."""
    if stale:
        return Text("● DNS stale", style="dim")
    if dns is None:
        return Text("● DNS ?", style="dim")
    if dns.primary_address is None:
        return _dot("✕ ", "bold red", "DNS no config")
    if dns.primary_error is not None:
        return _dot("✕ ", "bold red", f"DNS {dns.primary_error}")
    if dns.primary_ms is None:
        return Text("● DNS ?", style="dim")
    return _dot("● ", "green", f"DNS {dns.primary_ms:.0f}ms")


def _format_status_vpn(vpn: ProbeVpn | None) -> Text:
    """Format VPN status for the status banner."""
    if vpn is None:
        return Text("● VPN ?", style="dim")
    if not vpn.is_active:
        return Text("● VPN off", style="dim")
    body = f"VPN {vpn.tunnel_mode or 'on'}"
    if vpn.provider:
        body += f" · {vpn.provider}"
    return _dot("● ", "green", body)


def _format_status_ip(ip_probe: ProbeIp | None) -> Text:
    """Format IP for the status banner."""
    if ip_probe is None or ip_probe.ip is None:
        return Text("● IP ?", style="dim")
    body = f"{ip_probe.ip} ({ip_probe.country_code})" if ip_probe.country_code else ip_probe.ip
    return _dot("● ", "green", body)


class TuiApp(App[None]):
    """TUI dashboard for mb-netwatch."""

    TITLE = "mb-netwatch"
    # Minimum terminal width (in columns) that switches the middle area from a single
    # stacked column to a two-column layout: sparklines on the left, events on the right.
    WIDE_BREAKPOINT = 120
    CSS = """
    Screen {
        layout: vertical;
        overflow: hidden;
    }
    #status-row {
        height: 1;
        padding: 0 1;
    }
    #main {
        layout: vertical;
        height: 1fr;
    }
    #sparks {
        layout: vertical;
        height: auto;
    }
    #main.wide {
        layout: horizontal;
    }
    #main.wide #sparks {
        width: 2fr;
        height: 1fr;
    }
    #main.wide EventsWidget {
        width: 1fr;
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
        Binding("d", "show_dns_history", "DNS"),
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
        with Container(id="main"):
            with Vertical(id="sparks"):
                yield LatencyWidget(kind="warm")
                yield LatencyWidget(kind="cold")
                yield DnsWidget()
            yield EventsWidget()
        yield Static(id="footer-bar")

    def on_mount(self) -> None:
        """Start periodic data refresh on mount."""
        self._apply_layout(self.size.width)
        self._refresh_data()
        self.set_interval(self._core.config.tui.poll_interval, self._refresh_data)

    def on_resize(self, event: events.Resize) -> None:
        """Toggle between single-column and two-column layout based on width."""
        self._apply_layout(event.size.width)

    def _apply_layout(self, width: int) -> None:
        """Add or remove the ``wide`` class on #main to switch middle-area layout."""
        main = self.query_one("#main")
        if width >= self.WIDE_BREAKPOINT:
            main.add_class("wide")
        else:
            main.remove_class("wide")

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
        dns = db.fetch_latest_probe_dns()
        vpn = db.fetch_latest_probe_vpn()
        ip_probe = db.fetch_latest_probe_ip()
        recent_vpn = db.fetch_recent_probe_vpn(10)
        recent_ip = db.fetch_recent_probe_ip(10)
        now = time.time()
        warm_stale = latency_warm is not None and (now - latency_warm.created_at) > config.warm_latency_threshold.stale_seconds
        cold_stale = latency_cold is not None and (now - latency_cold.created_at) > config.cold_latency_threshold.stale_seconds
        dns_stale = dns is not None and (now - dns.created_at) > config.dns_threshold.stale_seconds

        status = Text("mb-netwatch", style="bold")
        status.append(f" v{_VERSION}", style="dim")
        status.append("    ")
        status.append_text(_format_status_latency("warm", latency_warm, warm_ok, warm_slow, stale=warm_stale))
        status.append("    ")
        status.append_text(_format_status_latency("cold", latency_cold, cold_ok, cold_slow, stale=cold_stale))
        status.append("    ")
        status.append_text(_format_status_dns(dns, stale=dns_stale))
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

        dns_widget = self.query_one("#dns", DnsWidget)
        dns_width = dns_widget.content_width
        dns_count = min(dns_width, config.tui.sparkline_history_max) if dns_width > 0 else 60
        dns_widget.update_data(db.fetch_recent_probe_dns(dns_count))

        self.query_one(EventsWidget).update_data(recent_vpn, recent_ip)

        pid_status = self._get_probed_status()
        footer_text = Text()
        footer_text.append_text(pid_status)
        footer_text.append("w warm  c cold  d dns  v vpn  i ip  r run  q quit", style="dim")
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

    def action_show_dns_history(self) -> None:
        """Open the DNS history screen."""
        self.push_screen(DnsHistoryScreen(self._core))

    def action_show_vpn_history(self) -> None:
        """Open the VPN history screen."""
        self.push_screen(VpnHistoryScreen(self._core))

    def action_show_ip_history(self) -> None:
        """Open the IP history screen."""
        self.push_screen(IpHistoryScreen(self._core))

    def action_run_probes_now(self) -> None:
        """Open the on-demand probe result screen."""
        self.push_screen(ProbeResultScreen(self._core))
