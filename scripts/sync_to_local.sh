#!/usr/bin/env bash
# Push the freshly-scraped data OFF the VPS to your local machine.
# Pick ONE strategy and configure it in .env (see .env.example).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

STRATEGY="${SYNC_STRATEGY:-none}"

case "$STRATEGY" in
  tailscale-rsync)
    # Local machine reachable over your tailnet. No public ports.
    #   SYNC_DEST=user@your-laptop:/home/user/nepse-data/
    rsync -avz --partial data/ "${SYNC_DEST:?set SYNC_DEST in .env}"
    ;;

  git)
    # Commit the CSV + DB into a private data repo, local machine pulls.
    #   requires: git remote 'origin' already set on ./data as its own repo,
    #             or data/ symlinked into a checked-out data repo.
    git -C data add -A
    git -C data commit -m "data: $(date -Is)" --quiet || echo "nothing to commit"
    git -C data push --quiet
    ;;

  rclone)
    # Push to S3 / Backblaze / Drive; local machine runs `rclone sync` the other way.
    #   SYNC_DEST=myremote:nepse-data
    rclone sync data/ "${SYNC_DEST:?set SYNC_DEST in .env}" --transfers 4
    ;;

  none)
    echo "SYNC_STRATEGY=none — data stays on the VPS only. Set one in .env."
    ;;

  *)
    echo "unknown SYNC_STRATEGY: $STRATEGY" >&2; exit 1
    ;;
esac
