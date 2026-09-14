"""Prune old raw-JSON dumps and log files so disk use doesn't grow forever.

Called once at the start of backfill/daily runs. Cheap (a directory listing),
safe (only deletes things clearly older than the configured window).
"""
from __future__ import annotations

import time
from pathlib import Path

from .logging_setup import get_logger

log = get_logger("retention")


def prune_raw(raw_dir: Path, retention_days: int) -> int:
    if not raw_dir.exists() or retention_days <= 0:
        return 0
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for day_dir in raw_dir.iterdir():
        if not day_dir.is_dir():
            continue
        try:
            if day_dir.stat().st_mtime < cutoff:
                for f in day_dir.glob("*"):
                    f.unlink(missing_ok=True)
                day_dir.rmdir()
                removed += 1
        except OSError as e:  # noqa: BLE001
            log.debug("could not prune %s: %s", day_dir, e)
    if removed:
        log.info("pruned %d raw/ folder(s) older than %d days", removed, retention_days)
    return removed


def prune_logs(log_dir: Path, retention_days: int) -> int:
    if not log_dir.exists() or retention_days <= 0:
        return 0
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for f in log_dir.glob("nepse-*.log*"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError as e:  # noqa: BLE001
            log.debug("could not prune %s: %s", f, e)
    if removed:
        log.info("pruned %d log file(s) older than %d days", removed, retention_days)
    return removed
