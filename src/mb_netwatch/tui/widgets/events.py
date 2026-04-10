"""Events widget — recent VPN and IP changes."""

from datetime import UTC, datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from mb_netwatch.core.db import ProbeIp, ProbeVpn


class EventsWidget(VerticalScroll):
    """Merged VPN/IP events list, newest first. Scrolls internally when overflowing."""

    DEFAULT_CSS = """
    EventsWidget {
        border: round $accent;
        border-title-color: $text;
        padding: 0 1;
        height: 1fr;
    }
    """

    def __init__(self) -> None:
        """Initialize with empty state."""
        super().__init__()
        self.border_title = "Events"
        self._vpn_rows: list[ProbeVpn] = []  # Recent VPN probe results
        self._ip_rows: list[ProbeIp] = []  # Recent IP probe results

    def compose(self) -> ComposeResult:
        """Create the inner static that holds rendered events."""
        yield Static(id="events-body")

    def update_data(self, vpn_rows: list[ProbeVpn], ip_rows: list[ProbeIp]) -> None:
        """Set new event data and update the inner static."""
        self._vpn_rows = vpn_rows
        self._ip_rows = ip_rows
        self.query_one("#events-body", Static).update(self._build_text())

    def _build_text(self) -> Text:
        """Build merged events list text, newest first."""
        events: list[tuple[float, str]] = []

        for v in self._vpn_rows:
            ts = datetime.fromtimestamp(v.created_at, tz=UTC).astimezone().strftime("%H:%M:%S")
            if not v.is_active:
                label = "off"
            else:
                label = v.tunnel_mode or "on"
                if v.provider:
                    label += f" {v.provider}"
            events.append((v.created_at, f"{ts}  VPN  {label}"))

        for ip in self._ip_rows:
            ts = datetime.fromtimestamp(ip.created_at, tz=UTC).astimezone().strftime("%H:%M:%S")
            if ip.ip:
                cc = f" ({ip.country_code})" if ip.country_code else ""
                events.append((ip.created_at, f"{ts}  IP   {ip.ip}{cc}"))
            else:
                events.append((ip.created_at, f"{ts}  IP   ?"))

        events.sort(key=lambda e: e[0], reverse=True)

        if not events:
            return Text("no events", style="dim")

        return Text("\n".join(line for _, line in events))
