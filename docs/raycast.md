# Raycast Integration

[Script Commands](https://github.com/raycast/script-commands) ship with `mb-netwatch` so you can trigger probes and manage the background processes from Raycast's search bar without a terminal.

## Available Commands

| Command | Description |
|---|---|
| Netwatch Probe | Run a one-shot connectivity probe (warm/cold latency, VPN, IP, DNS) |
| Start Netwatch | Start the probed daemon and tray in the background |
| Stop Netwatch | Stop the probed daemon and tray |

`Netwatch Probe` runs in `fullOutput` mode — the five-line result appears in a Raycast popup, Esc closes it. The other commands run silently with a brief HUD notification.

## Setup (end users)

1. Install `mb-netwatch` via `uv tool install mb-netwatch` (ensures the binary lands in `~/.local/bin/`).
2. Run:
   ```
   mb-netwatch raycast install
   ```
   This writes the scripts to `<data_dir>/raycast/` (default `~/.local/mb-netwatch/raycast/`) with the absolute binary path and `--data-dir` baked in. Pass a positional argument to choose a different directory, and `--force` to overwrite existing files.
3. In Raycast: open **Settings → Extensions → Script Commands → Add Directories**, then select the path printed by the install command. This is a one-time step.

After upgrades (`uv tool upgrade mb-netwatch`), re-run `mb-netwatch raycast install --force` to refresh the scripts. Raycast automatically picks up changes in the existing directory — no additional action needed.

## Setup (contributors)

The source-of-truth scripts live at `src/mb_netwatch/raycast/*.sh` inside the repo and are shipped as package data. On a dev machine point Raycast directly at that directory — edits are picked up live without re-running `raycast install`. The scripts rely on `mb-netwatch` being on `PATH` (via `uv tool install mb-netwatch` from the repo or a published version).
