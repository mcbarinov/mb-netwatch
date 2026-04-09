# mb-netwatch

macOS internet connection monitor. Tracks latency, VPN status, and public IP at a glance via a menu bar icon.

> **Status:** Under active development.

## What it monitors

Three types of checks run continuously in the background:

- **Latency** — HTTP probes against captive portal endpoints every 2 seconds (first response wins)
- **VPN status** — tunnel interface and routing table detection every 10 seconds
- **Public IP** — address and country code via plain-text IP services every 60 seconds

See [docs/probes.md](docs/probes.md) for detailed algorithms, endpoints, and design rationale.

## CLI commands

- `mb-netwatch probe` — one-shot connectivity probe, print result
- `mb-netwatch probed` — run continuous background measurements
- `mb-netwatch tray` — run menu bar UI process
- `mb-netwatch watch` — live terminal view of measurements
- `mb-netwatch start [probed|tray]` — start processes in the background (no argument = both)
- `mb-netwatch stop [probed|tray]` — stop background processes (no argument = both)

## Architecture

General CLI application architecture patterns are described in [docs/cli-architecture.md](docs/cli-architecture.md). Database schema and storage rules are in [docs/db.md](docs/db.md). Below is the project-specific structure.

### Core (`core/`)

Central application layer. Holds database, business logic, and probe implementations. Consumers never import from `core/` directly — they receive a `Core` instance and access everything through it:

- `core.db` — database (reads and writes)
- `core.config` — application configuration
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

SQLite database at `~/.local/mb-netwatch/netwatch.db` (WAL mode).
See [docs/db.md](docs/db.md) for schema, deduplication strategy, and retention rules.

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
- [mm-clikit](https://github.com/mcbarinov/mm-clikit) — CLI toolkit (Typer enhancements, SQLite, process management)
- [mm-pymac](https://github.com/mcbarinov/mm-pymac) — macOS menu bar app
