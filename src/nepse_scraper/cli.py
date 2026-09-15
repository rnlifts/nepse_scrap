"""Command-line entry point.

    python -m nepse_scraper refresh-symbols    # pull the ~700-ticker list from the site
    python -m nepse_scraper backfill           # full history, all configured symbols
    python -m nepse_scraper daily              # trailing window, upsert
    python -m nepse_scraper export             # (re)write CSVs from the DB
    python -m nepse_scraper status             # what's in the DB right now
    python -m nepse_scraper sync-sheets        # push [sheets] sync_symbols to Google Sheets

Flags: --symbols NEPSE,NABIL   --start 2015-01-01   --end 2026-09-10
       --time-frame daily|weekly   --price-type unadjusted|adjusted

--symbols also accepts "ALL" (every equity + index ticker, from
config/symbols.csv — run refresh-symbols first) or "ALL:<type>" for just
one class (equity, index, promoter, bond, fund).
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta

from .config import load_config
from .fetch import Fetcher, write_raw
from .logging_setup import get_logger, setup_logging
from .retention import prune_logs, prune_raw
from .store import Store
from .symbols import add_dead, resolve_symbol_list, save_csv


def _args(argv):
    p = argparse.ArgumentParser(prog="nepse_scraper")
    p.add_argument(
        "command",
        choices=["backfill", "daily", "export", "status", "refresh-symbols", "sync-sheets"],
    )
    p.add_argument("--symbols", help="comma-separated, or ALL / ALL:<type>; overrides settings.toml")
    p.add_argument("--start", help="YYYY-MM-DD (backfill only)")
    p.add_argument("--end", help="YYYY-MM-DD")
    p.add_argument("--time-frame", dest="time_frame", choices=["daily", "weekly"])
    p.add_argument("--price-type", dest="price_type", choices=["unadjusted", "adjusted"])
    p.add_argument("--no-sheets", action="store_true", help="skip the automatic post-run Google Sheets sync")
    return p.parse_args(argv)


def _resolve(cfg, a):
    spec = [s.strip() for s in a.symbols.split(",")] if a.symbols else cfg.symbols
    symbols_csv = cfg.path("symbols", "csv_path")
    dead_path = cfg.path("symbols", "dead_path")
    symbols = resolve_symbol_list(spec, symbols_csv, dead_path)
    time_frame = a.time_frame or cfg.get("source", "time_frame")
    price_type = a.price_type or cfg.get("source", "price_type")
    return symbols, time_frame, price_type


def cmd_refresh_symbols(cfg):
    log = get_logger("symbols")
    symbols_csv = cfg.path("symbols", "csv_path")
    with Fetcher(cfg) as fetcher:
        entries = fetcher.list_symbols()
    if not entries:
        log.error("could not read the symbol dropdown — site layout may have changed")
        return 1
    fp = save_csv(entries, symbols_csv)
    rows = resolve_symbol_list(["ALL"], symbols_csv)
    log.info("wrote %s: %d total tickers, %d equity+index (usable as --symbols ALL)",
              fp, len(entries), len(rows))
    return 0


def cmd_status(cfg):
    store = Store(cfg.path("store", "db_path"))
    try:
        rows = store.db.execute(
            "SELECT symbol, price_type, time_frame, COUNT(*), MIN(date), MAX(date) "
            "FROM prices GROUP BY symbol, price_type, time_frame ORDER BY symbol"
        ).fetchall()
        if not rows:
            print("database is empty — run 'backfill' first")
            return
        print(f"{'symbol':<12}{'type':<12}{'tf':<8}{'rows':>7}  {'from':<12}{'to':<12}")
        for s, pt, tf, n, lo, hi in rows:
            print(f"{s:<12}{pt:<12}{tf:<8}{n:>7}  {lo:<12}{hi:<12}")
        last = store.db.execute(
            "SELECT mode, started_at, finished_at, symbols_ok, symbols_failed, rows_written "
            "FROM runs ORDER BY run_id DESC LIMIT 5"
        ).fetchall()
        print("\nlast runs:")
        for m, st, fi, ok, fa, rw in last:
            print(f"  {st}  {m:<9} ok={ok} failed={fa} rows={rw} finished={fi or '(unfinished)'}")
    finally:
        store.close()


def cmd_sync_sheets(cfg):
    from .sheets import sync

    ok, failed = sync(cfg)
    return 0 if failed == 0 else 1


def cmd_export(cfg):
    log = get_logger("export")
    store = Store(cfg.path("store", "db_path"))
    csv_dir = cfg.path("store", "csv_dir")
    try:
        combos = store.db.execute(
            "SELECT DISTINCT symbol, price_type, time_frame FROM prices"
        ).fetchall()
        for s, pt, tf in combos:
            fp = store.export_csv(s, pt, tf, csv_dir)
            n = store._count(s, pt, tf)
            log.info("wrote %s (%d rows)", fp, n)
    finally:
        store.close()


def _run_fetch(cfg, mode, symbols, time_frame, price_type, start, end, sync_sheets_after=True):
    log = get_logger(mode)
    store = Store(cfg.path("store", "db_path"))
    run_id = store.start_run(mode)
    pause = cfg.get("fetch", "per_request_pause_s")
    keep_raw = cfg.get("store", "keep_raw")
    raw_dir = cfg.path("store", "raw_dir")
    csv_dir = cfg.path("store", "csv_dir")

    prune_raw(raw_dir, cfg.get("store", "raw_retention_days"))
    prune_logs(cfg.path("logging", "dir"), cfg.get("logging", "retention_days"))

    ok = failed = total_rows = 0
    newly_dead: list[str] = []
    t_start = time.monotonic()
    log.info(
        "=== %s START  symbols=%s  range=%s..%s  tf=%s  type=%s ===",
        mode.upper(), ",".join(symbols), start, end, time_frame, price_type,
    )
    try:
        with Fetcher(cfg) as fetcher:
            for i, sym in enumerate(symbols, 1):
                s_lo = start
                if mode == "daily":
                    look = cfg.get("daily", "lookback_days")
                    s_lo = (date.today() - timedelta(days=look)).isoformat()
                try:
                    res = fetcher.fetch(
                        sym, s_lo, end, price_type=price_type, time_frame=time_frame
                    )
                    if keep_raw:
                        write_raw(res, raw_dir)
                    ins, upd = store.upsert(res)
                    fp = store.export_csv(sym, price_type, time_frame, csv_dir)
                    total_rows += ins + upd
                    ok += 1
                    span = res.span
                    log.info(
                        "[%d/%d] %s  fetched=%d  +%d new / ~%d updated  span=%s..%s  "
                        "(%.1fs, %d attempt%s)  -> %s",
                        i, len(symbols), sym, len(res.rows), ins, upd,
                        span[0] if span else "?", span[1] if span else "?",
                        res.elapsed_s, res.attempts, "" if res.attempts == 1 else "s",
                        fp.name,
                    )
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    log.error("[%d/%d] %s FAILED: %s", i, len(symbols), sym, e)
                    if "empty data array" in str(e).lower():
                        newly_dead.append(sym)
                if i < len(symbols):
                    time.sleep(pause)
    except Exception as e:  # noqa: BLE001  (browser/Cloudflare level failure)
        log.error("run aborted: %s", e)
        store.finish_run(run_id, ok=ok, failed=failed, rows=total_rows, notes=f"aborted: {e}")
        store.close()
        if newly_dead:
            add_dead(cfg.path("symbols", "dead_path"), newly_dead)
        return 2

    if newly_dead:
        add_dead(cfg.path("symbols", "dead_path"), newly_dead)
        log.info(
            "recorded %d symbol(s) as dead (no data) -> %s — 'ALL' skips them next time",
            len(newly_dead), cfg.path("symbols", "dead_path"),
        )

    dt = time.monotonic() - t_start
    store.finish_run(run_id, ok=ok, failed=failed, rows=total_rows)
    store.close()
    log.info(
        "=== %s DONE  ok=%d  failed=%d  rows=%d  in %.1fs (%.1f min) ===",
        mode.upper(), ok, failed, total_rows, dt, dt / 60,
    )

    if sync_sheets_after and cfg.get("sheets", "enabled"):
        from .sheets import sync as sheets_sync

        sheets_sync(cfg)

    return 0 if failed == 0 else 1


def main(argv=None):
    a = _args(argv or sys.argv[1:])
    cfg = load_config()
    setup_logging(cfg.get("logging", "level"), cfg.path("logging", "dir"))

    if a.command == "status":
        return cmd_status(cfg)
    if a.command == "export":
        return cmd_export(cfg)
    if a.command == "refresh-symbols":
        return cmd_refresh_symbols(cfg)
    if a.command == "sync-sheets":
        return cmd_sync_sheets(cfg)

    symbols, time_frame, price_type = _resolve(cfg, a)
    end = a.end or date.today().isoformat()
    sync_sheets_after = not a.no_sheets
    if a.command == "backfill":
        start = a.start or cfg.get("source", "backfill_start")
        return _run_fetch(cfg, "backfill", symbols, time_frame, price_type, start, end, sync_sheets_after)
    if a.command == "daily":
        return _run_fetch(cfg, "daily", symbols, time_frame, price_type, None, end, sync_sheets_after)


if __name__ == "__main__":
    sys.exit(main() or 0)
