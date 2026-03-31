"""Typed CLI context."""

import typer
from mm_clikit import AppContext
from mm_clikit import use_context as _use_context

from mb_netwatch.cli.output import Output
from mb_netwatch.config import Config
from mb_netwatch.db import Db


def use_context(ctx: typer.Context) -> AppContext[Db, Output, Config]:
    """Extract typed app context from Typer context."""
    return _use_context(ctx, AppContext[Db, Output, Config])
