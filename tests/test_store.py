"""Minimal sanity tests — run: python -m pytest  (or python tests/test_store.py)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nepse_scraper.fetch import FetchResult
from nepse_scraper.store import Store


def _result(rows):
    return FetchResult(
        symbol="NEPSE", time_frame="daily", price_type="unadjusted", rows=rows
    )


def test_upsert_insert_then_update(tmp_path):
    st = Store(tmp_path / "t.db")
    r1 = _result([
        {"f_date": "2026-09-01", "open": 1, "high": 2, "low": 1, "close": 2,
         "volume": 10, "percent_change": 0.5},
        {"f_date": "2026-09-02", "open": 2, "high": 3, "low": 2, "close": 3,
         "volume": 11, "percent_change": 0.6},
    ])
    ins, upd = st.upsert(r1)
    assert (ins, upd) == (2, 0)

    # same dates, corrected close -> update, no new rows
    r2 = _result([
        {"f_date": "2026-09-02", "open": 2, "high": 3, "low": 2, "close": 3.5,
         "volume": 12, "percent_change": 0.7},
        {"f_date": "2026-09-03", "open": 3, "high": 4, "low": 3, "close": 4,
         "volume": 13, "percent_change": 0.8},
    ])
    ins, upd = st.upsert(r2)
    assert (ins, upd) == (1, 1)
    assert st._count("NEPSE", "unadjusted", "daily") == 3
    assert st.latest_date("NEPSE", "unadjusted", "daily") == "2026-09-03"

    row = st.db.execute(
        "SELECT close FROM prices WHERE date='2026-09-02'"
    ).fetchone()
    assert row[0] == 3.5
    st.close()


def test_csv_export(tmp_path):
    st = Store(tmp_path / "t.db")
    st.upsert(_result([
        {"f_date": "2026-09-01", "open": 1, "high": 2, "low": 1, "close": 2,
         "volume": 10, "percent_change": 0.5},
    ]))
    fp = st.export_csv("NEPSE", "unadjusted", "daily", tmp_path / "csv")
    lines = fp.read_text().splitlines()
    assert lines[0] == "date,open,high,low,close,volume,percent_change"
    assert lines[1].startswith("2026-09-01,")
    st.close()


if __name__ == "__main__":
    import tempfile

    d = Path(tempfile.mkdtemp())
    test_upsert_insert_then_update(d)
    test_csv_export(d)
    print("ok")
