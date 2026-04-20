"""Structured output for CLI and JSON modes."""

from urllib.parse import urlparse

from mm_clikit import DualModeOutput
from pydantic import BaseModel, ConfigDict
from rich.console import Group, RenderableType
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from mb_netwatch.core.diagnostics.dns import DnsDiagnosis
from mb_netwatch.core.probes.dns import DnsResolverSample
from mb_netwatch.core.service import ProbeResult


class StartStopResult(BaseModel):
    """Result of a start/stop command."""

    model_config = ConfigDict(frozen=True)

    component: str  # "probed" or "tray"
    message: str  # Human-readable status message


class RaycastInstallResult(BaseModel):
    """Result of installing Raycast script commands."""

    model_config = ConfigDict(frozen=True)

    target_dir: str  # Absolute path to the install directory
    installed: list[str]  # Names of installed script files
    refreshed: bool  # True if the directory already contained scripts (re-install)
    command: str  # Resolved command prefix baked into the scripts


# Cheat-sheet for common DNS fixes on macOS. Order = recommended escalation.
# Listed at the bottom of `diagnose dns` output for recall.
_DNS_FIX_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Flush DNS cache (try this first):",
        ("sudo dscacheutil -flushcache", "sudo killall -HUP mDNSResponder"),
    ),
    (
        "Hard restart of mDNSResponder (if flush did not help):",
        ("sudo launchctl kickstart -k system/com.apple.mDNSResponder",),
    ),
)


def _build_dns_fix_panel() -> Group:
    """Render the static cheat-sheet of useful DNS-fix commands."""
    items: list[RenderableType] = [Rule(title="Useful DNS commands", style="dim")]
    for label, commands in _DNS_FIX_COMMANDS:
        items.append(Text(label, style="bold"))
        items.extend(Text(f"  {cmd}", style="cyan") for cmd in commands)
        items.append(Text(""))
    return Group(*items)


def _build_resolver_table(title: str, samples: list[DnsResolverSample]) -> Table:
    """Render a single category of DNS samples as a Rich table."""
    table = Table(title=title, title_justify="left")
    table.add_column("Resolver")
    table.add_column("Time", justify="right")
    table.add_column("Status")
    if not samples:
        table.add_row("—", "—", "no resolvers")
        return table
    for s in samples:
        time_cell = f"{s.resolve_ms:.0f} ms" if s.resolve_ms is not None else "—"
        status_cell = "ok" if s.error is None else s.error
        table.add_row(s.address, time_cell, status_cell)
    return table


class Output(DualModeOutput):
    """Handles all CLI output in JSON or human-readable format."""

    def print_probe(self, result: ProbeResult) -> None:
        """Print one-shot probe result."""
        lines: list[str] = []

        # Latency (warm): reused keep-alive session — steady-state probe
        if result.latency_warm_ms is None:
            lines.append("Latency warm: down")
        else:
            host = urlparse(result.latency_warm_endpoint).hostname if result.latency_warm_endpoint else "?"
            lines.append(f"Latency warm: {result.latency_warm_ms:.0f}ms ({host})")

        # Latency (cold): fresh session — full TCP+TLS setup probe
        if result.latency_cold_ms is None:
            lines.append("Latency cold: down")
        else:
            host = urlparse(result.latency_cold_endpoint).hostname if result.latency_cold_endpoint else "?"
            lines.append(f"Latency cold: {result.latency_cold_ms:.0f}ms ({host})")

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

    def print_dns_diagnosis(self, diagnosis: DnsDiagnosis) -> None:
        """Print extended DNS diagnostic — three result tables plus a verdict line."""
        renderables: list[RenderableType] = [
            _build_resolver_table("System resolvers (UDP)", diagnosis.system_udp),
            _build_resolver_table("System resolvers (TCP)", diagnosis.system_tcp),
            _build_resolver_table("Public DNS (UDP)", diagnosis.public_udp),
        ]
        if diagnosis.verdict is not None:
            # Color verdict by severity: HEALTHY → green, NO_RESOLVERS / problem codes → yellow.
            color = "green" if diagnosis.verdict.code == "HEALTHY" else "yellow"
            renderables.append(Text(f"Verdict: {diagnosis.verdict.message}", style=color))
        else:
            renderables.append(Text("Verdict: mixed results — see tables above.", style="dim"))

        renderables.append(_build_dns_fix_panel())

        self.output(json_data=diagnosis.model_dump(), display_data=Group(*renderables))

    def print_raycast_installed(self, result: RaycastInstallResult) -> None:
        """Print Raycast install confirmation."""
        count = len(result.installed)
        if result.refreshed:
            display: str = f"Refreshed {count} Raycast scripts in {result.target_dir}"
        else:
            display = (
                f"Installed {count} Raycast scripts to {result.target_dir}\n"
                "\n"
                "One-time setup in Raycast:\n"
                "  Settings \u2192 Extensions \u2192 Script Commands \u2192 Add Directories\n"
                "  \u2192 select the path above"
            )
        self.output(json_data=result.model_dump(), display_data=display)
