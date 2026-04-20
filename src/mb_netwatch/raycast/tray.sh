#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Start Netwatch Tray
# @raycast.mode silent
# @raycast.icon 📶
# @raycast.packageName mb-netwatch
# @raycast.description Start the menu bar tray icon in the background

export PATH="$HOME/.local/bin:$PATH"
mb-netwatch start tray 2>&1
