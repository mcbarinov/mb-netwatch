"""Stop probed/tray processes."""

import os
import signal
import time
from typing import Annotated

import typer

from mb_netwatch.app_context import AppContext, use_context
from mb_netwatch.output import StartStopResult
from mb_netwatch.process import Component, is_alive, pid_path, read_pid

_POLL_INTERVAL = 0.2
_STOP_TIMEOUT = 5.0

_BOTH = [Component.PROBED, Component.TRAY]


def _stop_component(component: Component, app: AppContext) -> bool:
    """Stop a single component by sending SIGTERM and waiting for exit."""
    path = pid_path(component, app.cfg.data_dir)
    if not is_alive(path):
        app.out.print_start_stop(StartStopResult(component=component.value, message=f"{component.value}: not running"))
        return True

    pid = read_pid(path)
    if pid is None:
        app.out.print_start_stop(StartStopResult(component=component.value, message=f"{component.value}: not running"))
        return True

    os.kill(pid, signal.SIGTERM)

    # Poll until process exits or timeout
    deadline = time.monotonic() + _STOP_TIMEOUT
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            path.unlink(missing_ok=True)
            app.out.print_start_stop(StartStopResult(component=component.value, message=f"{component.value}: stopped"))
            return True
        except PermissionError:
            break
        time.sleep(_POLL_INTERVAL)

    app.out.print_start_stop(
        StartStopResult(
            component=component.value,
            message=f"{component.value}: failed to stop within {_STOP_TIMEOUT:.1f}s (pid {pid} still running)",
        )
    )
    return False


def stop(ctx: typer.Context, component: Annotated[Component | None, typer.Argument()] = None) -> None:
    """Stop probed and/or tray."""
    app = use_context(ctx)
    targets: list[Component] = [Component(component)] if component else _BOTH
    all_stopped = True
    for target in targets:
        if not _stop_component(target, app):
            all_stopped = False
    if not all_stopped:
        raise typer.Exit(1)
