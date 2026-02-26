"""Start probed/tray processes in the background."""

import shutil
from typing import Annotated, Literal

import typer
from mm_clikit import is_process_running, spawn_detached

from mb_netwatch.app_context import use_context
from mb_netwatch.output import StartStopResult


def start(ctx: typer.Context, component: Annotated[Literal["probed", "tray"] | None, typer.Argument()] = None) -> None:
    """Start probed and/or tray in the background."""
    app = use_context(ctx)
    for name in (component,) if component else ("probed", "tray"):
        path = app.cfg.data_dir / f"{name}.pid"
        if is_process_running(path, remove_stale=True, skip_self=True):
            app.out.print_start_stop(StartStopResult(component=name, message=f"{name}: already running"))
            continue

        exe = shutil.which("mb-netwatch")
        if not exe:
            app.out.print_error_and_exit("exe_not_found", "'mb-netwatch' not found in PATH. Install with: uv tool install .")

        pid = spawn_detached([exe, name])
        app.out.print_start_stop(StartStopResult(component=name, message=f"{name}: started (pid {pid})"))
