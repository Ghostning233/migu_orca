#!/bin/bash
# Playwright chromium wrapper — sets up library path for headless shell.
# This wrapper is auto-generated during Stage 9 browser automation setup.
# Source libraries are extracted from Ubuntu .deb packages and cached under
# /tmp/chromium-libs/.  When system libraries are available (via apt install),
# this wrapper is unnecessary and the standard playwright chromium works directly.

CHROMIUM_LIBS="/tmp/chromium-libs/usr/lib/x86_64-linux-gnu:/tmp/chromium-libs/lib/x86_64-linux-gnu"
CHROMIUM_BIN="$HOME/.cache/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-linux64/chrome-headless-shell"

if [ -d /tmp/chromium-libs ] && [ -f "$CHROMIUM_BIN" ]; then
    export LD_LIBRARY_PATH="${CHROMIUM_LIBS}:${LD_LIBRARY_PATH}"
    exec "$CHROMIUM_BIN" "$@"
else
    exec "$HOME/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome" "$@"
fi
