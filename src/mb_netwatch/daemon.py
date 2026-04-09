"""Continuous background measurement daemon."""

import asyncio
import contextlib
import logging
import signal

from mm_clikit import setup_logging, write_pid_file

from mb_netwatch.core.core import Core

log = logging.getLogger(__name__)


async def run_daemon(core: Core) -> None:
    """Launch latency, VPN, IP, and purge loops; shut down cleanly on signal."""
    setup_logging("mb_netwatch", core.config.probed_log_path)
    log.info("probed starting.")
    write_pid_file(core.config.probed_pid_path)

    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown.set)

    cfg = core.config.probed
    core.db.purge_old_probe_latency(cfg.retention_days)
    core.db.purge_old_probe_vpn(cfg.retention_days)
    core.db.purge_old_probe_ip(cfg.retention_days)

    # VPN loop sets this event when VPN state changes, so IP loop wakes up immediately instead of waiting for its full interval
    ip_trigger = asyncio.Event()

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_latency_loop(core, shutdown))
            tg.create_task(_vpn_loop(core, shutdown, ip_trigger))
            tg.create_task(_ip_loop(core, shutdown, ip_trigger))
            tg.create_task(_purge_loop(core, shutdown))
    finally:
        await core.service.close_latency_session()
        core.config.probed_pid_path.unlink(missing_ok=True)
        log.info("probed stopped.")


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


async def _latency_loop(core: Core, shutdown: asyncio.Event) -> None:
    """Run latency probes on interval."""
    while not shutdown.is_set():
        await core.service.run_latency_check()
        await _wait_shutdown(shutdown, core.config.probed.latency_interval)


async def _vpn_loop(core: Core, shutdown: asyncio.Event, ip_trigger: asyncio.Event) -> None:
    """Run VPN checks on interval. Signal IP loop on state change."""
    prev_active: bool | None = None
    while not shutdown.is_set():
        is_active = await core.service.run_vpn_check()

        if prev_active is not None and is_active != prev_active:
            log.info("VPN state changed (%s -> %s), triggering immediate IP check.", prev_active, is_active)
            ip_trigger.set()
        prev_active = is_active

        await _wait_shutdown(shutdown, core.config.probed.vpn_interval)


async def _ip_loop(core: Core, shutdown: asyncio.Event, ip_trigger: asyncio.Event) -> None:
    """Run IP checks on interval. Wakes early on VPN state change."""
    while not shutdown.is_set():
        vpn_changed = ip_trigger.is_set()
        if vpn_changed:
            ip_trigger.clear()

        await core.service.run_ip_check(vpn_changed=vpn_changed)

        await _wait_ip(shutdown, ip_trigger, core.config.probed.ip_interval)


async def _purge_loop(core: Core, shutdown: asyncio.Event) -> None:
    """Purge old data periodically."""
    cfg = core.config.probed
    while not shutdown.is_set():
        await _wait_shutdown(shutdown, cfg.purge_interval)
        if not shutdown.is_set():
            lat_deleted = core.db.purge_old_probe_latency(cfg.retention_days)
            vpn_deleted = core.db.purge_old_probe_vpn(cfg.retention_days)
            ip_deleted = core.db.purge_old_probe_ip(cfg.retention_days)
            log.info("Purged %d latency, %d VPN, %d IP old probe rows.", lat_deleted, vpn_deleted, ip_deleted)
