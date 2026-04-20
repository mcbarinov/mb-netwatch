#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Start Netwatch
# @raycast.mode silent
# @raycast.icon ▶️
# @raycast.packageName mb-netwatch
# @raycast.description Start the netwatch daemon and tray in the background

export PATH="$HOME/.local/bin:$PATH"
mb-netwatch start 2>&1
