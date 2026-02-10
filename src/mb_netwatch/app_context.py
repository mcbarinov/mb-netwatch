"""Application context shared across CLI commands."""

from dataclasses import dataclass

import typer

from mb_netwatch.config import Config
from mb_netwatch.db import Db
from mb_netwatch.output import Output


@dataclass(frozen=True, slots=True)
class AppContext:
    """Shared application state passed through Typer context."""

    out: Output
    db: Db
    cfg: Config


def use_context(ctx: typer.Context) -> AppContext:
    """Extract application context from Typer context."""
    result: AppContext = ctx.obj
    return result
