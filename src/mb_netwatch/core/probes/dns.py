"""DNS resolution probe — measures latency of the system's own DNS resolvers."""

import asyncio
import logging
import subprocess  # nosec B404
import time

import dns.asyncquery
import dns.exception
import dns.message
import dns.rcode
import dns.rdatatype
from pydantic import BaseModel, ConfigDict

log = logging.getLogger(__name__)

_CANARY_DOMAIN = "cloudflare.com"
"""Fixed A-record canary: short name, DNS-native operator, 300 s TTL."""

_DEFAULT_TIMEOUT = 2.0
"""Default UDP query timeout in seconds."""

_SCUTIL_TIMEOUT = 3.0
"""Timeout for the `scutil --dns` subprocess in seconds."""


class DnsResolverSample(BaseModel):
    """Outcome of probing a single system DNS resolver."""

    model_config = ConfigDict(frozen=True)

    address: str  # Resolver IP (IPv4 or IPv6) as reported by scutil
    resolve_ms: float | None  # UDP round-trip in ms; None on timeout/network/malformed
    error: str | None  # "timeout" / "network" / "malformed" / rcode name / "other"; None on success


class DnsResult(BaseModel):
    """Outcome of one DNS probe cycle across all system resolvers."""

    model_config = ConfigDict(frozen=True)

    resolvers: list[DnsResolverSample]  # System order; [0] is primary; empty = no DNS config


def _parse_scutil_dns(text: str) -> list[str]:
    """Extract nameservers of `resolver #1` from the main `DNS configuration` section."""
    in_main = False
    in_resolver_1 = False
    nameservers: list[str] = []

    for raw in text.splitlines():
        line = raw.strip()

        # Scoped-queries section follows the main one — stop before it.
        if line.startswith("DNS configuration (for scoped"):
            break

        if line == "DNS configuration":
            in_main = True
            continue

        if not in_main:
            continue

        if line == "resolver #1":
            in_resolver_1 = True
            continue

        # Any other `resolver #N` in the main section is a per-domain scope
        # (.local mDNS, ip6.arpa reverse zones, ...) — skip its nameservers.
        if line.startswith("resolver #"):
            in_resolver_1 = False
            continue

        if in_resolver_1 and line.startswith("nameserver["):
            # "nameserver[0] : 192.168.1.1" — partition on the first ':' only (safe for IPv6).
            _, _, addr = line.partition(":")
            addr = addr.strip()
            if addr:
                nameservers.append(addr)

    return nameservers


def _get_system_resolvers() -> list[str]:
    """Return addresses of the system's default DNS resolvers, or [] on any failure."""
    try:
        output = subprocess.check_output(["scutil", "--dns"], text=True, timeout=_SCUTIL_TIMEOUT)  # noqa: S607 — fixed system command, no user input  # nosec B603, B607
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("dns: scutil --dns failed: %s", exc)
        return []
    return _parse_scutil_dns(output)


async def _query_one(nameserver: str, timeout: float) -> DnsResolverSample:  # noqa: ASYNC109 — forwarded directly to dns.asyncquery.udp which accepts timeout natively
    """Send `A cloudflare.com` over UDP to *nameserver* and return a sample."""
    query = dns.message.make_query(_CANARY_DOMAIN, dns.rdatatype.A)
    start = time.monotonic()
    try:
        response = await dns.asyncquery.udp(query, nameserver, timeout=timeout)
    except dns.exception.Timeout:
        log.debug("dns: %s timed out", nameserver)
        return DnsResolverSample(address=nameserver, resolve_ms=None, error="timeout")
    except OSError as exc:
        log.debug("dns: %s network error: %s", nameserver, exc)
        return DnsResolverSample(address=nameserver, resolve_ms=None, error="network")
    except dns.exception.DNSException as exc:
        log.debug("dns: %s malformed response: %s", nameserver, exc)
        return DnsResolverSample(address=nameserver, resolve_ms=None, error="malformed")
    except Exception as exc:
        log.warning("dns: %s unexpected error: %s", nameserver, exc)
        return DnsResolverSample(address=nameserver, resolve_ms=None, error="other")

    elapsed_ms = round((time.monotonic() - start) * 1000, 3)
    rcode = response.rcode()
    if rcode != dns.rcode.NOERROR:
        # Resolver replied but with a non-success rcode (SERVFAIL/REFUSED/NXDOMAIN/...).
        # The exchange completed, so resolve_ms is meaningful and recorded alongside the error.
        error = dns.rcode.to_text(rcode).lower()
        log.debug("dns: %s rcode=%s in %.0fms", nameserver, error, elapsed_ms)
        return DnsResolverSample(address=nameserver, resolve_ms=elapsed_ms, error=error)

    log.debug("dns: %s responded in %.0fms", nameserver, elapsed_ms)
    return DnsResolverSample(address=nameserver, resolve_ms=elapsed_ms, error=None)


async def check_dns(timeout: float = _DEFAULT_TIMEOUT) -> DnsResult:  # noqa: ASYNC109 — forwarded to _query_one → dns.asyncquery.udp
    """Query every system DNS resolver in parallel for `A cloudflare.com` over UDP."""
    resolvers = await asyncio.to_thread(_get_system_resolvers)
    if not resolvers:
        log.warning("dns: no system resolvers found")
        return DnsResult(resolvers=[])

    tasks = [_query_one(addr, timeout) for addr in resolvers]
    samples = await asyncio.gather(*tasks)
    return DnsResult(resolvers=list(samples))
