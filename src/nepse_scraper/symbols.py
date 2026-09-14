"""Discover and classify the tickers nepsealpha.com knows about.

The page's own Symbols/Indices dropdown lists ~700+ entries: ordinary equity,
promoter shares, bonds/debentures, mutual funds, and NEPSE's sector indices.
We tag each so `--symbols ALL` (or `ALL:equity`, `ALL:index`, ...) can filter
sensibly instead of pulling bond coupons alongside share prices.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

_SECTOR_INDEX_CODES = {
    "NEPSE", "BANKING", "DEVBANK", "FINANCE", "HYDROPOWER", "MICROFINANCE",
    "LIFEINSU", "NONLIFEINSU", "HOTELS", "MANUFACTURE", "TRADING",
    "INVESTMENT", "OTHERS", "FLOAT", "SENFLOAT", "SENSITIVE", "MUTUAL",
}

_BOND_RE = re.compile(r"\d+(\.\d+)?%|Debenture|Rinpatra|Bond", re.I)
_PROMOTER_RE = re.compile(r"Promoter", re.I)
_FUND_RE = re.compile(r"Fund|Yojana|Scheme|SIP", re.I)


def classify(symbol: str, label: str) -> str:
    if symbol in _SECTOR_INDEX_CODES:
        return "index"
    if _BOND_RE.search(label):
        return "bond"
    if _PROMOTER_RE.search(label) or symbol.endswith(("PO", "P")):
        return "promoter"
    if _FUND_RE.search(label):
        return "fund"
    return "equity"


def save_csv(entries: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for e in entries:
        sym, label = e["symbol"], e["label"]
        name = label[len(sym):].strip(" ()") if label.startswith(sym) else label
        rows.append((sym, name, classify(sym, label)))
    rows.sort(key=lambda r: r[0])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "name", "type"])
        w.writerows(rows)
    return path


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_dead(dead_path: Path) -> set[str]:
    if not dead_path.exists():
        return set()
    return {ln.strip() for ln in dead_path.read_text(encoding="utf-8").splitlines() if ln.strip()}


def add_dead(dead_path: Path, symbols: list[str]) -> None:
    """Record symbols that returned no data at all — so `ALL` stops
    wasting a retry cycle on them every single run. `--symbols TICKER`
    explicitly still tries it (in case it gets re-listed)."""
    if not symbols:
        return
    dead_path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_dead(dead_path)
    new = existing | set(symbols)
    dead_path.write_text("\n".join(sorted(new)) + "\n", encoding="utf-8")


def resolve_symbol_list(spec: list[str], symbols_csv: Path, dead_path: Path | None = None) -> list[str]:
    """Expand config/CLI symbol specs.

    - plain tickers pass through unchanged: ["NEPSE", "NABIL"]
    - "ALL" -> every ticker in symbols.csv (equity + index; skips bonds/
      promoter shares/funds, which aren't ordinary tradeable stock prices)
    - "ALL:<type>" -> only that type, e.g. "ALL:equity", "ALL:index"
    """
    out: list[str] = []
    rows = load_csv(symbols_csv)
    dead = load_dead(dead_path) if dead_path else set()
    for item in spec:
        if item == "ALL":
            if not rows:
                raise RuntimeError(
                    f"{symbols_csv} not found — run 'refresh-symbols' first"
                )
            out += [r["symbol"] for r in rows if r["type"] in ("equity", "index")]
        elif item.startswith("ALL:"):
            want = item.split(":", 1)[1]
            out += [r["symbol"] for r in rows if r["type"] == want]
        else:
            out.append(item)  # explicit request: try it even if marked dead
    if dead:
        was_all = any(s == "ALL" or s.startswith("ALL:") for s in spec)
        if was_all:
            out = [s for s in out if s not in dead]
    # de-dupe, keep order
    seen = set()
    return [s for s in out if not (s in seen or seen.add(s))]
