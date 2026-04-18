"""Latency probe history screen (one kind per screen — opened by caller)."""

from datetime import UTC, datetime
from typing import ClassVar, Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Static

from mb_netwatch.core.core import Core
from mb_netwatch.core.db import ProbeLatencyCold, ProbeLatencyWarm
from mb_netwatch.tui.widgets.latency import latency_style

HISTORY_LIMIT = 200  # Number of most recent latency rows to display


class LatencyHistoryScreen(Screen[None]):
    """Scrollable table of recent latency probes, newest first. One kind per screen instance."""

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

    def __init__(self, core: Core, kind: Literal["warm", "cold"]) -> None:
        """Initialize with the application core and the probe kind this screen shows."""
        super().__init__()
        self._core = core  # Shared application services (db, config)
        self._kind: Literal["warm", "cold"] = kind  # Which probe series this screen shows

    def compose(self) -> ComposeResult:
        """Build the screen layout."""
        yield Static(f"Latency history ({self._kind}) — last {HISTORY_LIMIT} probes", id="title")
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
        """Fetch latest rows for this screen's kind and populate the table."""
        table = self.query_one(DataTable)
        table.clear()
        if self._kind == "warm":
            ok_ms = self._core.config.warm_latency_threshold.ok_ms
            slow_ms = self._core.config.warm_latency_threshold.slow_ms
            warm_rows: list[ProbeLatencyWarm] = self._core.db.fetch_recent_probe_latency_warm(HISTORY_LIMIT)
            # fetch_recent_* returns oldest-first; iterate in reverse for newest-first display
            for w_row in reversed(warm_rows):
                self._add_row(table, w_row.created_at, w_row.latency_ms, w_row.endpoint, ok_ms, slow_ms)
        else:
            ok_ms = self._core.config.cold_latency_threshold.ok_ms
            slow_ms = self._core.config.cold_latency_threshold.slow_ms
            cold_rows: list[ProbeLatencyCold] = self._core.db.fetch_recent_probe_latency_cold(HISTORY_LIMIT)
            for c_row in reversed(cold_rows):
                self._add_row(table, c_row.created_at, c_row.latency_ms, c_row.endpoint, ok_ms, slow_ms)

    @staticmethod
    def _add_row(
        table: DataTable[Text | str],
        created_at: float,
        latency_ms: float | None,
        endpoint: str | None,
        ok_ms: int,
        slow_ms: int,
    ) -> None:
        """Render one row into the table."""
        ts = datetime.fromtimestamp(created_at, tz=UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        if latency_ms is None:
            latency_cell: Text = Text("down", style="bold red")
        else:
            latency_cell = Text(f"{latency_ms:.0f} ms", style=latency_style(latency_ms, ok_ms, slow_ms))
        table.add_row(ts, latency_cell, endpoint or "-")
