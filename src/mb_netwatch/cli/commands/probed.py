"""Continuous background measurement process (probed)."""

import asyncio
import logging

import typer
from mm_clikit import CliError, is_process_running, setup_logging, write_pid_file

from mb_netwatch.cli.context import use_context
from mb_netwatch.daemon import run_daemon

log = logging.getLogger(__name__)


def probed(ctx: typer.Context) -> None:
    """Run continuous background measurements every 2 seconds."""
    app = use_context(ctx)
    if is_process_running(app.cfg.probed_pid_path, remove_stale=True, skip_self=True):
        raise CliError("probed: already running", "ALREADY_RUNNING")

    setup_logging("mb_netwatch", app.cfg.probed_log_path)
    log.info("probed starting.")
    write_pid_file(app.cfg.probed_pid_path)
    try:
        asyncio.run(run_daemon(app.svc))
    finally:
        app.cfg.probed_pid_path.unlink(missing_ok=True)
