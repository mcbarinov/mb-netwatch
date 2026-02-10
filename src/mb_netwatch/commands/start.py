"""Start probed/tray processes in the background."""

from typing import Annotated

import typer

from mb_netwatch.app_context import AppContext, use_context
from mb_netwatch.output import StartStopResult
from mb_netwatch.process import Component, is_alive, pid_path, spawn_component

_BOTH = [Component.PROBED, Component.TRAY]


def _start_component(component: Component, app: AppContext) -> None:
    """Start a single component as a detached background process."""
    path = pid_path(component, app.cfg.data_dir)
    if is_alive(path):
        app.out.print_start_stop(StartStopResult(component=component.value, message=f"{component.value}: already running"))
        return

    try:
        pid = spawn_component(component)
    except FileNotFoundError:
        app.out.print_error_and_exit("exe_not_found", "'mb-netwatch' not found in PATH. Install with: uv tool install .")

    app.out.print_start_stop(StartStopResult(component=component.value, message=f"{component.value}: started (pid {pid})"))


def start(ctx: typer.Context, component: Annotated[Component | None, typer.Argument()] = None) -> None:
    """Start probed and/or tray in the background."""
    app = use_context(ctx)
    targets: list[Component] = [Component(component)] if component else _BOTH
    for target in targets:
        _start_component(target, app)
