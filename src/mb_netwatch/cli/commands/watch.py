"""Live terminal view of measurements."""

import contextlib
import time
from datetime import UTC, datetime

import typer
from mm_clikit import CoreContext

from mb_netwatch.cli.context import use_context
from mb_netwatch.cli.output import Output, WatchRow
from mb_netwatch.core.core import Core
from mb_netwatch.core.db import IpCheckRow, LatencyRow, VpnCheckRow


def _format_vpn(vpn: VpnCheckRow | None) -> str:
    """Format cached VPN status for display."""
    if vpn is None:
        return "VPN:?"
    if not vpn.is_active:
        return "VPN:off"

    parts = ["VPN:on"]
    if vpn.provider:
        parts.append(vpn.provider)
    parts.append(vpn.tunnel_mode)
    return " ".join(parts)


def _format_ip(ip_check: IpCheckRow | None) -> str:
    """Format cached IP check for display."""
    if ip_check is None:
        return "IP:?"
    if ip_check.ip is None:
        return "IP:?"
    if ip_check.country_code:
        return f"IP:{ip_check.ip}({ip_check.country_code})"
    return f"IP:{ip_check.ip}"


def _format_row(row: LatencyRow, vpn: VpnCheckRow | None, ip_check: IpCheckRow | None) -> str:
    """Format a single latency row with cached VPN and IP status for terminal display."""
    ts_str = datetime.fromtimestamp(row.ts, tz=UTC).astimezone().strftime("%H:%M:%S")
    latency_str = "down" if row.latency_ms is None else f"{row.latency_ms:4.0f}ms"
    vpn_str = _format_vpn(vpn)
    ip_str = _format_ip(ip_check)
    return f"{ts_str}  {latency_str:>6}  {vpn_str}  {ip_str}"


def _make_watch_row(row: LatencyRow, vpn: VpnCheckRow | None, ip_check: IpCheckRow | None) -> WatchRow:
    """Build a WatchRow from the latest latency, VPN, and IP data."""
    ts_str = datetime.fromtimestamp(row.ts, tz=UTC).astimezone().isoformat()
    return WatchRow(
        ts=ts_str,
        latency_ms=row.latency_ms,
        vpn_active=vpn.is_active if vpn else False,
        tunnel_mode=vpn.tunnel_mode if vpn else "unknown",
        vpn_provider=vpn.provider if vpn else None,
        ip=ip_check.ip if ip_check else None,
        country_code=ip_check.country_code if ip_check else None,
    )


def _poll_loop(app: CoreContext[Core, Output]) -> None:
    """Poll the database for new latency/VPN/IP rows and print them."""
    latency_cursor_ts = time.time()

    # Load latest VPN and IP status
    cached_vpn = app.core.db.fetch_latest_vpn_check()
    vpn_cursor_ts = cached_vpn.created_at if cached_vpn else 0.0
    cached_ip = app.core.db.fetch_latest_ip_check()
    ip_cursor_ts = cached_ip.created_at if cached_ip else 0.0

    while True:
        # Check for newer VPN data
        vpn_rows = app.core.db.fetch_vpn_checks_since(vpn_cursor_ts)
        if vpn_rows:
            cached_vpn = vpn_rows[-1]
            vpn_cursor_ts = cached_vpn.created_at

        # Check for newer IP data
        ip_rows = app.core.db.fetch_ip_checks_since(ip_cursor_ts)
        if ip_rows:
            cached_ip = ip_rows[-1]
            ip_cursor_ts = cached_ip.created_at

        # Print new latency rows with cached VPN and IP status
        rows = app.core.db.fetch_latency_checks_since(latency_cursor_ts)
        for row in rows:
            formatted = _format_row(row, cached_vpn, cached_ip)
            watch_row = _make_watch_row(row, cached_vpn, cached_ip)
            app.out.print_watch_row(watch_row, formatted)
            latency_cursor_ts = row.ts

        time.sleep(app.core.config.watch.poll_interval)


def watch(ctx: typer.Context) -> None:
    """Show live terminal view of connection measurements."""
    app = use_context(ctx)
    with contextlib.suppress(KeyboardInterrupt):
        _poll_loop(app)
