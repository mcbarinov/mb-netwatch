"""Extended DNS diagnostic — tests system resolvers (UDP+TCP) plus public comparators."""

import asyncio
import logging
from typing import Annotated

import typer

from mb_netwatch.cli.context import use_context
from mb_netwatch.core.diagnostics.dns import diagnose_dns


def dns(
    ctx: typer.Context,
    *,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show diagnostic details on stderr.")] = False,
) -> None:
    """Run an on-demand DNS diagnostic against system and public resolvers."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    app = use_context(ctx)
    diagnosis = asyncio.run(diagnose_dns(timeout=app.core.config.probed.dns_timeout))
    app.out.print_dns_diagnosis(diagnosis)
