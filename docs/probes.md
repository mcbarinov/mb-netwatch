# Probe Algorithms

> **Source of truth.** This document defines probe behavior. Code must follow these specifications.
> If the code diverges from this document, the code is wrong — update the code, not the doc.

## Latency

Latency is measured via HTTP/HTTPS requests, not ICMP ping — many VPN tunnels don't route ICMP traffic, making ping unreliable. HTTP requests work over any TCP-capable connection regardless of VPN configuration.

Probe targets are **captive portal detection endpoints** — lightweight URLs that OS and browser vendors operate specifically for connectivity checking:

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

**How probing works:**
1. Requests are sent to all endpoints simultaneously
2. The first successful response wins — all remaining requests are cancelled immediately
3. If no response arrives within 5 seconds — status is "Down"
4. Connections are reused between checks (keep-alive) — lower baseline latency makes network degradation more visible, and eliminates measurement noise from TLS handshake variance. If sustained failures are detected, the HTTP session is automatically recreated to recover from stale connections

**Polling:**
- A probe runs every 2 seconds
- Each measurement is stored as a raw value in the database

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
3. If the IP changed, two country services are raced for the new IP
4. Responses are validated: IP must be a valid IPv4 address, country must be exactly 2 uppercase ASCII letters
