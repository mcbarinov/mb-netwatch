"""Start probed and tray processes in the background."""

import typer
from mm_clikit import is_process_running, spawn_daemon

from mb_netwatch.cli.context import use_context
from mb_netwatch.cli.output import StartStopResult


def start(ctx: typer.Context) -> None:
    """Start probed and tray in the background."""
    app = use_context(ctx)
    for name in ("probed", "tray"):
        path = app.core.config.data_dir / f"{name}.pid"
        if is_process_running(path, remove_stale=True, skip_self=True):
            app.out.print_start_stop(StartStopResult(component=name, message=f"{name}: already running"))
            continue

        pid = spawn_daemon([*app.core.config.base_argv(), name])
        app.out.print_start_stop(StartStopResult(component=name, message=f"{name}: started (pid {pid})"))
