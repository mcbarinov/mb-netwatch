"""Public IP address and country detection."""

import asyncio
import ipaddress
import random
from dataclasses import dataclass

import aiohttp

_IP_SERVICES: list[str] = [
    "https://api.ipify.org",
    "https://icanhazip.com",
    "https://checkip.amazonaws.com",
    "https://ifconfig.me/ip",
    "https://ipinfo.io/ip",
    "https://v4.ident.me",
]
"""Plain-text IP detection services."""

_IP_COUNTRY_SERVICES: list[str] = [
    "https://ipinfo.io/{ip}/country",
    "https://ipapi.co/{ip}/country/",
]
"""Country resolution URL templates ({ip} is replaced at runtime)."""


@dataclass(frozen=True, slots=True)
class IpResult:
    """Public IP detection outcome."""

    ip: str | None
    country_code: str | None


async def _race_urls(session: aiohttp.ClientSession, urls: list[str]) -> str | None:
    """GET all *urls* concurrently, return first successful stripped response text."""

    async def _get(url: str) -> str | None:
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return (await resp.text()).strip()
        except aiohttp.ClientError, TimeoutError:
            return None

    pending: set[asyncio.Task[str | None]] = {asyncio.create_task(_get(url)) for url in urls}
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                text = task.result()
                if text:
                    return text
        return None
    finally:
        for task in pending:
            task.cancel()


async def check_ip(*, previous: IpResult | None = None, http_timeout: float = 5.0) -> IpResult:
    """Detect public IP and resolve its country code.

    Races 2 random IP services, then races country services for the winner.
    When *previous* is provided and the detected IP matches ``previous.ip``,
    the country code is reused without making extra API calls.

    Each call creates a throwaway session — connection reuse is pointless
    at 60-second intervals (exceeds default keepalive).
    """
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=http_timeout)) as session:
        return await _check_ip(session, previous)


async def _check_ip(session: aiohttp.ClientSession, previous: IpResult | None) -> IpResult:
    """Detect IP, then resolve country."""
    # Step 1: detect IP by racing 2 random services
    ip_text = await _race_urls(session, random.sample(_IP_SERVICES, 2))

    ip: str | None = None
    if ip_text:
        try:
            ipaddress.IPv4Address(ip_text)
        except ValueError:
            pass
        else:
            ip = ip_text

    if ip is None:
        return IpResult(ip=None, country_code=None)

    # Reuse country code when IP hasn't changed
    if previous and ip == previous.ip and previous.country_code:
        return IpResult(ip=ip, country_code=previous.country_code)

    # Step 2: resolve country by racing geo services
    country_urls = [url.format(ip=ip) for url in _IP_COUNTRY_SERVICES]
    country_text = await _race_urls(session, country_urls)

    country_code: str | None = None
    if country_text and len(country_text) == 2 and country_text.isascii() and country_text.isalpha() and country_text.isupper():
        country_code = country_text

    return IpResult(ip=ip, country_code=country_code)
