"""Menu bar UI process."""

import time

import typer
from mm_clikit import is_process_running, setup_logging, write_pid_file
from mm_pymac import MenuItem, MenuSeparator, TrayApp

from mb_netwatch.cli.context import use_context
from mb_netwatch.config import Config
from mb_netwatch.db import Db, IpCheckRow, LatencyRow, VpnCheckRow


class _NetwatchTray:
    """Menu bar tray that displays network monitoring status.

    Args:
        db: Database access object for reading check data.
        cfg: Application configuration.

    """

    def __init__(self, db: Db, cfg: Config) -> None:
        self._db = db
        self._cfg = cfg
        self._tray = TrayApp(title="...")

        # Info items (non-interactive)
        self._latency_item = MenuItem("Latency: ...", enabled=False)
        self._vpn_item = MenuItem("VPN: ...", enabled=False)
        self._ip_item = MenuItem("IP: ...", enabled=False)

        quit_item = MenuItem("Quit", callback=lambda _: self._tray.quit())
        self._tray.set_menu([self._latency_item, self._vpn_item, self._ip_item, MenuSeparator(), quit_item])

    def run(self) -> None:
        """Start the polling timer and enter the event loop."""
        self._tray.start_timer(self._cfg.tray.poll_interval, self._refresh)
        self._tray.run()

    def _refresh(self) -> None:
        """Poll DB and update menu bar title and detail items."""
        latency = self._db.fetch_latest_latency_check()
        ip = self._db.fetch_latest_ip_check()
        vpn = self._db.fetch_latest_vpn_check()
        stale = self._is_stale(latency)

        self._tray.title = self._format_title(latency, ip, stale=stale)
        self._latency_item.title = self._format_latency(latency, stale=stale)
        self._vpn_item.title = self._format_vpn(vpn, stale=stale)
        self._ip_item.title = self._format_ip(ip, stale=stale)

    def _format_title(self, latency: LatencyRow | None, ip: IpCheckRow | None, *, stale: bool) -> str:
        """Build a fixed-width (3-char) menu bar title: country code + symbol."""
        if latency is None:
            symbol = "\u00b7"
        elif stale:
            symbol = "\u2013"
        else:
            symbol = self._latency_band(latency.latency_ms)
        country = ip.country_code if ip and not stale and latency is not None else "  "
        return f"{country}{symbol}"

    def _format_latency(self, latency: LatencyRow | None, *, stale: bool) -> str:
        """Build the exact latency string for the dropdown menu item."""
        if stale:
            return "Latency: stale"
        if latency is None or latency.latency_ms is None:
            return "Latency: DOWN"
        return f"Latency: {latency.latency_ms:.0f}ms"

    def _format_vpn(self, vpn: VpnCheckRow | None, *, stale: bool) -> str:
        """Build the VPN status string for the dropdown menu item."""
        if stale:
            return "VPN: stale"
        if vpn is None:
            return "VPN: ..."
        if not vpn.is_active:
            return "VPN: off"
        # Active — show tunnel mode and optional provider
        label = f"VPN: {vpn.tunnel_mode} tunnel"
        if vpn.provider:
            label += f" ({vpn.provider})"
        return label

    def _format_ip(self, ip: IpCheckRow | None, *, stale: bool) -> str:
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

    def _latency_band(self, latency_ms: float | None) -> str:
        """Classify latency into a status band label."""
        if latency_ms is None:
            return "✕"
        if latency_ms < self._cfg.tray.ok_threshold_ms:
            return "●"
        if latency_ms < self._cfg.tray.slow_threshold_ms:
            return "◐"
        return "○"

    def _is_stale(self, latency: LatencyRow | None) -> bool:
        """Check if the latest latency row is too old to be trusted."""
        if latency is None:
            return False  # no data at all is handled separately (shows "...")
        return (time.time() - latency.ts) > self._cfg.tray.stale_threshold


def tray(ctx: typer.Context) -> None:
    """Run menu bar UI process that displays current status."""
    app = use_context(ctx)
    if is_process_running(app.cfg.tray_pid_path, remove_stale=True, skip_self=True):
        typer.echo("tray: already running")
        raise typer.Exit(1)

    setup_logging("mb_netwatch", app.cfg.tray_log_path)

    write_pid_file(app.cfg.tray_pid_path)
    try:
        _NetwatchTray(app.svc, app.cfg).run()
    finally:
        app.cfg.tray_pid_path.unlink(missing_ok=True)
