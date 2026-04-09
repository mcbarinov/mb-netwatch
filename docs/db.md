# Database Schema

> **Source of truth.** This document defines the database schema and storage rules.
> Code must follow these specifications. If the code diverges, the code is wrong.

SQLite database stored at `<data_dir>/netwatch.db`. All timestamps are UTC Unix seconds (REAL).

## Tables

### latency_checks

Every probe inserts a new row. No deduplication — each measurement is unique.

| Column           | Type | Nullable | Description                                   |
|------------------|------|----------|-----------------------------------------------|
| ts               | REAL | NO       | Probe timestamp                               |
| latency_ms       | REAL | YES      | Round-trip time in ms; NULL when all endpoints failed |
| winner_endpoint  | TEXT | YES      | URL that responded first; NULL when down       |

Indexes: `ts`.

### vpn_checks

| Column      | Type    | Nullable | Description                              |
|-------------|---------|----------|------------------------------------------|
| created_at  | REAL    | NO       | When this state first appeared            |
| updated_at  | REAL    | NO       | Last time this state was confirmed        |
| is_active   | INTEGER | NO       | 1 = VPN tunnel active, 0 = inactive      |
| tunnel_mode | TEXT    | NO       | "full", "split", or "unknown"            |
| provider    | TEXT    | YES      | VPN app name; NULL when not identified    |

Indexes: `created_at`, `updated_at`.

### ip_checks

| Column       | Type | Nullable | Description                                      |
|--------------|------|----------|--------------------------------------------------|
| created_at   | REAL | NO       | When this (ip, country_code) pair first appeared  |
| updated_at   | REAL | NO       | Last time this pair was confirmed                 |
| ip           | TEXT | YES      | Public IPv4 address; NULL when all lookups failed |
| country_code | TEXT | YES      | 2-letter ISO country code; NULL when lookup failed|

Indexes: `created_at`, `updated_at`.

## Deduplication (vpn_checks, ip_checks)

These two tables use **upsert deduplication** to avoid storing identical consecutive rows.

On each check the daemon compares the new result with the latest row (by `updated_at DESC`):
- **Same result** — only `updated_at` is bumped to the current timestamp. No new row.
- **Different result** — a new row is inserted with `created_at = updated_at = now`.

Comparison fields:
- `vpn_checks`: `(is_active, tunnel_mode, provider)`
- `ip_checks`: `(ip, country_code)`

NULL values are treated as equal to NULL for comparison purposes.

**Why:** VPN state changes rarely (minutes to hours), IP changes even less often. Without deduplication, 30 days of 10-second VPN checks would produce ~260k rows of mostly identical data. With deduplication, it produces one row per state change — typically single digits per day.

### Query implications

- `fetch_latest` orders by `updated_at DESC` — returns the most recently confirmed state.
- `fetch_since` filters on `created_at > cursor` — returns only genuine state changes, not re-confirmations.
- `purge` deletes where `updated_at < cutoff` — a long-lived unchanged state survives as long as it's being confirmed.

## Retention

Old rows are purged periodically (default: every hour). Configurable via `retention_days` (default: 30). For `vpn_checks` and `ip_checks`, retention is based on `updated_at`, not `created_at` — a row that has been continuously confirmed won't be purged even if it was first created long ago.
