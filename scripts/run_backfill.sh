#!/usr/bin/env bash
# One-off: pull full history for every symbol in config/settings.toml.
set -euo pipefail
cd "$(dirname "$0")/.."

export PYTHONPATH=src
# headed Chrome on a headless server -> wrap in a virtual display
if [ -z "${DISPLAY:-}" ] && command -v xvfb-run >/dev/null; then
  exec xvfb-run -a python -m nepse_scraper backfill "$@"
else
  exec python -m nepse_scraper backfill "$@"
fi
