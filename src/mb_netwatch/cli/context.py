"""Typed CLI context."""

from dataclasses import dataclass

import typer

from mb_netwatch.cli.output import Output
from mb_netwatch.core import Core


@dataclass(frozen=True, slots=True)
class CoreContext:
    """Shared state passed through Typer context to all CLI commands."""

    core: Core
    out: Output


def use_context(ctx: typer.Context) -> CoreContext:
    """Extract typed core context from Typer context."""
    return ctx.obj  # type: ignore[no-any-return]
