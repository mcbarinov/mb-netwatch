"""Public IP address and country detection."""

import asyncio
import ipaddress
import logging
import random
from collections.abc import Callable

import aiohttp
from pydantic import BaseModel, ConfigDict

log = logging.getLogger(__name__)

_IP_SERVICES: list[str] = [
    "https://api.ipify.org",
    "https://ipv4.icanhazip.com",
    "https://checkip.amazonaws.com",
    "https://ipinfo.io/ip",
    "https://v4.ident.me",
]
"""Plain-text IP detection services."""

_IP_COUNTRY_SERVICES: list[str] = [
    "https://ipinfo.io/{ip}/country",
    "https://ipapi.co/{ip}/country/",
]
"""Country resolution URL templates ({ip} is replaced at runtime)."""


class IpResult(BaseModel):
    """Public IP detection outcome."""

    model_config = ConfigDict(frozen=True)

    ip: str | None  # Public IPv4 address; None when all lookups failed
    country_code: str | None  # 2-letter ISO country code; None when lookup failed


async def _race_urls(session: aiohttp.ClientSession, urls: list[str]) -> str | None:
    """GET all *urls* concurrently, return first successful stripped response text."""

    async def _get(url: str) -> str | None:
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                text = (await resp.text()).strip()
                log.debug("ip: %s returned %r", url, text)
                return text
        except (aiohttp.ClientError, TimeoutError) as exc:
            log.debug("ip: %s failed: %s", url, exc)
            return None

    pending: set[asyncio.Task[str | None]] = {asyncio.create_task(_get(url)) for url in urls}
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                text = task.result()
                if text:
                    return text
        log.warning("ip: all %d urls failed or returned empty", len(urls))
        return None
    finally:
        for task in pending:
            task.cancel()


async def check_ip(
    *,
    previous: IpResult | None = None,
    known_country_lookup: Callable[[str], str | None] | None = None,
    http_timeout: float = 5.0,
) -> IpResult:
    """Detect public IP and resolve its country code.

    Races 2 random IP services, then races country services for the winner.
    When *previous* is provided and the detected IP matches ``previous.ip``,
    the country code is reused without making extra API calls.

    When *known_country_lookup* is provided, it is consulted for any detected
    IP that is not the in-process ``previous.ip`` — this lets a persistent
    store (e.g. the ``probe_ip`` history table) short-circuit the country
    race for IPs that have been resolved before.

    Each call creates a throwaway session — connection reuse is pointless
    at 60-second intervals (exceeds default keepalive).
    """
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=http_timeout)) as session:
        return await _check_ip(session, previous, known_country_lookup)


async def _check_ip(
    session: aiohttp.ClientSession,
    previous: IpResult | None,
    known_country_lookup: Callable[[str], str | None] | None,
) -> IpResult:
    """Detect IP, then resolve country."""
    # Step 1: detect IP by racing 2 random services
    selected = random.sample(_IP_SERVICES, 2)
    ip_text = await _race_urls(session, selected)

    ip: str | None = None
    if ip_text:
        try:
            ipaddress.IPv4Address(ip_text)
        except ValueError:
            log.debug("ip: invalid IPv4 response: %r", ip_text)
        else:
            ip = ip_text

    if ip is None:
        return IpResult(ip=None, country_code=None)

    # Reuse country code when IP hasn't changed
    if previous and ip == previous.ip and previous.country_code:
        return IpResult(ip=ip, country_code=previous.country_code)

    # Persistent cache: reuse country if this IP has been resolved before
    if known_country_lookup is not None:
        cached = known_country_lookup(ip)
        if cached:
            return IpResult(ip=ip, country_code=cached)

    # Step 2: resolve country by racing geo services
    country_urls = [url.format(ip=ip) for url in _IP_COUNTRY_SERVICES]
    country_text = await _race_urls(session, country_urls)

    country_code: str | None = None
    if country_text and len(country_text) == 2 and country_text.isascii() and country_text.isalpha() and country_text.isupper():
        country_code = country_text
    elif country_text:
        log.debug("ip: invalid country response: %r", country_text)

    return IpResult(ip=ip, country_code=country_code)
