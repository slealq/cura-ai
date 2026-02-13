#!/usr/bin/env bash
#
# Configure Git to use the project's .githooks directory.
# Run once after cloning the repo.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Configuring git hooks path to .githooks/ ..."
git -C "$REPO_ROOT" config core.hooksPath .githooks

# Ensure hooks are executable
chmod +x "$REPO_ROOT"/.githooks/*

echo "Done. Git hooks are active."
echo ""
echo "Protected branches: master, dev (no direct pushes)"
echo "Use personal branches: u/<your-name>/feature-name"
