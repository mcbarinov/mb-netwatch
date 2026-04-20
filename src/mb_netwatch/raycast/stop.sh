#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Stop Netwatch
# @raycast.mode silent
# @raycast.icon ⏹
# @raycast.packageName mb-netwatch
# @raycast.description Stop the netwatch daemon and tray

export PATH="$HOME/.local/bin:$PATH"
mb-netwatch stop 2>&1
