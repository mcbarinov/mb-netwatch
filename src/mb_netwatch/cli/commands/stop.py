"""Stop probed and tray processes."""

import typer
from mm_clikit import CoreContext

from mb_netwatch.cli.context import use_context
from mb_netwatch.cli.output import Output, StartStopResult
from mb_netwatch.core.core import Core
from mb_netwatch.process_control import stop_by_pid_file

_STOP_TIMEOUT = 5.0
"""Seconds to wait for graceful SIGTERM shutdown before giving up."""


def _stop_component(component: str, app: CoreContext[Core, Output]) -> bool:
    """Stop a single component by sending SIGTERM and waiting for exit."""
    path = app.core.config.data_dir / f"{component}.pid"
    result = stop_by_pid_file(path, timeout=_STOP_TIMEOUT, force_kill=False)
    match result.outcome:
        case "not_running":
            app.out.print_start_stop(StartStopResult(component=component, message=f"{component}: not running"))
            return True
        case "stopped":
            app.out.print_start_stop(StartStopResult(component=component, message=f"{component}: stopped"))
            return True
        case "timeout":
            app.out.print_start_stop(
                StartStopResult(
                    component=component,
                    message=f"{component}: failed to stop within {_STOP_TIMEOUT:.1f}s (pid {result.pid} still running)",
                )
            )
            return False


def stop(ctx: typer.Context) -> None:
    """Stop probed and tray."""
    app = use_context(ctx)
    all_stopped = True
    for name in ("probed", "tray"):
        if not _stop_component(name, app):
            all_stopped = False
    if not all_stopped:
        raise typer.Exit(1)
