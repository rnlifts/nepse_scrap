# VPS setup (Ubuntu/Debian)

## 1. System packages

```bash
sudo useradd -m -d /opt/nepse-data -s /bin/bash nepse   # or reuse an existing user
sudo apt update
sudo apt install -y python3 python3-venv python3-pip xvfb wget gnupg

# real Google Chrome (Playwright channel="chrome")
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update && sudo apt install -y google-chrome-stable
```

## 2. The project

```bash
sudo -iu nepse
git clone <your-repo> /opt/nepse-data && cd /opt/nepse-data
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
playwright install-deps chromium        # shared libs Chrome needs
# channel="chrome" uses the apt Chrome above; no `playwright install chromium` needed
cp .env.example .env && nano .env        # set SYNC_STRATEGY + SYNC_DEST
chmod +x scripts/*.sh
```

`scripts/run_daily.sh` auto-detects a headless box and wraps the run in
`xvfb-run`, so headed Chrome works with no display.

## 3. First backfill

```bash
. .venv/bin/activate
scripts/run_backfill.sh --symbols NEPSE          # ~10 s for the index
python -m nepse_scraper status
```

## 4. Schedule the daily run

### systemd (preferred)

```bash
sudo cp deploy/nepse-daily.service deploy/nepse-daily.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nepse-daily.timer
systemctl list-timers nepse-daily.timer          # check next run
journalctl -u nepse-daily.service -f             # watch a run
```

### or cron

```bash
crontab deploy/crontab.txt
```

## 5. Get the data onto your local machine

Set `SYNC_STRATEGY` in `.env`:

| strategy          | VPS side                                   | local side                          |
|-------------------|--------------------------------------------|-------------------------------------|
| `tailscale-rsync` | `tailscale up`; `SYNC_DEST=you@laptop:/path/to/nepse-data/data/` | `tailscale up`; keep the box reachable |
| `git`             | `data/` is its own git repo with a remote  | `git -C data pull` (cron/manual)    |
| `rclone`          | `rclone config` a remote; `SYNC_DEST=remote:nepse-data` | `rclone sync remote:nepse-data ./data` |

`run_daily.sh` calls `scripts/sync_to_local.sh` automatically after each scrape.

## Troubleshooting

* **`Cloudflare challenge did not clear`** — transient; the timer retries next
  day. To force a run: `scripts/run_daily.sh`. If it persists, the VPS IP may be
  flagged; a residential/other IP or a short delay usually clears it.
* **`channel=chrome unavailable`** — `google-chrome-stable` not installed; the
  code falls back to bundled Chromium (`playwright install chromium`), which is
  more likely to hit the Cloudflare screen.
* **`non-JSON response … Cloudflare re-challenge`** — same as above; ret/reload
  logic handles the common case.
* Logs: `logs/nepse-YYYY-MM-DD.log`, `logs/daily-YYYY-MM-DD.log`, plus
  `logs/fail_*.png` screenshots on a fully failed symbol.
