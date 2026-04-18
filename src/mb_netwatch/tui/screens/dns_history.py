"""DNS probe history screen — one row per resolver sample."""

from datetime import UTC, datetime
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Static

from mb_netwatch.core.core import Core

HISTORY_LIMIT = 200  # Number of most recent probe_dns cycles to display (each cycle fans out to N resolver rows)


class DnsHistoryScreen(Screen[None]):
    """Scrollable per-resolver view of recent DNS probe cycles, newest first.

    Each probe cycle is expanded into one row per resolver. This is the only view
    in the TUI that exposes non-primary resolvers over time — the dashboard
    sparkline shows only the primary.
    """

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
        yield Static(f"DNS history — last {HISTORY_LIMIT} cycles (one row per resolver)", id="title")
        yield DataTable()
        yield Static("r refresh    esc/q back", id="hint")

    def on_mount(self) -> None:
        """Configure the table and load initial data."""
        table = self.query_one(DataTable)
        table.add_columns("Time", "Role", "Resolver", "ms", "Error")
        table.cursor_type = "row"
        self._reload()

    def action_refresh(self) -> None:
        """Refetch rows from the database."""
        self._reload()

    def _reload(self) -> None:
        """Fetch latest rows and populate the table."""
        table = self.query_one(DataTable)
        table.clear()
        # fetch_recent_probe_dns returns oldest-first; reverse for newest-first display.
        cycles = list(reversed(self._core.db.fetch_recent_probe_dns(HISTORY_LIMIT)))
        for cycle in cycles:
            ts = datetime.fromtimestamp(cycle.created_at, tz=UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            if not cycle.resolvers:
                table.add_row(ts, Text("—", style="dim"), Text("no config", style="bold red"), "-", "-")
                continue
            for idx, sample in enumerate(cycle.resolvers):
                role = Text("primary", style="bold") if idx == 0 else Text(f"#{idx + 1}", style="dim")
                ms_cell = f"{sample.resolve_ms:.0f}" if sample.resolve_ms is not None else "-"
                err_cell = Text(sample.error, style="bold red") if sample.error else Text("-", style="dim")
                table.add_row(ts, role, sample.address, ms_cell, err_cell)
