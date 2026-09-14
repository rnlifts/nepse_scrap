#!/usr/bin/env bash
# Daily incremental pull + sync to your local machine.
# Invoked by systemd timer / cron after NEPSE closes.
set -euo pipefail
cd "$(dirname "$0")/.."

export PYTHONPATH=src
LOG="logs/daily-$(date +%F).log"

run() {
  if [ -z "${DISPLAY:-}" ] && command -v xvfb-run >/dev/null; then
    xvfb-run -a python -m nepse_scraper daily "$@"
  else
    python -m nepse_scraper daily "$@"
  fi
}

echo "==== $(date -Is) daily run ====" >> "$LOG"
if run "$@" >> "$LOG" 2>&1; then
  status=ok
else
  status=FAILED
fi
echo "==== $(date -Is) fetch $status ====" >> "$LOG"

# hand the data to the local machine (see scripts/sync_to_local.sh)
if [ -x scripts/sync_to_local.sh ]; then
  scripts/sync_to_local.sh >> "$LOG" 2>&1 || echo "sync failed" >> "$LOG"
fi

[ "$status" = ok ]
