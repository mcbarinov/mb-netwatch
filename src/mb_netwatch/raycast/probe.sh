#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Netwatch Probe
# @raycast.mode fullOutput
# @raycast.icon 📡
# @raycast.packageName mb-netwatch
# @raycast.description Run a one-shot connectivity probe (warm/cold latency, VPN, IP, DNS)

export PATH="$HOME/.local/bin:$PATH"
mb-netwatch probe 2>&1
