#!/bin/bash
# Setup browser dependencies for Playwright / Chromium browser automation tests.
#
# This script attempts three strategies in order:
#   1. Install system packages via apt (requires sudo).
#   2. Download and extract .deb packages locally to /tmp/chromium-libs/
#      (no sudo required, works without root).
#   3. Print fallback instructions.
#
# After running this script, browser tests should pass:
#   uv run pytest tests/browser/ -v

set -euo pipefail

echo "=== MiGuOrca Stage 9: Browser Dependency Setup ==="

echo "=> Ensuring Playwright Chromium browser binary is installed..."
uv run playwright install chromium

# --- Strategy 1: apt with sudo ------------------------------------------------
if command -v sudo &>/dev/null && sudo -n true 2>/dev/null; then
    echo "=> Trying apt install (sudo available)..."
    if sudo apt-get install -y libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 \
        libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
        libatspi2.0-0 2>/dev/null; then
        echo "=> System dependencies installed via apt."
        exit 0
    fi
    echo "=> apt install failed or incomplete, trying local extraction..."
fi

# --- Strategy 2: local .deb extraction ---------------------------------------
LIBS_DIR="/tmp/chromium-libs"
DEBS_DIR="$(mktemp -d /tmp/chromium-debs.XXXXXX)"
trap 'rm -rf "${DEBS_DIR}"' EXIT
echo "=> Downloading and extracting .deb packages to ${LIBS_DIR}..."

mkdir -p "${LIBS_DIR}"

# List mirrors the playwright install-deps package set for Ubuntu Jammy.
PACKAGES=(
    libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2
    libatspi2.0-0
)

DOWNLOADED=0
for pkg in "${PACKAGES[@]}"; do
    if (cd "${DEBS_DIR}" && apt download "$pkg" 2>/dev/null); then
        for deb in "${DEBS_DIR}"/"${pkg}"*.deb; do
            [ -f "$deb" ] && dpkg -x "$deb" "${LIBS_DIR}" 2>/dev/null
        done
        DOWNLOADED=$((DOWNLOADED + 1))
    fi
done

if [ "$DOWNLOADED" -gt 0 ]; then
    echo "=> Extracted ${DOWNLOADED} packages to ${LIBS_DIR}."
    echo "=> LD_LIBRARY_PATH will be set automatically by browser test conftest."
    echo "=> Extracted library paths:"
    echo "   ${LIBS_DIR}/usr/lib/x86_64-linux-gnu"
    echo "   ${LIBS_DIR}/lib/x86_64-linux-gnu"
else
    echo "=> No .deb packages could be downloaded."
fi

# --- Strategy 3: manual fallback ---------------------------------------------
echo ""
echo "=== Setup complete ==="
echo ""
echo "If browser tests still fail, install the dependencies manually:"
echo "  sudo apt-get install libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 \\"
echo "    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 \\"
echo "    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \\"
echo "    libatspi2.0-0"
echo ""
echo "Or run: uv run playwright install-deps chromium"
