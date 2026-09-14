"""Push scraped data into a Google Sheet via a service account.

One-time setup: see deploy/GOOGLE_SHEETS.md.

Design: each configured symbol gets its own worksheet tab, which is fully
rewritten from the SQLite store on every sync. That's simple, always
consistent with the DB (no partial-write drift), and cheap in API calls
(one values.update per symbol, not one per row) — fine for a handful to a
few dozen tabs. Don't point this at all 376 symbols; Sheets isn't built for
that many tabs and you'd burn through API quota for no benefit — pick your
watchlist in `config/settings.toml` -> `[sheets] sync_symbols`.
"""
from __future__ import annotations

import time
from pathlib import Path

from .config import Config
from .logging_setup import get_logger
from .store import Store

log = get_logger("sheets")

_HEADER = ["date", "open", "high", "low", "close", "volume", "percent_change"]


def _client(credentials_path: Path):
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(str(credentials_path), scopes=scopes)
    return gspread.authorize(creds)


def sync(cfg: Config, symbols: list[str] | None = None) -> tuple[int, int]:
    """Push each symbol's full series to its own worksheet tab.

    Returns (ok, failed) counts. Never raises — a Sheets outage should not
    fail the scrape itself; callers just log the counts.
    """
    if not cfg.get("sheets", "enabled"):
        log.info("sheets sync disabled ([sheets] enabled=false) -- skipping")
        return 0, 0

    creds_path = cfg.path("sheets", "credentials_path")
    if not creds_path.exists():
        log.error(
            "credentials file not found: %s -- see deploy/GOOGLE_SHEETS.md", creds_path
        )
        return 0, 1

    sheet_id = cfg.get("sheets", "spreadsheet_id")
    if not sheet_id:
        log.error("[sheets] spreadsheet_id is empty in settings.toml")
        return 0, 1

    symbols = symbols or cfg.get("sheets", "sync_symbols")
    if not symbols:
        log.info("[sheets] sync_symbols is empty -- nothing to push")
        return 0, 0

    pause = cfg.get("sheets", "pause_s")
    price_type = cfg.get("source", "price_type")
    time_frame = cfg.get("source", "time_frame")

    try:
        gc = _client(creds_path)
        sh = gc.open_by_key(sheet_id)
    except Exception as e:  # noqa: BLE001
        log.error("could not open the spreadsheet: %s", e)
        return 0, len(symbols)

    store = Store(cfg.path("store", "db_path"))
    ok = failed = 0
    try:
        for i, sym in enumerate(symbols, 1):
            try:
                rows = store.db.execute(
                    "SELECT date, open, high, low, close, volume, percent_change "
                    "FROM prices WHERE symbol=? AND price_type=? AND time_frame=? "
                    "ORDER BY date",
                    (sym, price_type, time_frame),
                ).fetchall()
                if not rows:
                    log.warning(
                        "%s: nothing in the DB yet -- skipped (run backfill first)", sym
                    )
                    failed += 1
                    continue

                try:
                    ws = sh.worksheet(sym)
                except Exception:  # noqa: BLE001  (gspread.WorksheetNotFound)
                    ws = sh.add_worksheet(title=sym, rows=len(rows) + 10, cols=len(_HEADER))

                ws.clear()
                ws.update([_HEADER] + [list(r) for r in rows], value_input_option="RAW")
                log.info("[%d/%d] %s -> tab '%s' (%d rows)", i, len(symbols), sym, sym, len(rows))
                ok += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                log.error("[%d/%d] %s FAILED: %s", i, len(symbols), sym, e)
            if i < len(symbols):
                time.sleep(pause)
    finally:
        store.close()

    log.info("sheets sync done: ok=%d failed=%d", ok, failed)
    return ok, failed
