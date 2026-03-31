"""Continuous background measurement process (probed)."""

import asyncio
import contextlib
import logging
import signal
from datetime import UTC, datetime

import aiohttp
import typer
from mm_clikit import AppContext, is_process_running, setup_logging, write_pid_file

from mb_netwatch.cli.context import use_context
from mb_netwatch.cli.output import Output
from mb_netwatch.config import Config
from mb_netwatch.db import Db
from mb_netwatch.probes.ip import IpResult, check_ip
from mb_netwatch.probes.latency import check_latency
from mb_netwatch.probes.vpn import check_vpn

log = logging.getLogger(__name__)

_Ctx = AppContext[Db, Output, Config]


async def _wait_shutdown(shutdown: asyncio.Event, seconds: float) -> None:
    """Wait for the shutdown signal or timeout, whichever comes first."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(shutdown.wait(), timeout=seconds)


async def _wait_ip(shutdown: asyncio.Event, ip_trigger: asyncio.Event, seconds: float) -> None:
    """Wait for shutdown, IP trigger, or timeout — whichever comes first."""
    trigger_task = asyncio.create_task(ip_trigger.wait())
    shutdown_task = asyncio.create_task(shutdown.wait())
    try:
        await asyncio.wait({trigger_task, shutdown_task}, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
    finally:
        trigger_task.cancel()
        shutdown_task.cancel()


async def _latency_loop(app: _Ctx, shutdown: asyncio.Event) -> None:
    """Measure latency and record to DB. Recreates session on failure."""
    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=app.cfg.probed.latency_timeout))
    try:
        while not shutdown.is_set():
            result = await check_latency(session)
            ts = datetime.now(tz=UTC)
            log.debug("latency=%s ms, endpoint=%s", result.latency_ms, result.winner_endpoint)
            app.svc.insert_latency_check(ts, result.latency_ms, result.winner_endpoint)

            # Self-healing: recreate session on failure to drop stale connections
            if result.latency_ms is None:
                log.debug("Latency check failed, recreating HTTP session.")
                await session.close()
                session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=app.cfg.probed.latency_timeout))

            await _wait_shutdown(shutdown, app.cfg.probed.latency_interval)
    finally:
        await session.close()


async def _vpn_loop(app: _Ctx, shutdown: asyncio.Event, ip_trigger: asyncio.Event) -> None:
    """Check VPN status and record to DB. Signals IP loop on state change."""
    prev_active: bool | None = None
    while not shutdown.is_set():
        status = await asyncio.to_thread(check_vpn)
        ts = datetime.now(tz=UTC)
        log.debug("vpn=%s, mode=%s, provider=%s", status.is_active, status.tunnel_mode, status.provider)
        app.svc.insert_vpn_check(ts, status.is_active, status.tunnel_mode, status.provider)

        if prev_active is not None and status.is_active != prev_active:
            log.info("VPN state changed (%s -> %s), triggering immediate IP check.", prev_active, status.is_active)
            ip_trigger.set()
        prev_active = status.is_active

        await _wait_shutdown(shutdown, app.cfg.probed.vpn_interval)


async def _ip_loop(app: _Ctx, shutdown: asyncio.Event, ip_trigger: asyncio.Event) -> None:
    """Detect public IP and country, record to DB. Wakes early on VPN change."""
    # Seed from DB so we skip country lookup on restart if IP is unchanged
    last = app.svc.fetch_latest_ip_check()
    previous = IpResult(ip=last.ip, country_code=last.country_code) if last else None

    while not shutdown.is_set():
        triggered = ip_trigger.is_set()
        if triggered:
            ip_trigger.clear()
            # Force fresh country lookup — IP likely changed after VPN toggle
            previous = None

        result = await check_ip(previous=previous, http_timeout=app.cfg.probed.ip_timeout)
        ts = datetime.now(tz=UTC)
        log.debug("ip=%s, country=%s", result.ip, result.country_code)
        app.svc.insert_ip_check(ts, result.ip, result.country_code)
        previous = result

        # Wait for next scheduled check or VPN change signal
        await _wait_ip(shutdown, ip_trigger, app.cfg.probed.ip_interval)


async def _purge_loop(app: _Ctx, shutdown: asyncio.Event) -> None:
    """Purge old data periodically."""
    while not shutdown.is_set():
        await _wait_shutdown(shutdown, app.cfg.probed.purge_interval)
        if not shutdown.is_set():
            lat_deleted = app.svc.purge_old_latency_checks(app.cfg.probed.retention_days)
            vpn_deleted = app.svc.purge_old_vpn_checks(app.cfg.probed.retention_days)
            ip_deleted = app.svc.purge_old_ip_checks(app.cfg.probed.retention_days)
            log.info("Purged %d old latency checks, %d old VPN checks, %d old IP checks.", lat_deleted, vpn_deleted, ip_deleted)


async def _run(app: _Ctx) -> None:
    """Launch latency, VPN, and purge loops; shut down cleanly on signal."""
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown.set)

    app.svc.purge_old_latency_checks(app.cfg.probed.retention_days)
    app.svc.purge_old_vpn_checks(app.cfg.probed.retention_days)
    app.svc.purge_old_ip_checks(app.cfg.probed.retention_days)

    ip_trigger = asyncio.Event()

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_latency_loop(app, shutdown))
            tg.create_task(_vpn_loop(app, shutdown, ip_trigger))
            tg.create_task(_ip_loop(app, shutdown, ip_trigger))
            tg.create_task(_purge_loop(app, shutdown))
    finally:
        log.info("probed stopped.")


def probed(ctx: typer.Context) -> None:
    """Run continuous background measurements every 2 seconds."""
    app = use_context(ctx)
    if is_process_running(app.cfg.probed_pid_path, remove_stale=True, skip_self=True):
        typer.echo("probed: already running")
        raise typer.Exit(1)

    setup_logging("mb_netwatch", app.cfg.probed_log_path)
    log.info("probed starting.")
    write_pid_file(app.cfg.probed_pid_path)
    try:
        asyncio.run(_run(app))
    finally:
        app.cfg.probed_pid_path.unlink(missing_ok=True)
