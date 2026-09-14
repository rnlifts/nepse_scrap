# nepse-data

Scrapes NEPSE historical **OHLC + volume** from
[nepsealpha.com/nepse-data](https://nepsealpha.com/nepse-data) into a local
SQLite DB + CSV files, and keeps it current with a daily post-market run.

Tracks any ticker nepsealpha.com knows about — the NEPSE index, individual
stocks (`NABIL`, `ADBL`, ...), and sector indices (`BANKING`, `HYDROPOWER`,
...). Add symbols in `config/settings.toml` -> `[symbols] list`, or pass
`--symbols` on the command line — the fetch path is identical for all of them.

## What you get

```
data/
  nepse.db                              SQLite, source of truth
  csv/NEPSE_daily_unadjusted.csv        date,open,high,low,close,volume,percent_change
  raw/2026-09-10/NEPSE_daily_unadjusted.json
```

The NEPSE index history runs from **1997-07-20** to present (~6,600 daily rows).
`volume` (rupee turnover for the index) is only populated by the source from
**2016-05-29** onward; earlier rows have `volume = 0` but full OHLC.

## How it works

nepsealpha.com is behind Cloudflare and its API wants a browser session, so the
scraper drives **real Google Chrome** via Playwright: it loads the page, lets
Cloudflare clear, then calls the data endpoint with an in-page `fetch()`. One
request returns the entire date range as JSON — no pagination. A full index
pull takes ~10 seconds.

Plain `requests`/`curl` do **not** work (Cloudflare 403 / Laravel 419).

## Quick start (local, Windows or Linux)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      Linux:  . .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # or rely on system Chrome (channel="chrome")

set PYTHONPATH=src                    # Windows;  export PYTHONPATH=src on Linux
python -m nepse_scraper backfill      # full history
python -m nepse_scraper status        # what's in the DB
python -m nepse_scraper daily         # trailing-window refresh (idempotent)
```

## Commands

| command           | does                                                              |
|-------------------|--------------------------------------------------------------------|
| `refresh-symbols` | pull the full ticker list (~730) from the site's own dropdown, classify & save to `config/symbols.csv` |
| `backfill`        | full history for every configured symbol (`--start` to override) |
| `daily`           | re-pull the last N days (`[daily] lookback_days`) and upsert     |
| `export`          | rewrite all CSVs from the DB                                     |
| `status`          | rows / date span per symbol + last 5 run outcomes               |

Flags: `--symbols NEPSE,NABIL` · `--start 2015-01-01` · `--end 2026-09-10` ·
`--time-frame daily|weekly` · `--price-type unadjusted|adjusted`

### Tracking more than a handful of symbols

```bash
python -m nepse_scraper refresh-symbols        # writes config/symbols.csv (~730 tickers)
python -m nepse_scraper backfill --symbols ALL          # every equity + index (~410)
python -m nepse_scraper backfill --symbols ALL:equity   # just the 393 ordinary stocks
python -m nepse_scraper backfill --symbols ALL:index    # just the 17 sector/composite indices
```

`config/symbols.csv` tags each ticker `equity` / `index` / `promoter` /
`bond` / `fund` (guessed from its label on the site — promoter shares,
debentures and mutual-fund units aren't ordinary stock prices, so `ALL`
skips them by default). Re-run `refresh-symbols` occasionally to pick up
new listings.

One browser session handles many symbols back-to-back (~0.1–0.2s fetch each,
plus `[fetch] per_request_pause_s` between them) — no relaunch per symbol. A
full `ALL` backfill (~410 symbols) is roughly **10–15 minutes** at the default
2s pause; a `daily` run over `ALL` is proportionally faster since each request
only asks for a few trailing days.

## Logs

Console **and** `logs/nepse-YYYY-MM-DD.log`:

```
=== BACKFILL START  symbols=NEPSE  range=1990-01-01..2026-09-10  tf=daily  type=unadjusted ===
launching chrome (headless=False)
page ready, Cloudflare cleared in 6.3s
attempt 1/4  symbol=NEPSE range=1990-01-01..2026-09-10 tf=daily type=unadjusted
OK 200  rows=6590  in 0.4s
[1/1] NEPSE  fetched=6590  +6590 new / ~0 updated  span=1997-07-20..2026-09-09  (0.4s, 1 attempt)  -> NEPSE_daily_unadjusted.csv
=== BACKFILL DONE  ok=1  failed=0  rows=6590  in 8.1s (0.1 min) ===
```

On trouble you see the retry schedule and, if a symbol fails every attempt, an
`ERROR` line + a `logs/fail_<symbol>_<ts>.png` screenshot. The `runs` table in
the DB records every run's ok/failed/rows counts.

Retry policy (config `[fetch]`): 4 attempts, backoff 5s → 15s → 35s, page reload
between attempts.

## Running on a VPS + storing data locally

See [deploy/SETUP.md](deploy/SETUP.md). Summary:

1. VPS runs `daily` on a systemd timer (or cron) at ~17:45 Nepal time, Sun–Thu.
2. `scripts/sync_to_local.sh` then pushes `data/` to your machine — pick
   `tailscale-rsync`, `git`, or `rclone` in `.env`.
3. The VPS keeps a copy too, so a missed sync self-heals next day.

Code lives in git; `data/` and `logs/` are gitignored and travel via the sync
step.

## Layout

```
config/settings.toml     all knobs (env-overridable as NEPSE_*)
src/nepse_scraper/
  config.py              settings loader
  logging_setup.py       console + rotating file logs
  fetch.py               Chrome/Playwright + the data request  <- the core
  store.py               SQLite upsert + CSV export
  cli.py                 backfill / daily / export / status
scripts/                 run_backfill.sh, run_daily.sh, sync_to_local.sh
deploy/                  systemd units, crontab, SETUP.md
tests/                   test_store.py
```
