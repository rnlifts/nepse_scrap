"""Console + rotating-file logging with a compact, readable format.

Every run logs to both stdout (so `journalctl` / cron mail catches it) and
logs/nepse-YYYY-MM-DD.log.
"""
from __future__ import annotations

import logging
import sys
from datetime import date
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FMT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> logging.Logger:
    root = logging.getLogger("nepse")
    if root.handlers:  # already configured
        return root
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    con = logging.StreamHandler(sys.stdout)
    con.setFormatter(logging.Formatter(_FMT, _DATEFMT))
    root.addHandler(con)

    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            log_dir / f"nepse-{date.today():%Y-%m-%d}.log",
            maxBytes=5_000_000, backupCount=10, encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter(_FMT, _DATEFMT))
        root.addHandler(fh)

    # Playwright is chatty at DEBUG; keep it quiet unless we ask.
    logging.getLogger("playwright").setLevel(logging.WARNING)
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"nepse.{name}")
