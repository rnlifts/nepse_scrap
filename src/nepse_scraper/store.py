"""SQLite (source of truth) + CSV export.

Schema
------
prices(symbol, date, price_type, time_frame,
       open, high, low, close, volume, percent_change,
       fetched_at)                       PK = (symbol, date, price_type, time_frame)

runs(run_id INTEGER PK, mode, started_at, finished_at,
     symbols_ok, symbols_failed, rows_written, notes)

`volume` on the NEPSE index is rupee turnover; on individual stocks it is share
count ("Kitta"). It is 0 for index history before 2016-05-29 (source limitation).
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .fetch import FetchResult
from .logging_setup import get_logger

log = get_logger("store")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    symbol         TEXT NOT NULL,
    date           TEXT NOT NULL,
    price_type     TEXT NOT NULL,
    time_frame     TEXT NOT NULL,
    open           REAL,
    high           REAL,
    low            REAL,
    close          REAL,
    volume         REAL,
    percent_change REAL,
    fetched_at     TEXT NOT NULL,
    PRIMARY KEY (symbol, date, price_type, time_frame)
);
CREATE INDEX IF NOT EXISTS ix_prices_symbol_date ON prices(symbol, date);

CREATE TABLE IF NOT EXISTS runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    mode          TEXT,
    started_at    TEXT,
    finished_at   TEXT,
    symbols_ok    INTEGER DEFAULT 0,
    symbols_failed INTEGER DEFAULT 0,
    rows_written  INTEGER DEFAULT 0,
    notes         TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.executescript(_SCHEMA)
        self.db.commit()

    def close(self):
        self.db.close()

    # -- runs bookkeeping ------------------------------------------------
    def start_run(self, mode: str) -> int:
        cur = self.db.execute(
            "INSERT INTO runs(mode, started_at) VALUES (?, ?)", (mode, _now())
        )
        self.db.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, *, ok: int, failed: int, rows: int, notes: str = ""):
        self.db.execute(
            "UPDATE runs SET finished_at=?, symbols_ok=?, symbols_failed=?, "
            "rows_written=?, notes=? WHERE run_id=?",
            (_now(), ok, failed, rows, notes, run_id),
        )
        self.db.commit()

    # -- upsert --------------------------------------------------------
    def upsert(self, result: FetchResult) -> tuple[int, int]:
        """Return (inserted, updated)."""
        fetched_at = _now()
        before = self._count(result.symbol, result.price_type, result.time_frame)
        rows = [
            (
                result.symbol, r["f_date"], result.price_type, result.time_frame,
                r.get("open"), r.get("high"), r.get("low"), r.get("close"),
                r.get("volume"), r.get("percent_change"), fetched_at,
            )
            for r in result.rows
        ]
        self.db.executemany(
            """
            INSERT INTO prices
              (symbol, date, price_type, time_frame,
               open, high, low, close, volume, percent_change, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol, date, price_type, time_frame) DO UPDATE SET
              open=excluded.open, high=excluded.high, low=excluded.low,
              close=excluded.close, volume=excluded.volume,
              percent_change=excluded.percent_change, fetched_at=excluded.fetched_at
            """,
            rows,
        )
        self.db.commit()
        after = self._count(result.symbol, result.price_type, result.time_frame)
        inserted = after - before
        updated = len(rows) - inserted
        return inserted, updated

    def _count(self, symbol, price_type, time_frame) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM prices WHERE symbol=? AND price_type=? AND time_frame=?",
            (symbol, price_type, time_frame),
        ).fetchone()[0]

    def latest_date(self, symbol, price_type, time_frame) -> str | None:
        row = self.db.execute(
            "SELECT MAX(date) FROM prices WHERE symbol=? AND price_type=? AND time_frame=?",
            (symbol, price_type, time_frame),
        ).fetchone()
        return row[0] if row else None

    # -- CSV export --------------------------------------------------
    def export_csv(self, symbol, price_type, time_frame, csv_dir: Path) -> Path:
        csv_dir.mkdir(parents=True, exist_ok=True)
        fp = csv_dir / f"{symbol}_{time_frame}_{price_type}.csv"
        cur = self.db.execute(
            "SELECT date, open, high, low, close, volume, percent_change "
            "FROM prices WHERE symbol=? AND price_type=? AND time_frame=? ORDER BY date",
            (symbol, price_type, time_frame),
        )
        with open(fp, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "open", "high", "low", "close", "volume", "percent_change"])
            w.writerows(cur.fetchall())
        return fp
