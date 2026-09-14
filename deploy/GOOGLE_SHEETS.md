# Google Sheets sync — setup

One-time setup (~5 minutes), then it's fully automatic: every `daily` and
`backfill` run pushes the symbols you list into their own tab in a Sheet you
own.

## 1. Create a service account

1. Go to [console.cloud.google.com](https://console.cloud.google.com/) — create
   a project if you don't have one (top-left project picker → New Project).
2. **APIs & Services → Library** → search **Google Sheets API** → Enable.
3. **APIs & Services → Credentials** → **Create Credentials → Service account**.
   - Any name, e.g. `nepse-scraper`. Skip the optional role/access steps — no
     project-level permissions needed, just the key.
4. Open the new service account → **Keys** tab → **Add Key → Create new key →
   JSON**. This downloads a `.json` file — that's your credential.

## 2. Put the key on the machine that scrapes

Copy that JSON file to `config/service_account.json` in the project (VPS or
wherever `daily`/`backfill` actually runs). It's gitignored — never commit it.

```bash
scp downloaded-key.json youruser@vps:/opt/nepse-data/config/service_account.json
chmod 600 /opt/nepse-data/config/service_account.json
```

## 3. Share your Sheet with the service account

1. Create (or open) the Google Sheet you want the data in.
2. Click **Share**, paste the service account's email — it's the
   `client_email` field inside the JSON, looks like
   `nepse-scraper@your-project.iam.gserviceaccount.com` — and give it
   **Editor** access.
3. Copy the spreadsheet ID from its URL:
   `https://docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`

## 4. Configure

In `config/settings.toml`:

```toml
[sheets]
enabled          = true
credentials_path = "config/service_account.json"
spreadsheet_id   = "paste the id from step 3"
sync_symbols     = ["NEPSE", "NABIL", "ADBL"]   # keep this short — your watchlist
pause_s          = 1.2
```

Then install the extra dependency (only needed for Sheets):

```bash
pip install gspread google-auth
```

## 5. Test it

```bash
python -m nepse_scraper sync-sheets
```

You should see a new tab per symbol appear in the Sheet, with columns
`date, open, high, low, close, volume, percent_change`. From here on, every
`daily` (and `backfill`) run does this automatically at the end — no extra
step needed once `enabled = true`.

## Notes

- **Keep `sync_symbols` short.** Each tab write is one API call; Google's
  default quota is 60 write requests/minute per user. A watchlist of a
  handful to a few dozen symbols is fine. Don't point this at `ALL` (376
  symbols) — that's what the CSV/SQLite files and local sync are for.
- Each sync **fully rewrites** the tab from the SQLite store (not an append).
  Simple, always consistent, safe to re-run — but don't hand-edit those tabs,
  your edits get overwritten on the next sync.
- If it fails, the scrape itself still succeeds — a Sheets outage never loses
  scraped data, it just logs `sheets sync done: ok=X failed=Y` and moves on.
