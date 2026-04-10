"""On-demand probe result screen."""

from typing import ClassVar
from urllib.parse import urlparse

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Static

from mb_netwatch.core.core import Core
from mb_netwatch.core.service import ProbeResult
from mb_netwatch.tui.widgets.latency import latency_style


def _format_latency_line(result: ProbeResult, ok_ms: int, slow_ms: int) -> Text:
    """Format the latency line from a live ProbeResult."""
    text = Text("Latency:  ", style="bold")
    if result.latency_ms is None:
        text.append("down", style="bold red")
        return text
    host = urlparse(result.endpoint).hostname if result.endpoint else "?"
    text.append(f"{result.latency_ms:.0f} ms", style=latency_style(result.latency_ms, ok_ms, slow_ms))
    text.append(f"  ({host})", style="dim")
    return text


def _format_vpn_line(result: ProbeResult) -> Text:
    """Format the VPN line from a live ProbeResult."""
    text = Text("VPN:      ", style="bold")
    if not result.vpn_active:
        text.append("off", style="dim")
        return text
    label = result.tunnel_mode or "on"
    text.append(label, style="green")
    if result.vpn_provider:
        text.append(f"  · {result.vpn_provider}", style="green")
    return text


def _format_ip_line(result: ProbeResult) -> Text:
    """Format the IP line from a live ProbeResult."""
    text = Text("IP:       ", style="bold")
    if result.ip is None:
        text.append("unknown", style="dim")
        return text
    text.append(result.ip)
    if result.country_code:
        text.append(f"  ({result.country_code})", style="dim")
    return text


class ProbeResultScreen(Screen[None]):
    """Run all probes on demand and display the live result."""

    CSS = """
    #probe-title { height: 1; padding: 0 1; background: $accent; color: $text; text-style: bold; }
    #probe-body { padding: 1 2; height: 1fr; }
    #probe-hint { dock: bottom; height: 1; padding: 0 1; color: $text-muted; }
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("escape", "dismiss", "Back"),
        Binding("q", "dismiss", "Back"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, core: Core) -> None:
        """Initialize with the application core."""
        super().__init__()
        self._core = core  # Shared application services (db, config)

    def compose(self) -> ComposeResult:
        """Build the screen layout."""
        yield Static("Run all probes", id="probe-title")
        yield Static(id="probe-body")
        yield Static("r refresh    esc/q back", id="probe-hint")

    def on_mount(self) -> None:
        """Render loading state and kick off the first probe run."""
        self._render_loading()
        self.run_worker(self._run(), exclusive=True)

    def action_refresh(self) -> None:
        """Re-run all probes."""
        self._render_loading()
        self.run_worker(self._run(), exclusive=True)

    async def _run(self) -> None:
        """Run all probes via the service and render the result."""
        # Safety net: a broken probe must never crash the TUI. run_probe() normally
        # returns sentinel None fields on failure, so reaching except means something structural.
        try:
            result = await self._core.service.run_probe()
        except Exception as e:
            self._render_error(str(e))
            return
        self._render_result(result)

    def _render_loading(self) -> None:
        """Show the 'running…' placeholder for all three lines."""
        text = Text()
        text.append("Latency:  running…\n", style="dim")
        text.append("VPN:      running…\n", style="dim")
        text.append("IP:       running…", style="dim")
        self.query_one("#probe-body", Static).update(text)

    def _render_result(self, result: ProbeResult) -> None:
        """Render the finished ProbeResult."""
        ok_ms = self._core.config.latency_threshold.ok_ms
        slow_ms = self._core.config.latency_threshold.slow_ms
        text = Text()
        text.append_text(_format_latency_line(result, ok_ms, slow_ms))
        text.append("\n")
        text.append_text(_format_vpn_line(result))
        text.append("\n")
        text.append_text(_format_ip_line(result))
        self.query_one("#probe-body", Static).update(text)

    def _render_error(self, message: str) -> None:
        """Render an error message if the probe raised unexpectedly."""
        text = Text("Probe failed: ", style="bold red")
        text.append(message, style="red")
        self.query_one("#probe-body", Static).update(text)
