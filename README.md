# mb-netwatch

macOS internet connection monitor. Tracks latency, VPN status, and public IP at a glance via a menu bar icon.

> **Status:** Under active development.

## What it monitors

Three types of checks run continuously in the background:

- **Latency** — HTTP probe every 2 seconds
- **VPN status** — tunnel detection every 10 seconds
- **Public IP** — IP address and country every 60 seconds

### Latency

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

### VPN status

Detects VPN state every 10 seconds and stores only information that is directly useful for end users:

- **Active/inactive** — whether traffic is currently routed through a tunnel interface
- **Tunnel mode** — full tunnel (all traffic via VPN) vs split tunnel (only part of traffic via VPN)
- **Provider (best effort)** — VPN app name when it can be identified with sufficient confidence; otherwise `NULL`

#### How VPN detection works

The detector uses a simple priority-based pipeline:

1. **Detect tunnel presence**
   - Find active `tun*`/`utun*` interface with IPv4 address.
   - If no tunnel interface is found, VPN is considered inactive.
2. **Detect tunnel mode**
   - Parse `netstat -rn -f inet`.
   - Full tunnel if default route is via tunnel, or if OpenVPN-style `0/1` + `128.0/1` routes are via tunnel.
   - Otherwise split tunnel.
   - If routing cannot be parsed, mode is `unknown`.
3. **Detect provider**
   - Parse `scutil --nc list`.
   - If a service with `(Connected)` status is found, use its name as provider.
   - Otherwise `NULL`.

### Public IP

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

## CLI commands

- `mb-netwatch probe` — one-shot connectivity probe, print result
- `mb-netwatch probed` — run continuous background measurements
- `mb-netwatch tray` — run menu bar UI process
- `mb-netwatch watch` — live terminal view of measurements
- `mb-netwatch start [probed|tray]` — start processes in the background (no argument = both)
- `mb-netwatch stop [probed|tray]` — stop background processes (no argument = both)

## Architecture

### Core (`core/`)

Central application layer. Holds database, business logic, and probe implementations. Consumers never import from `core/` directly — they receive a `Core` instance and access everything through it:

- `core.db` — database (reads and writes)
- `core.cfg` — application configuration
- `core.service` — business logic (running probes, storing results)

### Consumers

Three independent consumers of `Core`:

- **CLI** (`cli/`) — command-line interface. Each command receives `Core` and `Output` via `CoreContext`.
- **Daemon** (`daemon.py`) — long-running background process. Orchestrates scheduling (loops, timers, signals) and delegates all probe/store logic to `core.service`.
- **Tray** (`tray.py`) — macOS menu bar UI. Polls `core.db` for latest results and updates the icon.

### Processes

Two long-running processes in normal operation:

- **probed** (`mb-netwatch probed`) — runs the daemon; measures latency every 2 s, VPN status every 10 s, public IP every 60 s; writes to SQLite via `core.service`.
- **tray** (`mb-netwatch tray`) — UI only; reads latest samples from SQLite via `core.db`, updates menu bar icon and dropdown.

The tray must not perform network probing directly. This separation keeps UI responsive and simplifies debugging.

## Storage

SQLite database at `~/.local/mb-netwatch/netwatch.db`.
Journal mode: WAL (concurrent reads while probed writes).

### Schema

```sql
CREATE TABLE latency_checks (
    ts               REAL  NOT NULL,  -- UTC Unix timestamp (seconds since epoch)
    latency_ms       REAL,            -- winning request latency; NULL when all endpoints failed
    winner_endpoint  TEXT              -- URL that responded first; NULL when down
);
CREATE INDEX idx_latency_checks_ts ON latency_checks(ts);

CREATE TABLE vpn_checks (
    ts            REAL     NOT NULL,  -- UTC Unix timestamp (seconds since epoch)
    is_active     INTEGER  NOT NULL,  -- 1 = VPN active, 0 = inactive
    tunnel_mode   TEXT     NOT NULL,  -- "full", "split", or "unknown"
    provider      TEXT                -- VPN app name, NULL when not identified reliably
);
CREATE INDEX idx_vpn_checks_ts ON vpn_checks(ts);

CREATE TABLE ip_checks (
    ts            REAL  NOT NULL,  -- UTC Unix timestamp (seconds since epoch)
    ip            TEXT,            -- public IPv4 address; NULL when all lookups failed
    country_code  TEXT             -- 2-letter ISO country code; NULL when lookup failed
);
CREATE INDEX idx_ip_checks_ts ON ip_checks(ts);
```

Retention: raw rows kept for 30 days, older rows purged periodically by probed.

## Configuration

Optional TOML config at `~/.local/mb-netwatch/config.toml`. The file is not created automatically — create it only if you want to override defaults. All keys are optional — only specify what you want to change.

```toml
[probed]
latency_interval = 2.0   # seconds between latency probes (default: 2.0)
vpn_interval = 10.0      # seconds between VPN status checks (default: 10.0)
ip_interval = 60.0       # seconds between public IP lookups (default: 60.0)
purge_interval = 3600.0  # seconds between old-data purge runs (default: 3600.0)
latency_timeout = 5.0    # HTTP timeout for latency probes (default: 5.0)
ip_timeout = 5.0         # HTTP timeout for IP/country lookups (default: 5.0)
retention_days = 30      # days to keep raw rows before purging (default: 30)

[tray]
poll_interval = 2.0      # seconds between tray DB polls (default: 2.0)
ok_threshold_ms = 300    # latency below this → OK (default: 300)
slow_threshold_ms = 800  # latency below this → SLOW, at or above → BAD (default: 800)
stale_threshold = 10.0   # seconds before data is considered stale (default: 10.0)

[watch]
poll_interval = 0.5      # seconds between terminal view DB polls (default: 0.5)
```

The menu bar shows a fixed-width 3-character title: 2-letter country code + status symbol (`●` OK / `◐` SLOW / `○` BAD / `✕` DOWN), e.g. `US●`. Click the menu bar icon to see the exact latency in the dropdown. If probed stops writing data, the symbol changes to `–` (en dash) after `stale_threshold` seconds (default 10). While waiting for the first data, a middle dot `·` is displayed.

## Installation

```
uv tool install mb-netwatch
mb-netwatch start
```

## Tech stack

- Python 3.14
- [aiohttp](https://docs.aiohttp.org/) — HTTP probes
- [psutil](https://github.com/giampaolo/psutil) — network interface inspection for VPN detection
- [mm-pymac](https://github.com/mcbarinov/mm-pymac) — macOS menu bar app
