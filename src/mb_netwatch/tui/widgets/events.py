"""Events widget — recent VPN and IP changes."""

from datetime import UTC, datetime

from rich.text import Text
from textual.widget import Widget

from mb_netwatch.core.db import ProbeIp, ProbeVpn


class EventsWidget(Widget):
    """Merged VPN/IP events list, newest first."""

    DEFAULT_CSS = """
    EventsWidget {
        border: round $accent;
        border-title-color: $text;
        padding: 0 1;
        min-height: 4;
    }
    """

    def __init__(self) -> None:
        """Initialize with empty state."""
        super().__init__()
        self.border_title = "Events"
        self._vpn_rows: list[ProbeVpn] = []  # Recent VPN probe results
        self._ip_rows: list[ProbeIp] = []  # Recent IP probe results

    def update_data(self, vpn_rows: list[ProbeVpn], ip_rows: list[ProbeIp]) -> None:
        """Set new event data and trigger re-render."""
        self._vpn_rows = vpn_rows
        self._ip_rows = ip_rows
        self.refresh()

    def render(self) -> Text:
        """Render merged events list, newest first."""
        events: list[tuple[float, str]] = []

        for v in self._vpn_rows:
            ts = datetime.fromtimestamp(v.created_at, tz=UTC).astimezone().strftime("%H:%M:%S")
            if v.is_active:
                parts = ["on"]
                if v.provider:
                    parts.append(v.provider)
                parts.append(v.tunnel_mode)
                events.append((v.created_at, f"  {ts}  VPN  {' '.join(parts)}"))
            else:
                events.append((v.created_at, f"  {ts}  VPN  off"))

        for ip in self._ip_rows:
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
