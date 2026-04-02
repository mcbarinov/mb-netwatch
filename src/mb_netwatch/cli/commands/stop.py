"""Stop probed/tray processes."""

from typing import Annotated, Literal

import typer
from mm_clikit import CoreContext, is_process_running, read_pid_file, stop_process

from mb_netwatch.cli.context import use_context
from mb_netwatch.cli.output import Output, StartStopResult
from mb_netwatch.core import Core

_STOP_TIMEOUT = 5.0


def _stop_component(component: str, app: CoreContext[Core, Output]) -> bool:
    """Stop a single component by sending SIGTERM and waiting for exit."""
    path = app.core.config.data_dir / f"{component}.pid"
    if not is_process_running(path, remove_stale=True, skip_self=True):
        app.out.print_start_stop(StartStopResult(component=component, message=f"{component}: not running"))
        return True

    pid = read_pid_file(path)
    if pid is None:
        app.out.print_start_stop(StartStopResult(component=component, message=f"{component}: not running"))
        return True

    stopped = stop_process(pid, timeout=_STOP_TIMEOUT, force_kill=False)
    if stopped:
        path.unlink(missing_ok=True)
        app.out.print_start_stop(StartStopResult(component=component, message=f"{component}: stopped"))
    else:
        app.out.print_start_stop(
            StartStopResult(
                component=component,
                message=f"{component}: failed to stop within {_STOP_TIMEOUT:.1f}s (pid {pid} still running)",
            )
        )
    return stopped


def stop(ctx: typer.Context, component: Annotated[Literal["probed", "tray"] | None, typer.Argument()] = None) -> None:
    """Stop probed and/or tray."""
    app = use_context(ctx)
    all_stopped = True
    for name in (component,) if component else ("probed", "tray"):
        if not _stop_component(name, app):
            all_stopped = False
    if not all_stopped:
        raise typer.Exit(1)
