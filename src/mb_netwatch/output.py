"""Structured output for CLI and JSON modes."""

# ruff: noqa: T201 — this module is the output layer; print() is its sole mechanism for producing CLI output.

import json
import sys
from dataclasses import asdict, dataclass
from typing import NoReturn
from urllib.parse import urlparse

import typer


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Result of a one-shot connectivity probe."""

    latency_ms: float | None
    winner_endpoint: str | None
    vpn_active: bool
    tunnel_mode: str
    vpn_provider: str | None
    ip: str | None
    country_code: str | None


@dataclass(frozen=True, slots=True)
class WatchRow:
    """Single measurement row for the watch stream."""

    ts: str
    latency_ms: float | None
    vpn_active: bool
    tunnel_mode: str
    vpn_provider: str | None
    ip: str | None
    country_code: str | None


@dataclass(frozen=True, slots=True)
class StartStopResult:
    """Result of a start/stop command."""

    component: str
    message: str


class Output:
    """Handles all CLI output in JSON or human-readable format."""

    def __init__(self, *, json_mode: bool) -> None:
        """Initialize output handler.

        Args:
            json_mode: If True, output JSON envelopes; otherwise human-readable text.

        """
        self._json_mode = json_mode

    @property
    def json_mode(self) -> bool:
        """Whether JSON output is enabled."""
        return self._json_mode

    def _success(self, data: dict[str, object], message: str) -> None:
        """Print a success result in JSON or human-readable format."""
        if self._json_mode:
            print(json.dumps({"ok": True, "data": data}))
        else:
            print(message)

    def print_error_and_exit(self, code: str, message: str) -> NoReturn:
        """Print an error in JSON or human-readable format and exit with code 1."""
        if self._json_mode:
            print(json.dumps({"ok": False, "error": code, "message": message}))
        else:
            print(f"Error: {message}", file=sys.stderr)
        raise typer.Exit(code=1)

    def print_probe(self, result: ProbeResult) -> None:
        """Print one-shot probe result."""
        if self._json_mode:
            print(json.dumps({"ok": True, "data": asdict(result)}))
            return

        # Latency
        if result.latency_ms is None:
            print("Latency: down")
        else:
            host = urlparse(result.winner_endpoint).hostname if result.winner_endpoint else "?"
            print(f"Latency: {result.latency_ms:.0f}ms ({host})")

        # VPN
        if not result.vpn_active:
            print("VPN: inactive")
        else:
            parts = ["VPN: active"]
            if result.vpn_provider:
                parts.append(f"({result.vpn_provider})")
            parts.append(f"[{result.tunnel_mode} tunnel]")
            print(" ".join(parts))

        # IP
        if result.ip is None:
            print("IP: unknown")
        elif result.country_code:
            print(f"IP: {result.ip} ({result.country_code})")
        else:
            print(f"IP: {result.ip}")

    def print_watch_row(self, row: WatchRow, formatted_line: str) -> None:
        """Print a single watch row in JSON or human-readable format."""
        if self._json_mode:
            print(json.dumps(asdict(row)))
        else:
            print(formatted_line)

    def print_start_stop(self, result: StartStopResult) -> None:
        """Print start/stop command result."""
        self._success(asdict(result), result.message)
