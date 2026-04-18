# Probe Algorithms

> **Source of truth.** This document defines probe behavior. Code must follow these specifications.
> If the code diverges from this document, the code is wrong — update the code, not the doc.

## Latency

Two independent HTTP latency probes run side by side: **warm** and **cold**. Neither uses ICMP ping — many VPN tunnels don't route ICMP traffic, which is why this project measures over HTTP instead. HTTP works over any TCP-capable connection regardless of VPN configuration.

Both probes target the same set of **captive portal detection endpoints** — lightweight URLs that OS and browser vendors operate specifically for connectivity checking:

- `https://connectivitycheck.gstatic.com/generate_204` — Google, HTTPS, 204 No Content
- `https://www.apple.com/library/test/success.html` — Apple, HTTPS, tiny HTML
- `http://detectportal.firefox.com/success.txt` — Mozilla, HTTP, "success"
- `http://www.msftconnecttest.com/connecttest.txt` — Microsoft, HTTP, "Microsoft Connect Test"

**Why these endpoints:**
- **Purpose-built** — designed for automated connectivity checks, not general web pages
- **Minimal payload** — empty body or a few bytes, negligible bandwidth
- **Global CDN** — low latency from virtually any location
- **High uptime** — operated by Google, Apple, Mozilla, Microsoft
- **No rate limiting** — billions of devices hit them daily; our requests are invisible
- **Never blocked by ISPs** — blocking would break captive portal detection on every phone, laptop, and tablet
- **Multiple providers** — if one company's infrastructure has issues, the others still work

**Shared request mechanics (both probes):**
1. Requests are sent to all endpoints simultaneously
2. The first successful response wins — all remaining requests are cancelled immediately
3. If no response arrives within the timeout (default 5 seconds) — status is "Down"

### Latency (warm)

Uses one long-lived `aiohttp.ClientSession` across probe cycles (HTTP keep-alive, pooled connections). Measures steady-state responsiveness over an established connection — effectively the HTTP analogue of ping.

- Low baseline latency makes steady-state network degradation visible
- Eliminates TLS-handshake variance from measurement noise
- On sustained failure the session is automatically recreated to drop stale pooled connections
- Runs every **2 seconds** by default
- Stored in the `probe_latency_warm` table

### Latency (cold)

Creates a fresh `aiohttp.ClientSession` for every probe — no pooling, no keep-alive reuse. Measures the full cost of establishing a new connection end-to-end: DNS resolution, TCP handshake, TLS handshake, and the first HTTP round-trip.

This is the complement to the warm probe. A browser opens new connections for new pages, new tabs, and new hosts; when that setup path is broken (DNS slow, TCP handshake failing, TLS stalled, firewall state table exhausted), the warm probe can still report "all good" because it reuses a connection that was opened before the problem started. Cold catches exactly that class of incident.

- Baseline is higher than warm by roughly the TCP + TLS handshake cost (~100-300 ms on a healthy link)
- No self-healing logic needed — each cycle builds and tears down its own session
- Runs every **10 seconds** by default (cheaper than warm would be on paper, but each cycle is more expensive per request, so the interval is tuned for a reasonable load on the captive-portal endpoints)
- Stored in the `probe_latency_cold` table

Thresholds (`ok_ms`, `slow_ms`, `stale_seconds`) are configured separately for warm and cold via `[warm_latency_threshold]` and `[cold_latency_threshold]` TOML sections. Defaults for cold are intentionally higher to account for the handshake overhead.

## VPN Status

Detects VPN state every 10 seconds and stores only information that is directly useful for end users:

- **Active/inactive** — whether traffic is currently routed through a tunnel interface
- **Tunnel mode** — full tunnel (all traffic via VPN) vs split tunnel (only part of traffic via VPN); `NULL` when VPN is inactive or routing table cannot be parsed
- **Provider (best effort)** — VPN app name when it can be identified with sufficient confidence; otherwise `NULL`

### How VPN detection works

The detector uses a simple priority-based pipeline:

1. **Detect tunnel presence**
   - Find active `tun*`/`utun*` interface with IPv4 address.
   - If no tunnel interface is found, VPN is considered inactive.
2. **Detect tunnel mode**
   - Parse `netstat -rn -f inet`.
   - Full tunnel if default route is via tunnel, or if OpenVPN-style `0/1` + `128.0/1` routes are via tunnel.
   - Otherwise split tunnel.
   - If routing cannot be parsed, mode is `NULL`.
3. **Detect provider**
   - Parse `scutil --nc list`.
   - If a service with `(Connected)` status is found, use its name as provider.
   - Otherwise `NULL`.

## Public IP

Detects the public IP address and its country every 60 seconds. Useful for verifying which exit point your traffic uses — especially after toggling a VPN.

**IP detection services** (plain-text responses):
- `https://api.ipify.org` — ipify
- `https://ipv4.icanhazip.com` — icanhazip
- `https://checkip.amazonaws.com` — Amazon
- `https://ipinfo.io/ip` — ipinfo
- `https://v4.ident.me` — ident.me

**Country resolution services** (2-letter ISO code):
- `https://ipinfo.io/{ip}/country` — ipinfo
- `https://ipapi.co/{ip}/country/` — ipapi

**How it works:**
1. Two random services are picked from the IP list and raced — first valid IPv4 response wins
2. If the IP is the same as the previous check, the country code is reused (saves API quota)
3. If the IP changed, the daemon first checks whether this IP has been resolved before in the local `probe_ip` history — if so, the prior country code is reused. Only a genuinely new IP triggers the country-service race.
4. Responses are validated: IP must be a valid IPv4 address, country must be exactly 2 uppercase ASCII letters

## DNS

DNS resolution is measured separately from HTTP latency because the two probes cover different failure modes. The HTTP latency probe reuses keep-alive connections, so it resolves each endpoint once and is blind to subsequent DNS problems. Meanwhile DNS is a frequent and independent source of "internet is broken" incidents — the resolver may be slow, unreachable, hijacked, or swapped out by a VPN — and none of that shows up in HTTP timings.

The probe measures **latency of the system's own DNS resolvers**, not of public ones like `1.1.1.1`. The goal is to reflect what macOS actually uses for name resolution at this moment. When a VPN is active, macOS replaces the resolver set with the VPN's resolvers; the probe automatically picks that up on the next cycle.

**How resolver discovery works:**
1. Run `scutil --dns` and read its output. This is the authoritative source of macOS DNS configuration — `/etc/resolv.conf` is a legacy shim and does not reflect the real resolver set (especially under VPN).
2. Locate the main `DNS configuration` section (not `DNS configuration (for scoped queries)`, which comes after it).
3. Inside that section, locate `resolver #1` — the default resolver. Collect every `nameserver[N] : ADDRESS` line from that block. `resolver #2`, `#3` and so on in the main section are per-domain scopes (e.g. `.local`, `ip6.arpa`) and are ignored.
4. **Fallback for VPNs that only publish DNS via per-interface scoping** (observed with clients like Happ Plus): if `resolver #1` in the main section has no `nameserver[]` entries, walk the `(for scoped queries)` section and collect `nameserver[]` entries from every resolver block that does *not* have a `domain :` line. Domain-scoped blocks are always ignored because they only serve lookups matching that specific domain. Interface-scoped blocks (those tagged with `if_index : N (ifN)`) represent the effective DNS for all traffic going out that interface, and when the main default resolver is empty they are what macOS is actually using.
5. If neither pass finds any nameservers, the probe reports an empty resolver list. An empty list is itself a diagnostic signal: the system has no DNS configuration (no network, broken `configd`, etc.).

**How probing works:**
1. For each nameserver discovered in steps 3–4 above, build a DNS query for the canary record `A cloudflare.com` and send it over UDP directly to that nameserver. All nameservers are probed **in parallel** — in the typical single-resolver case this collapses to one query; in multi-resolver setups it captures the "primary dead, fallback alive" scenario that a primary-only probe would miss.
2. Round-trip time is measured with a wall-clock timer around the UDP exchange. Each nameserver's result is independent: a `resolve_ms` value on success, or one of the error categories below on failure.
3. If a nameserver does not respond within 2 seconds the result is recorded as `timeout`. Other failure categories: `network` (socket error, e.g. unreachable through a down VPN tunnel), `malformed` (response unparseable), `servfail` / `refused` / `nxdomain` / ... (resolver replied with a non-success rcode — `resolve_ms` is still recorded because the exchange completed).
4. There are **no retries and no TCP fallback**. The probe measures a single UDP round-trip per resolver per cycle. Retries would mask the very degradation the probe exists to detect.

**Why `cloudflare.com` as the canary:**
- Short name — minimal UDP packet size
- Operated by a DNS-native company, essentially guaranteed to resolve
- Short TTL (300 s) — does not get pinned indefinitely in upstream caches
- Always an A record — no AAAA / dual-stack complications

Because the canary's 300 s TTL is much longer than the probe cadence, most measured round-trips are served from the upstream resolver's cache. The stored `resolve_ms` therefore reflects **resolver-path reachability and cached-answer speed**, not full upstream recursion health — cache-busting is intentionally avoided because random-subdomain hammering of a domain we do not control is abusive and produces misleading NXDOMAIN signals.

**What is deliberately not measured:**
- **Correctness of the answer** — no IP comparison, no DNSSEC validation, no hijack detection. The probe cares about latency and reachability only.
- **AAAA records** — only A is queried. Dual-stack measurement would double the data without adding useful failure signal for this use case.
- **Public resolvers** (`1.1.1.1`, `8.8.8.8`, etc.) — they measure a different path than what the system actually uses.
- **Domain-scoped resolvers** (any resolver block in `scutil --dns` output that carries a `domain :` line, whether in the main or the scoped-queries section) — these serve only lookups matching that specific domain (e.g. `.local` mDNS, `ip6.arpa` reverse zones) and do not reflect general DNS.
