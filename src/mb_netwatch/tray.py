"""Menu bar UI for network monitoring status."""

import logging
import time

from mm_clikit import write_pid_file
from mm_pymac import MenuItem, MenuSeparator, TrayApp

from mb_netwatch.core.core import Core
from mb_netwatch.core.db import ProbeDns, ProbeIp, ProbeLatencyCold, ProbeLatencyWarm, ProbeVpn

log = logging.getLogger(__name__)


class NetwatchTray:
    """Menu bar tray that displays network monitoring status.

    Args:
        core: Core application object for reading check data and configuration.

    """

    def __init__(self, core: Core) -> None:
        """Initialize tray with core application object.

        Args:
            core: Core application object for reading check data and configuration.

        """
        self._core = core
        self._tray = TrayApp(title="...")

        # Info items (non-interactive)
        self._latency_warm_item = MenuItem("Latency warm: ...", enabled=False)
        self._latency_cold_item = MenuItem("Latency cold: ...", enabled=False)
        self._dns_item = MenuItem("DNS: ...", enabled=False)
        self._vpn_item = MenuItem("VPN: ...", enabled=False)
        self._ip_item = MenuItem("IP: ...", enabled=False)

        quit_item = MenuItem("Quit", callback=lambda _: self._tray.quit())
        self._tray.set_menu(
            [
                self._latency_warm_item,
                self._latency_cold_item,
                self._dns_item,
                self._vpn_item,
                self._ip_item,
                MenuSeparator(),
                quit_item,
            ]
        )

    def run(self) -> None:
        """Write PID file, start the polling timer and enter the event loop."""
        write_pid_file(self._core.config.tray_pid_path)
        try:
            self._tray.start_timer(self._core.config.tray.poll_interval, self._refresh)
            self._tray.run()
        finally:
            self._core.config.tray_pid_path.unlink(missing_ok=True)
            log.info("tray stopped.")

    def _refresh(self) -> None:
        """Poll DB and update menu bar title and detail items.

        Title is driven by the warm probe only (primary status signal).
        The cold probe shows as an extra dropdown line (diagnostic, not status).
        """
        latency_warm = self._core.db.fetch_latest_probe_latency_warm()
        latency_cold = self._core.db.fetch_latest_probe_latency_cold()
        dns = self._core.db.fetch_latest_probe_dns()
        ip = self._core.db.fetch_latest_probe_ip()
        vpn = self._core.db.fetch_latest_probe_vpn()
        warm_stale = self._is_warm_stale(latency_warm)
        cold_stale = self._is_cold_stale(latency_cold)
        dns_stale = self._is_dns_stale(dns)

        self._tray.title = self._format_title(latency_warm, ip, stale=warm_stale)
        self._latency_warm_item.title = self._format_latency_warm(latency_warm, stale=warm_stale)
        self._latency_cold_item.title = self._format_latency_cold(latency_cold, stale=cold_stale)
        self._dns_item.title = self._format_dns(dns, stale=dns_stale)
        self._vpn_item.title = self._format_vpn(vpn, stale=warm_stale)
        self._ip_item.title = self._format_ip(ip, stale=warm_stale)

    def _format_title(self, latency: ProbeLatencyWarm | None, ip: ProbeIp | None, *, stale: bool) -> str:
        """Build a fixed-width (3-char) menu bar title: country code + symbol (warm-driven)."""
        if latency is None:
            symbol = "\u00b7"
        elif stale:
            symbol = "\u2013"
        else:
            symbol = self._warm_latency_band(latency.latency_ms)
        country = ip.country_code if ip and ip.country_code and not stale and latency is not None else "  "
        return f"{country}{symbol}"

    def _format_latency_warm(self, latency: ProbeLatencyWarm | None, *, stale: bool) -> str:
        """Build the warm-latency string for the dropdown menu item."""
        if stale:
            return "Latency warm: stale"
        if latency is None or latency.latency_ms is None:
            return "Latency warm: DOWN"
        return f"Latency warm: {latency.latency_ms:.0f}ms"

    def _format_latency_cold(self, latency: ProbeLatencyCold | None, *, stale: bool) -> str:
        """Build the cold-latency string for the dropdown menu item."""
        if stale:
            return "Latency cold: stale"
        if latency is None or latency.latency_ms is None:
            return "Latency cold: DOWN"
        return f"Latency cold: {latency.latency_ms:.0f}ms"

    def _format_vpn(self, vpn: ProbeVpn | None, *, stale: bool) -> str:
        """Build the VPN status string for the dropdown menu item."""
        if stale:
            return "VPN: stale"
        if vpn is None:
            return "VPN: ..."
        if not vpn.is_active:
            return "VPN: off"
        # Active — show tunnel mode (if known) and optional provider
        label = f"VPN: {vpn.tunnel_mode} tunnel" if vpn.tunnel_mode is not None else "VPN: active"
        if vpn.provider:
            label += f" ({vpn.provider})"
        return label

    def _format_dns(self, dns: ProbeDns | None, *, stale: bool) -> str:
        """Build the DNS status string for the dropdown menu item (primary resolver only)."""
        if dns is None:
            return "DNS: ..."
        if stale:
            return "DNS: stale"
        if not dns.resolvers:
            # Empty resolver list is its own diagnostic: no DNS configured, broken configd, or
            # VPN tearing down. Distinct from "primary errored".
            return "DNS: no config"
        primary = dns.resolvers[0]
        if primary.error is not None:
            return f"DNS: {primary.error} ({primary.address})"
        if primary.resolve_ms is None:
            return f"DNS: ? ({primary.address})"
        return f"DNS: {primary.resolve_ms:.0f}ms ({primary.address})"

    def _format_ip(self, ip: ProbeIp | None, *, stale: bool) -> str:
        """Build the public IP string for the dropdown menu item."""
        if stale:
            return "IP: stale"
        if ip is None:
            return "IP: ..."
        if ip.ip is None:
            return "IP: --"
        if ip.country_code:
            return f"IP: {ip.ip} ({ip.country_code})"
        return f"IP: {ip.ip}"

    def _warm_latency_band(self, latency_ms: float | None) -> str:
        """Classify warm latency into a status band label for the menu bar title."""
        if latency_ms is None:
            return "\u2715"
        if latency_ms < self._core.config.warm_latency_threshold.ok_ms:
            return "\u25cf"
        if latency_ms < self._core.config.warm_latency_threshold.slow_ms:
            return "\u25d0"
        return "\u25cb"

    def _is_warm_stale(self, latency: ProbeLatencyWarm | None) -> bool:
        """Check if the latest warm-latency row is too old to be trusted."""
        if latency is None:
            return False  # no data at all is handled separately (shows "...")
        return (time.time() - latency.created_at) > self._core.config.warm_latency_threshold.stale_seconds

    def _is_cold_stale(self, latency: ProbeLatencyCold | None) -> bool:
        """Check if the latest cold-latency row is too old to be trusted."""
        if latency is None:
            return False
        return (time.time() - latency.created_at) > self._core.config.cold_latency_threshold.stale_seconds

    def _is_dns_stale(self, dns: ProbeDns | None) -> bool:
        """Check if the latest DNS row is too old to be trusted."""
        if dns is None:
            return False
        return (time.time() - dns.created_at) > self._core.config.dns_threshold.stale_seconds
