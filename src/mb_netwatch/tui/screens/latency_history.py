"""Latency probe history screen."""

from datetime import UTC, datetime
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Static

from mb_netwatch.core.core import Core
from mb_netwatch.tui.widgets.latency import latency_style

HISTORY_LIMIT = 200  # Number of most recent probe_latency rows to display


class LatencyHistoryScreen(Screen[None]):
    """Scrollable table of recent latency probes, newest first."""

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
        yield Static(f"Latency history — last {HISTORY_LIMIT} probes", id="title")
        yield DataTable()
        yield Static("r refresh    esc/q back", id="hint")

    def on_mount(self) -> None:
        """Configure the table and load initial data."""
        table = self.query_one(DataTable)
        table.add_columns("Time", "Latency", "Endpoint")
        table.cursor_type = "row"
        self._reload()

    def action_refresh(self) -> None:
        """Refetch rows from the database."""
        self._reload()

    def _reload(self) -> None:
        """Fetch latest rows and populate the table."""
        table = self.query_one(DataTable)
        table.clear()
        ok_ms = self._core.config.latency_threshold.ok_ms
        slow_ms = self._core.config.latency_threshold.slow_ms
        # fetch_recent_probe_latency returns oldest-first; iterate in reverse for newest-first display
        for row in reversed(self._core.db.fetch_recent_probe_latency(HISTORY_LIMIT)):
            ts = datetime.fromtimestamp(row.created_at, tz=UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            if row.latency_ms is None:
                latency_cell = Text("down", style="bold red")
            else:
                latency_cell = Text(f"{row.latency_ms:.0f} ms", style=latency_style(row.latency_ms, ok_ms, slow_ms))
            endpoint = row.endpoint or "-"
            table.add_row(ts, latency_cell, endpoint)
