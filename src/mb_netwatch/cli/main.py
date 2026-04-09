"""CLI app definition and initialization."""

from pathlib import Path
from typing import Annotated

import typer
from mm_clikit import CoreContext, TyperPlus

from mb_netwatch.cli.commands.probe import probe
from mb_netwatch.cli.commands.probed import probed
from mb_netwatch.cli.commands.start import start
from mb_netwatch.cli.commands.stop import stop
from mb_netwatch.cli.commands.tray import tray
from mb_netwatch.cli.output import Output
from mb_netwatch.config import Config
from mb_netwatch.core.core import Core
from mb_netwatch.tui.app import TuiApp

app = TyperPlus(package_name="mb-netwatch", no_args_is_help=False)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    *,
    data_dir: Annotated[Path | None, typer.Option("--data-dir", help="Data directory. Env: MB_NETWATCH_DATA_DIR.")] = None,
) -> None:
    """Internet connection monitor for macOS."""
    config = Config.build(data_dir)
    core = Core(config)
    ctx.call_on_close(core.close)
    ctx.obj = CoreContext(core=core, out=Output())

    if ctx.invoked_subcommand is None:
        TuiApp(db=core.db, config=config).run()


app.command(aliases=["p"])(probe)
app.command()(probed)
app.command()(start)
app.command()(stop)
app.command()(tray)
