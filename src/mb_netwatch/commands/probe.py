"""One-shot connectivity probe."""

import asyncio

import typer

from mb_netwatch.app_context import AppContext, use_context
from mb_netwatch.output import ProbeResult
from mb_netwatch.probes.ip import check_ip
from mb_netwatch.probes.latency import check_latency
from mb_netwatch.probes.vpn import check_vpn

app = typer.Typer()


@app.command()
def probe(ctx: typer.Context) -> None:
    """Run a one-shot connectivity probe and print result."""
    asyncio.run(_probe(use_context(ctx)))


async def _probe(app: AppContext) -> None:
    """Run all checks concurrently and print result."""
    latency, vpn, ip_result = await asyncio.gather(
        check_latency(http_timeout=app.cfg.probed.latency_timeout),
        asyncio.to_thread(check_vpn),
        check_ip(http_timeout=app.cfg.probed.ip_timeout),
    )

    result = ProbeResult(
        latency_ms=latency.latency_ms,
        winner_endpoint=latency.winner_endpoint,
        vpn_active=vpn.is_active,
        tunnel_mode=vpn.tunnel_mode,
        vpn_provider=vpn.provider,
        ip=ip_result.ip,
        country_code=ip_result.country_code,
    )
    app.out.print_probe(result)
