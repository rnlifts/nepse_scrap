# Daily NEPSE scrape, meant to be run by Windows Task Scheduler.
# Runs from the local machine (residential IP) since the VPS's datacenter IP
# gets Cloudflare-challenged by nepsealpha.com regardless of browser fidelity.
#
# What it does each run:
#   1. python -m nepse_scraper daily --symbols ALL
#        -- pulls trailing days for every tracked symbol (unadjusted prices,
#           which carry real volume), upserts SQLite, re-exports CSVs, and
#           (since [sheets] enabled=true) pushes the configured watchlist
#           tabs to Google Sheets.
#   2. python -m nepse_scraper daily --symbols ALL --price-type adjusted --no-sheets
#        -- same, but split/bonus-adjusted prices (volume is 0 for this
#           price type -- a source limitation). --no-sheets skips a
#           redundant duplicate Sheets push (Sheets always mirrors the
#           unadjusted series from step 1).
#   Logs everything to logs\task-YYYY-MM-DD.log so you can check it later.

$ErrorActionPreference = "Stop"
$ProjectDir = "C:\Users\user\Desktop\project nepse\nepse-data"
Set-Location $ProjectDir

# This machine has a stray CURL_CA_BUNDLE pointing at a Postgres install's
# (nonexistent-for-our-purposes) cert bundle, which breaks TLS for Python's
# HTTP libraries. Override it to the correct CA bundle for this run only.
$env:CURL_CA_BUNDLE = (python -c "import certifi; print(certifi.where())")
$env:SSL_CERT_FILE  = $env:CURL_CA_BUNDLE
$env:PYTHONPATH     = "src"

$LogDir = Join-Path $ProjectDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir ("task-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

"==== $(Get-Date -Format o) daily run start ====" | Out-File -Append -Encoding utf8 $LogFile

try {
    python -m nepse_scraper daily --symbols ALL 2>&1 | Out-File -Append -Encoding utf8 $LogFile
    $exitCode1 = $LASTEXITCODE
    python -m nepse_scraper daily --symbols ALL --price-type adjusted --no-sheets 2>&1 | Out-File -Append -Encoding utf8 $LogFile
    $exitCode2 = $LASTEXITCODE
    $exitCode = [Math]::Max($exitCode1, $exitCode2)
} catch {
    "ERROR: $_" | Out-File -Append -Encoding utf8 $LogFile
    $exitCode = 1
}

"==== $(Get-Date -Format o) daily run end (exit $exitCode) ====" | Out-File -Append -Encoding utf8 $LogFile
exit $exitCode
