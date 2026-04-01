"""Typed CLI context."""

import typer
from mm_clikit import AppContext
from mm_clikit import use_context as _use_context

from mb_netwatch.cli.output import Output
from mb_netwatch.config import Config
from mb_netwatch.service import Service


def use_context(ctx: typer.Context) -> AppContext[Service, Output, Config]:
    """Extract typed app context from Typer context."""
    return _use_context(ctx, AppContext[Service, Output, Config])
