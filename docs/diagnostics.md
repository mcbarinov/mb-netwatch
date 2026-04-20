# Diagnostics

> **Source of truth.** This document defines diagnostic behavior. Code must follow these specifications.
> If the code diverges from this document, the code is wrong — update the code, not the doc.

Diagnostics are **on-demand** checks the user invokes by hand when something looks wrong. They differ from probes in three ways:

| | Probes (`core/probes/`) | Diagnostics (`core/diagnostics/`) |
|---|---|---|
| When they run | Continuously, scheduled by `probed` | One-shot, when the user asks |
| Cost | Lightweight by contract | May be heavier — multiple transports, external comparators |
| Where the result goes | SQLite, drives tray/TUI display | Returned to the caller (CLI/TUI), never stored |

A diagnostic does not replace a probe. The probe answers *"is it working right now?"* on a steady cadence so the user can see degradation. The diagnostic answers *"why isn't it working?"* once, when the user has already noticed a problem.

## DNS

Invoked via `mb-netwatch diagnose dns` (alias `mb-netwatch d dns`). The check runs entirely on demand — it does not depend on `probed` being alive, so it works even when the daemon is misbehaving.

### What it tests

Three groups of queries run **in parallel**, all using the same canary record (`A cloudflare.com`) as the steady-state DNS probe:

1. **System resolvers over UDP** — discovered via `scutil --dns` using the same parser as `core/probes/dns.py`. Mirrors what apps on the machine actually use.
2. **System resolvers over TCP** — same resolvers, TCP transport. Surfaces the "UDP/53 filtered but TCP/53 open" failure mode common on hotel and captive networks.
3. **Public resolvers over UDP** — fixed set of `1.1.1.1`, `8.8.8.8`, `9.9.9.9` as a baseline reference. Tells us whether outbound DNS to the wider internet works at all.

All queries share the same per-query timeout (default 2 s, configured by `[probed].dns_timeout`). There are no retries — a single round-trip per (resolver, transport) pair, by design.

### Why public comparators are necessary

Without a baseline, we can only say *"DNS is failing."* With one, we can say *what kind* of failure it is. The matrix of (system result × public result × TCP result) collapses into the verdict table below — the public column is what distinguishes a broken resolver from broken upstream connectivity.

The tradeoff is a small amount of outbound traffic the user did not directly request. Three queries per invocation to widely-used public resolvers is negligible and uncontroversial; the user explicitly opted in by running the command.

### Verdict logic

After the queries finish, the result is matched against a fixed set of patterns. Each pattern produces a stable code (for JSON consumers) and a one-line message (for humans).

| Pattern | Code | Message |
|---|---|---|
| `system_resolvers` empty | `NO_RESOLVERS` | macOS has no active DNS configuration — check the network. |
| All system UDP ok and all public UDP ok | `HEALTHY` | DNS is healthy. |
| All system UDP ok but all public UDP fail | `SYSTEM_OK_PUBLIC_BLOCKED` | Normal on VPN/corporate networks that restrict outbound DNS — not a problem. |
| All system UDP fail and all public UDP fail and not all system TCP ok | `UPSTREAM_DOWN` | Not a DNS problem; upstream connectivity is down. |
| All system UDP fail and all public UDP fail and all system TCP ok | `UDP_BLOCKED` | UDP/53 appears blocked. TCP queries succeed where UDP fails. |
| All system UDP fail and all public UDP ok | `SYSTEM_RESOLVER_BROKEN` | Likely VPN or router DNS issue — flushing the cache will not help. |
| Anything else | (no verdict) | Mixed results — the user reads the tables themselves. |

"All ok" requires a non-empty list where every sample has `error is None`. "All fail" requires a non-empty list where every sample has a non-None error. Partial failures (one of two resolvers down) deliberately do not match any pattern — the verdict engine refuses to guess. A wrong verdict erodes trust faster than no verdict.

### Output

Three resolver tables (system UDP, system TCP, public UDP) followed by the verdict line and a static cheat-sheet of common DNS-fix commands:

1. **Soft flush** — `sudo dscacheutil -flushcache` + `sudo killall -HUP mDNSResponder`. Try first.
2. **Hard restart** — `sudo launchctl kickstart -k system/com.apple.mDNSResponder`. When the soft flush did not help.

The cheat-sheet is presentation only. It is not part of `DnsDiagnosis` and is omitted in `--json` mode (scripted consumers do not need a recall aid).

### What is deliberately not done

- **No automatic execution of fix commands.** Every fix requires `sudo` and the diagnostic stays read-only by design. The cheat-sheet exists to remind the user; the user runs the commands themselves.
- **No retries or TCP fallback inside a query.** Same rationale as the steady-state probe — retries hide the very degradation the diagnostic exists to detect.
- **No IPv6, no DNSSEC, no DoH/DoT, no answer-correctness check.** Same scope boundary as the steady-state probe.
- **No persistence.** The result is returned to the caller and forgotten. Diagnostics are interactive; their value is in the moment.
