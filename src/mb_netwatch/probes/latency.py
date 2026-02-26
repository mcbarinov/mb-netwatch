"""Internet latency measurement via HTTP/HTTPS endpoints."""

import asyncio
import logging
import time
from dataclasses import dataclass

import aiohttp

log = logging.getLogger(__name__)

_LATENCY_PROBE_URLS: list[str] = [
    "https://connectivitycheck.gstatic.com/generate_204",
    "https://www.apple.com/library/test/success.html",
    "http://detectportal.firefox.com/success.txt",
    "http://www.msftconnecttest.com/connecttest.txt",
]
"""Captive portal detection endpoints used for latency measurement."""


@dataclass(frozen=True, slots=True)
class LatencyResult:
    """Single latency measurement outcome."""

    latency_ms: float | None
    winner_endpoint: str | None


async def _measure(session: aiohttp.ClientSession, url: str) -> tuple[float, str] | None:
    """Send GET and return (latency_ms, url), or None on failure."""
    start = time.monotonic()
    try:
        async with session.get(url) as resp:
            await resp.read()
    except (aiohttp.ClientError, TimeoutError) as exc:
        log.debug("latency: %s failed: %s", url, exc)
        return None
    else:
        elapsed = round((time.monotonic() - start) * 1000, 3)
        log.debug("latency: %s responded in %.0fms", url, elapsed)
        return elapsed, url


async def check_latency(session: aiohttp.ClientSession | None = None, *, http_timeout: float = 5.0) -> LatencyResult:
    """Measure latency against all endpoints concurrently, return the first success.

    When *session* is provided it is used as-is (probed keeps one alive for
    connection reuse).  When omitted a throwaway session is created with *http_timeout*.
    """
    if session is None:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=http_timeout)) as s:
            return await _check_latency(s)
    return await _check_latency(session)


async def _check_latency(session: aiohttp.ClientSession) -> LatencyResult:
    """Race all endpoints and return the winner."""
    pending: set[asyncio.Task[tuple[float, str] | None]] = {
        asyncio.create_task(_measure(session, url)) for url in _LATENCY_PROBE_URLS
    }
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                result = task.result()
                if result is not None:
                    latency_ms, url = result
                    log.debug("latency: winner %s at %.0fms, cancelling %d remaining", url, latency_ms, len(pending))
                    return LatencyResult(latency_ms=latency_ms, winner_endpoint=url)
        log.debug("latency: all %d endpoints failed", len(_LATENCY_PROBE_URLS))
        return LatencyResult(latency_ms=None, winner_endpoint=None)
    finally:
        for task in pending:
            task.cancel()
