"""CLI entry point for mb-netwatch."""

from importlib.metadata import version
from typing import Annotated

import typer
from mm_clikit import TyperPlus

from mb_netwatch.app_context import AppContext
from mb_netwatch.commands.probe import probe
from mb_netwatch.commands.probed import probed
from mb_netwatch.commands.start import start
from mb_netwatch.commands.stop import stop
from mb_netwatch.commands.tray import tray
from mb_netwatch.commands.watch import watch
from mb_netwatch.config import Config
from mb_netwatch.db import Db
from mb_netwatch.output import Output

app = TyperPlus(package_name="mb-netwatch")


@app.callback()
def main(
    ctx: typer.Context,
    *,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Internet connection monitor for macOS."""
    _ = version
    cfg = Config.build()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    db = Db(cfg.db_path)
    ctx.call_on_close(db.close)
    ctx.obj = AppContext(out=Output(json_mode=json_output), db=db, cfg=cfg)


app.command(aliases=["p"])(probe)
app.command()(probed)
app.command()(start)
app.command()(stop)
app.command()(tray)
app.command(aliases=["w"])(watch)
