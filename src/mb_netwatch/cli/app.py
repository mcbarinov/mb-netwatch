"""CLI app definition and initialization."""

from pathlib import Path
from typing import Annotated

import typer
from mm_clikit import AppContext, TyperPlus

from mb_netwatch.cli.commands.probe import probe
from mb_netwatch.cli.commands.probed import probed
from mb_netwatch.cli.commands.start import start
from mb_netwatch.cli.commands.stop import stop
from mb_netwatch.cli.commands.tray import tray
from mb_netwatch.cli.commands.watch import watch
from mb_netwatch.cli.output import Output
from mb_netwatch.config import Config
from mb_netwatch.db import Db

app = TyperPlus(package_name="mb-netwatch")


@app.callback()
def main(
    ctx: typer.Context,
    *,
    data_dir: Annotated[Path | None, typer.Option("--data-dir", help="Data directory. Env: MB_NETWATCH_DATA_DIR.")] = None,
) -> None:
    """Internet connection monitor for macOS."""
    cfg = Config.build(data_dir)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    db = Db(cfg.db_path)
    ctx.call_on_close(db.close)
    ctx.obj = AppContext(svc=db, out=Output(), cfg=cfg)


app.command(aliases=["p"])(probe)
app.command()(probed)
app.command()(start)
app.command()(stop)
app.command()(tray)
app.command(aliases=["w"])(watch)
