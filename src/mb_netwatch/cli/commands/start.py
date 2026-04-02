"""Start probed/tray processes in the background."""

import shutil
from typing import Annotated, Literal

import typer
from mm_clikit import CliError, is_process_running, spawn_daemon

from mb_netwatch.cli.context import use_context
from mb_netwatch.cli.output import StartStopResult


def start(ctx: typer.Context, component: Annotated[Literal["probed", "tray"] | None, typer.Argument()] = None) -> None:
    """Start probed and/or tray in the background."""
    app = use_context(ctx)
    for name in (component,) if component else ("probed", "tray"):
        path = app.core.config.data_dir / f"{name}.pid"
        if is_process_running(path, remove_stale=True, skip_self=True):
            app.out.print_start_stop(StartStopResult(component=name, message=f"{name}: already running"))
            continue

        exe = shutil.which("mb-netwatch")
        if not exe:
            raise CliError("'mb-netwatch' not found in PATH. Install with: uv tool install .", "EXE_NOT_FOUND")

        pid = spawn_daemon([*app.core.config.cli_base_args(), name])
        app.out.print_start_stop(StartStopResult(component=name, message=f"{name}: started (pid {pid})"))
