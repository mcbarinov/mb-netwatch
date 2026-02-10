"""Continuous background measurement process (probed)."""

import asyncio
import contextlib
import logging
import signal
from datetime import UTC, datetime
from typing import Annotated

import aiohttp
import typer

from mb_netwatch.app_context import AppContext, use_context
from mb_netwatch.logger import setup_logging
from mb_netwatch.probes.ip import IpResult, check_ip
from mb_netwatch.probes.latency import check_latency
from mb_netwatch.probes.vpn import check_vpn
from mb_netwatch.process import is_alive, write_pid_file

log = logging.getLogger(__name__)

app = typer.Typer()


async def _wait_shutdown(shutdown: asyncio.Event, seconds: float) -> None:
    """Wait for the shutdown signal or timeout, whichever comes first."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(shutdown.wait(), timeout=seconds)


async def _latency_loop(app: AppContext, shutdown: asyncio.Event) -> None:
    """Measure latency and record to DB. Recreates session on failure."""
    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=app.cfg.probed.latency_timeout))
    try:
        while not shutdown.is_set():
            result = await check_latency(session)
            ts = datetime.now(tz=UTC)
            log.debug("latency=%s ms, endpoint=%s", result.latency_ms, result.winner_endpoint)
            app.db.insert_latency_check(ts, result.latency_ms, result.winner_endpoint)

            # Self-healing: recreate session on failure to drop stale connections
            if result.latency_ms is None:
                log.debug("Latency check failed, recreating HTTP session.")
                await session.close()
                session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=app.cfg.probed.latency_timeout))

            await _wait_shutdown(shutdown, app.cfg.probed.latency_interval)
    finally:
        await session.close()


async def _vpn_loop(app: AppContext, shutdown: asyncio.Event) -> None:
    """Check VPN status and record to DB."""
    while not shutdown.is_set():
        status = await asyncio.to_thread(check_vpn)
        ts = datetime.now(tz=UTC)
        log.debug("vpn=%s, mode=%s, provider=%s", status.is_active, status.tunnel_mode, status.provider)
        app.db.insert_vpn_check(ts, status.is_active, status.tunnel_mode, status.provider)

        await _wait_shutdown(shutdown, app.cfg.probed.vpn_interval)


async def _ip_loop(app: AppContext, shutdown: asyncio.Event) -> None:
    """Detect public IP and country, record to DB."""
    # Seed from DB so we skip country lookup on restart if IP is unchanged
    last = app.db.fetch_latest_ip_check()
    previous = IpResult(ip=last.ip, country_code=last.country_code) if last else None

    while not shutdown.is_set():
        result = await check_ip(previous=previous, http_timeout=app.cfg.probed.ip_timeout)
        ts = datetime.now(tz=UTC)
        log.debug("ip=%s, country=%s", result.ip, result.country_code)
        app.db.insert_ip_check(ts, result.ip, result.country_code)
        previous = result

        await _wait_shutdown(shutdown, app.cfg.probed.ip_interval)


async def _purge_loop(app: AppContext, shutdown: asyncio.Event) -> None:
    """Purge old data periodically."""
    while not shutdown.is_set():
        await _wait_shutdown(shutdown, app.cfg.probed.purge_interval)
        if not shutdown.is_set():
            lat_deleted = app.db.purge_old_latency_checks(app.cfg.probed.retention_days)
            vpn_deleted = app.db.purge_old_vpn_checks(app.cfg.probed.retention_days)
            ip_deleted = app.db.purge_old_ip_checks(app.cfg.probed.retention_days)
            log.info("Purged %d old latency checks, %d old VPN checks, %d old IP checks.", lat_deleted, vpn_deleted, ip_deleted)


async def _run(app: AppContext) -> None:
    """Launch latency, VPN, and purge loops; shut down cleanly on signal."""
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown.set)

    app.db.purge_old_latency_checks(app.cfg.probed.retention_days)
    app.db.purge_old_vpn_checks(app.cfg.probed.retention_days)
    app.db.purge_old_ip_checks(app.cfg.probed.retention_days)

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_latency_loop(app, shutdown))
            tg.create_task(_vpn_loop(app, shutdown))
            tg.create_task(_ip_loop(app, shutdown))
            tg.create_task(_purge_loop(app, shutdown))
    finally:
        log.info("probed stopped.")


@app.command()
def probed(ctx: typer.Context, *, debug: Annotated[bool, typer.Option(help="Enable debug logging.")] = False) -> None:
    """Run continuous background measurements every 2 seconds."""
    app = use_context(ctx)
    if is_alive(app.cfg.probed_pid_path):
        typer.echo("probed: already running")
        raise typer.Exit(1)

    setup_logging(debug=debug, log_file=app.cfg.probed_log_path)
    log.info("probed starting.")
    write_pid_file(app.cfg.probed_pid_path)
    try:
        asyncio.run(_run(app))
    finally:
        app.cfg.probed_pid_path.unlink(missing_ok=True)
