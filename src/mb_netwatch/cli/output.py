"""Structured output for CLI and JSON modes."""

from urllib.parse import urlparse

from mm_clikit import DualModeOutput
from pydantic import BaseModel, ConfigDict

from mb_netwatch.core.service import ProbeResult


class StartStopResult(BaseModel):
    """Result of a start/stop command."""

    model_config = ConfigDict(frozen=True)

    component: str  # "probed" or "tray"
    message: str  # Human-readable status message


class Output(DualModeOutput):
    """Handles all CLI output in JSON or human-readable format."""

    def print_probe(self, result: ProbeResult) -> None:
        """Print one-shot probe result."""
        lines: list[str] = []

        # Latency
        if result.latency_ms is None:
            lines.append("Latency: down")
        else:
            host = urlparse(result.endpoint).hostname if result.endpoint else "?"
            lines.append(f"Latency: {result.latency_ms:.0f}ms ({host})")

        # VPN
        if not result.vpn_active:
            lines.append("VPN: inactive")
        else:
            parts = ["VPN: active"]
            if result.vpn_provider:
                parts.append(f"({result.vpn_provider})")
            if result.tunnel_mode is not None:
                parts.append(f"[{result.tunnel_mode} tunnel]")
            lines.append(" ".join(parts))

        # IP
        if result.ip is None:
            lines.append("IP: unknown")
        elif result.country_code:
            lines.append(f"IP: {result.ip} ({result.country_code})")
        else:
            lines.append(f"IP: {result.ip}")

        # DNS
        if not result.dns_resolvers:
            lines.append("DNS: unknown")
        else:
            dns_parts: list[str] = []
            for r in result.dns_resolvers:
                if r.error is not None:
                    dns_parts.append(f"{r.error} ({r.address})")
                elif r.resolve_ms is not None:
                    dns_parts.append(f"{r.resolve_ms:.0f}ms ({r.address})")
            lines.append("DNS: " + ", ".join(dns_parts))

        self.output(json_data=result.model_dump(), display_data="\n".join(lines))

    def print_start_stop(self, result: StartStopResult) -> None:
        """Print start/stop command result."""
        self.output(json_data=result.model_dump(), display_data=result.message)
