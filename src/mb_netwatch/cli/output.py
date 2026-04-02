"""Structured output for CLI and JSON modes."""

from urllib.parse import urlparse

from mm_clikit import DualModeOutput
from pydantic import BaseModel, ConfigDict

from mb_netwatch.core import ProbeResult


class WatchRow(BaseModel):
    """Single measurement row for the watch stream."""

    model_config = ConfigDict(frozen=True)

    ts: str
    latency_ms: float | None
    vpn_active: bool
    tunnel_mode: str
    vpn_provider: str | None
    ip: str | None
    country_code: str | None


class StartStopResult(BaseModel):
    """Result of a start/stop command."""

    model_config = ConfigDict(frozen=True)

    component: str
    message: str


class Output(DualModeOutput):
    """Handles all CLI output in JSON or human-readable format."""

    def print_probe(self, result: ProbeResult) -> None:
        """Print one-shot probe result."""
        lines: list[str] = []

        # Latency
        if result.latency_ms is None:
            lines.append("Latency: down")
        else:
            host = urlparse(result.winner_endpoint).hostname if result.winner_endpoint else "?"
            lines.append(f"Latency: {result.latency_ms:.0f}ms ({host})")

        # VPN
        if not result.vpn_active:
            lines.append("VPN: inactive")
        else:
            parts = ["VPN: active"]
            if result.vpn_provider:
                parts.append(f"({result.vpn_provider})")
            parts.append(f"[{result.tunnel_mode} tunnel]")
            lines.append(" ".join(parts))

        # IP
        if result.ip is None:
            lines.append("IP: unknown")
        elif result.country_code:
            lines.append(f"IP: {result.ip} ({result.country_code})")
        else:
            lines.append(f"IP: {result.ip}")

        self.output(json_data=result.model_dump(), display_data="\n".join(lines))

    def print_watch_row(self, row: WatchRow, formatted_line: str) -> None:
        """Print a single watch row in JSON or human-readable format."""
        self.output(json_data=row.model_dump(), display_data=formatted_line)

    def print_start_stop(self, result: StartStopResult) -> None:
        """Print start/stop command result."""
        self.output(json_data=result.model_dump(), display_data=result.message)
