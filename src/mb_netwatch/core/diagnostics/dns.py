"""On-demand DNS diagnostic — runs UDP+TCP against system resolvers and public comparators.

Unlike the steady-state probe in ``core/probes/dns.py``, this is a single heavier check
the user runs by hand when DNS looks broken. It tests the same canary against:

- each system resolver over UDP (matches what apps actually use)
- each system resolver over TCP (catches "UDP/53 blocked but TCP works" cases)
- a fixed set of public resolvers over UDP (1.1.1.1 / 8.8.8.8 / 9.9.9.9) as a baseline

The combined result drives a short verdict line that points the user at the actual
problem class (resolver broken, UDP filtered, upstream down, healthy).
"""

import asyncio
import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict

from mb_netwatch.core.probes.dns import DnsResolverSample, get_system_resolvers, query_one

log = logging.getLogger(__name__)

PUBLIC_RESOLVERS: tuple[str, ...] = ("1.1.1.1", "8.8.8.8", "9.9.9.9")
"""Well-known public DNS resolvers used as a baseline reference."""

_DEFAULT_TIMEOUT = 2.0
"""Default per-query timeout in seconds (UDP and TCP)."""

VerdictCode = Literal[
    "HEALTHY",  # everything responding
    "SYSTEM_OK_PUBLIC_BLOCKED",  # system works, public fails — common on VPN/corporate networks
    "SYSTEM_RESOLVER_BROKEN",  # system fails, public works
    "UDP_BLOCKED",  # UDP fails everywhere, TCP to system works
    "UPSTREAM_DOWN",  # nothing works, including public
    "NO_RESOLVERS",  # scutil returned no nameservers
]


class DnsVerdict(BaseModel):
    """Short interpretation of a diagnosis result."""

    model_config = ConfigDict(frozen=True)

    code: VerdictCode  # Stable identifier for programmatic consumers
    message: str  # Human-readable one-liner shown under the result tables


class DnsDiagnosis(BaseModel):
    """Outcome of one extended DNS diagnostic run."""

    model_config = ConfigDict(frozen=True)

    system_resolvers: list[str]  # Discovered system resolver addresses (empty = no DNS config)
    system_udp: list[DnsResolverSample]  # System resolvers probed over UDP
    system_tcp: list[DnsResolverSample]  # System resolvers probed over TCP
    public_udp: list[DnsResolverSample]  # Public comparators probed over UDP
    verdict: DnsVerdict | None  # None when the result is mixed and no confident pattern matches


def _all_ok(samples: list[DnsResolverSample]) -> bool:
    """Return True when every sample succeeded (non-empty list)."""
    return bool(samples) and all(s.error is None for s in samples)


def _all_fail(samples: list[DnsResolverSample]) -> bool:
    """Return True when every sample failed (non-empty list)."""
    return bool(samples) and all(s.error is not None for s in samples)


def _build_verdict(
    system_resolvers: list[str],
    system_udp: list[DnsResolverSample],
    system_tcp: list[DnsResolverSample],
    public_udp: list[DnsResolverSample],
) -> DnsVerdict | None:
    """Map the combined results to a verdict, or None when the picture is mixed."""
    if not system_resolvers:
        return DnsVerdict(
            code="NO_RESOLVERS",
            message="No system resolvers found. macOS has no active DNS configuration — check the network.",
        )

    sys_udp_ok = _all_ok(system_udp)
    sys_udp_fail = _all_fail(system_udp)
    sys_tcp_ok = _all_ok(system_tcp)
    pub_udp_ok = _all_ok(public_udp)
    pub_udp_fail = _all_fail(public_udp)

    if sys_udp_ok and pub_udp_ok:
        return DnsVerdict(
            code="HEALTHY",
            message="DNS is healthy. System resolvers and public DNS responding normally.",
        )

    # System resolver answers fine but outbound DNS to public servers is blocked.
    # Typical on VPN/corporate networks that force traffic through their resolver.
    if sys_udp_ok and pub_udp_fail:
        return DnsVerdict(
            code="SYSTEM_OK_PUBLIC_BLOCKED",
            message=(
                "System DNS works, but public resolvers are unreachable. "
                "Normal on VPN/corporate networks that restrict outbound DNS — not a problem."
            ),
        )

    # Public DNS unreachable too — DNS itself isn't the layer that's broken.
    if sys_udp_fail and pub_udp_fail and not sys_tcp_ok:
        return DnsVerdict(
            code="UPSTREAM_DOWN",
            message="All DNS — including public resolvers — is failing. Not a DNS problem; upstream connectivity is down.",
        )

    # UDP fails everywhere, but TCP to system works → port 53/UDP is being filtered.
    if sys_udp_fail and pub_udp_fail and sys_tcp_ok:
        return DnsVerdict(
            code="UDP_BLOCKED",
            message=(
                "UDP/53 appears blocked. TCP queries to your resolvers succeed where UDP fails. "
                "Likely network or firewall filtering."
            ),
        )

    # System resolvers fail, public ones answer → the resolver itself is the problem.
    if sys_udp_fail and pub_udp_ok:
        return DnsVerdict(
            code="SYSTEM_RESOLVER_BROKEN",
            message=(
                "System DNS is failing while public DNS works. Likely VPN or router DNS issue — "
                "flushing the cache will not help. Reconnect VPN or change resolvers."
            ),
        )

    return None


async def diagnose_dns(timeout: float = _DEFAULT_TIMEOUT) -> DnsDiagnosis:  # noqa: ASYNC109 — forwarded to query_one → dns.asyncquery
    """Run the extended DNS diagnostic in parallel and return results plus a verdict.

    All queries run concurrently — total wall time is roughly the slowest single query
    (≈ ``timeout`` on a fully broken network).
    """
    resolvers = await asyncio.to_thread(get_system_resolvers)

    system_udp, system_tcp, public_udp = await asyncio.gather(
        asyncio.gather(*(query_one(addr, timeout) for addr in resolvers)),
        asyncio.gather(*(query_one(addr, timeout, tcp=True) for addr in resolvers)),
        asyncio.gather(*(query_one(addr, timeout) for addr in PUBLIC_RESOLVERS)),
    )

    verdict = _build_verdict(resolvers, system_udp, system_tcp, public_udp)

    return DnsDiagnosis(
        system_resolvers=resolvers,
        system_udp=system_udp,
        system_tcp=system_tcp,
        public_udp=public_udp,
        verdict=verdict,
    )
