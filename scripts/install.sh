#!/usr/bin/env bash
# Install the cura CLI system-wide by symlinking to /usr/local/bin.
# Usage: ./scripts/install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CURA_SCRIPT="$PROJECT_ROOT/cura"
INSTALL_PATH="/usr/local/bin/cura"

if [ ! -f "$CURA_SCRIPT" ]; then
    echo "ERROR: cura script not found at $CURA_SCRIPT"
    exit 1
fi

if [ -L "$INSTALL_PATH" ]; then
    existing=$(readlink "$INSTALL_PATH")
    if [ "$existing" = "$CURA_SCRIPT" ]; then
        echo "cura is already installed at $INSTALL_PATH"
        exit 0
    fi
    echo "Updating existing symlink (was: $existing)"
fi

echo "Installing cura → $INSTALL_PATH"
sudo ln -sf "$CURA_SCRIPT" "$INSTALL_PATH"
echo "Done. You can now run 'cura' from anywhere."
