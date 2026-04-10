"""VPN probe history screen."""

from datetime import UTC, datetime
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Static

from mb_netwatch.core.core import Core

HISTORY_LIMIT = 200  # Number of most recent probe_vpn rows to display


class VpnHistoryScreen(Screen[None]):
    """Scrollable table of recent VPN state changes, newest first."""

    CSS = """
    #title { height: 1; padding: 0 1; background: $accent; color: $text; text-style: bold; }
    #hint { dock: bottom; height: 1; padding: 0 1; color: $text-muted; }
    DataTable { height: 1fr; }
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
        yield Static(f"VPN history — last {HISTORY_LIMIT} state changes", id="title")
        yield DataTable()
        yield Static("r refresh    esc/q back", id="hint")

    def on_mount(self) -> None:
        """Configure the table and load initial data."""
        table = self.query_one(DataTable)
        table.add_columns("Time", "State", "Mode", "Provider", "Last seen")
        table.cursor_type = "row"
        self._reload()

    def action_refresh(self) -> None:
        """Refetch rows from the database."""
        self._reload()

    def _reload(self) -> None:
        """Fetch latest rows and populate the table."""
        table = self.query_one(DataTable)
        table.clear()
        for row in self._core.db.fetch_recent_probe_vpn(HISTORY_LIMIT):
            ts = datetime.fromtimestamp(row.created_at, tz=UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            last_seen = datetime.fromtimestamp(row.updated_at, tz=UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            state = Text("on", style="green") if row.is_active else Text("off", style="dim")
            table.add_row(ts, state, row.tunnel_mode or "-", row.provider or "-", last_seen)
