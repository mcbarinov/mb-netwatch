"""Typed CLI context."""

import typer
from mm_clikit import CoreContext
from mm_clikit import use_context as _use_context

from mb_netwatch.cli.output import Output
from mb_netwatch.core.core import Core


def use_context(ctx: typer.Context) -> CoreContext[Core, Output]:
    """Extract typed core context from Typer context."""
    return _use_context(ctx, CoreContext[Core, Output])
