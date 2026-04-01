"""Menu bar UI process CLI entry point."""

import typer
from mm_clikit import CliError, is_process_running

from mb_netwatch.cli.context import use_context
from mb_netwatch.tray import NetwatchTray


def tray(ctx: typer.Context) -> None:
    """Run menu bar UI process that displays current status."""
    app = use_context(ctx)
    if is_process_running(app.core.cfg.tray_pid_path, remove_stale=True, skip_self=True):
        raise CliError("tray: already running", "ALREADY_RUNNING")

    NetwatchTray(app.core).run()
