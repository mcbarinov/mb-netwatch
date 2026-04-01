"""Continuous background measurement process (probed)."""

import asyncio

import typer
from mm_clikit import CliError, is_process_running

from mb_netwatch.cli.context import use_context
from mb_netwatch.daemon import run_daemon


def probed(ctx: typer.Context) -> None:
    """Run continuous background measurements every 2 seconds."""
    app = use_context(ctx)
    if is_process_running(app.core.cfg.probed_pid_path, remove_stale=True, skip_self=True):
        raise CliError("probed: already running", "ALREADY_RUNNING")

    asyncio.run(run_daemon(app.core))
