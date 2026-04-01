"""One-shot connectivity probe."""

import asyncio
import logging
from typing import Annotated

import typer

from mb_netwatch.cli.context import use_context


def probe(
    ctx: typer.Context,
    *,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show diagnostic details on stderr.")] = False,
) -> None:
    """Run a one-shot connectivity probe and print result."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    app = use_context(ctx)
    result = asyncio.run(app.svc.run_probe())
    app.out.print_probe(result)
