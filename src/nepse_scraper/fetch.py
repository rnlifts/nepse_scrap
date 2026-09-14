"""Fetch NEPSE price history from nepsealpha.com/nepse-data.

Why a real browser:
  * The site is behind Cloudflare, which 403s plain HTTP clients and stalls
    headless Chrome on the "Just a moment" screen.
  * /nepse-data expects a session established by the page's own JavaScript.

Approach (simple and robust):
  1. Open the page in the system's real Google Chrome (headed; wrap in xvfb on
     a server). Wait for the Cloudflare interstitial to clear.
  2. Call the endpoint with `page.evaluate()` -> an in-page `fetch()`.  Because
     it runs inside the loaded page it inherits the cookies / headers the site
     expects, and Cloudflare sees an ordinary same-origin XHR.
  3. One request returns the whole date range as JSON (no pagination).

No UI clicking, no request rewriting, no CSRF token juggling.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date

from .config import Config
from .logging_setup import get_logger

log = get_logger("fetch")

_JS_FETCH = """
async (body) => {
  const r = await fetch('/nepse-data', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  const text = await r.text();
  return { status: r.status,
           ctype: r.headers.get('content-type') || '',
           text };
}
"""


class CloudflareStuck(RuntimeError):
    """The 'Just a moment' screen did not clear in time."""


class FetchError(RuntimeError):
    """A request failed (bad status, non-JSON)."""


class NoDataError(FetchError):
    """The server responded fine but has no rows for this symbol/range —
    not a transient Cloudflare/network hiccup, so don't burn the full
    backoff schedule retrying it."""


@dataclass
class FetchResult:
    symbol: str
    time_frame: str
    price_type: str
    rows: list[dict]
    elapsed_s: float = 0.0
    attempts: int = 1

    @property
    def span(self) -> tuple[str, str] | None:
        if not self.rows:
            return None
        ds = sorted(r["f_date"] for r in self.rows)
        return ds[0], ds[-1]


@dataclass
class Fetcher:
    cfg: Config
    _pw: object = field(default=None, repr=False)
    _browser: object = field(default=None, repr=False)
    _ctx: object = field(default=None, repr=False)
    _page: object = field(default=None, repr=False)
    _ready: bool = False

    # -- lifecycle ------------------------------------------------------
    def __enter__(self) -> "Fetcher":
        from playwright.sync_api import sync_playwright

        t0 = time.monotonic()
        self._pw = sync_playwright().start()
        channel = self.cfg.get("browser", "channel")
        headless = self.cfg.get("browser", "headless")
        log.info("launching %s (headless=%s)", channel, headless)
        try:
            self._browser = self._pw.chromium.launch(
                channel=channel, headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as e:  # noqa: BLE001
            log.warning("channel=%s unavailable (%s) — falling back to bundled chromium", channel, e)
            self._browser = self._pw.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
        self._ctx = self._browser.new_context(no_viewport=True, locale="en-US")
        self._page = self._ctx.new_page()
        self._open_site(t0)
        return self

    def __exit__(self, *exc):
        for closer in (self._ctx, self._browser):
            try:
                closer and closer.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            self._pw and self._pw.stop()
        except Exception:  # noqa: BLE001
            pass

    # -- internals ----------------------------------------------------
    def _clear_cloudflare(self) -> None:
        cf_to = self.cfg.get("browser", "cf_clear_timeout_s")
        deadline = time.monotonic() + cf_to
        while time.monotonic() < deadline:
            title = (self._page.title() or "").lower()
            if "just a moment" not in title and "checking your browser" not in title:
                return
            time.sleep(1)
        raise CloudflareStuck(f"Cloudflare challenge did not clear within {cf_to}s")

    def _open_site(self, t0: float) -> None:
        url = self.cfg.base_url
        nav_to = self.cfg.get("browser", "nav_timeout_s") * 1000
        log.info("navigating to %s", url)
        self._page.goto(url, wait_until="domcontentloaded", timeout=nav_to)
        self._clear_cloudflare()
        time.sleep(2.5)  # let the site's JS finish booting
        self._ready = True
        log.info("page ready, Cloudflare cleared in %.1fs", time.monotonic() - t0)

    # -- symbol discovery ---------------------------------------------
    def list_symbols(self) -> list[dict]:
        """Read the page's own Symbols/Indices <select> — ticker + full name.

        Not the /trading/1/search endpoint (that one is disallowed in
        robots.txt); this reads the dropdown already present in the loaded
        page, which is not.
        """
        js = """
        () => {
          const sel = document.querySelector('select[name=symbol]')
                   || [...document.querySelectorAll('select')]
                        .find(s => s.options.length > 100);
          if (!sel) return [];
          return [...sel.options]
            .filter(o => o.value)
            .map(o => ({ symbol: o.value, label: o.textContent.trim() }));
        }
        """
        opts = self._page.evaluate(js)
        log.info("discovered %d symbols/indices from the page dropdown", len(opts))
        return opts

    def _reload(self) -> None:
        self._page.goto(
            self.cfg.base_url, wait_until="domcontentloaded",
            timeout=self.cfg.get("browser", "nav_timeout_s") * 1000,
        )
        self._clear_cloudflare()
        time.sleep(2.5)

    @staticmethod
    def _body(symbol, start, end, price_type, time_frame) -> str:
        from urllib.parse import urlencode

        return urlencode({
            "symbol": symbol,
            "specific_date": end,
            "start_date": start,
            "end_date": end,
            "filter_type": "date-range",
            "price_type": price_type,
            "time_frame": time_frame,
        })

    # -- public API -------------------------------------------------
    def fetch(
        self,
        symbol: str,
        start: str,
        end: str | None = None,
        *,
        price_type: str | None = None,
        time_frame: str | None = None,
    ) -> FetchResult:
        if not self._ready:
            raise RuntimeError("Fetcher used outside its context manager")

        end = end or date.today().isoformat()
        price_type = price_type or self.cfg.get("source", "price_type")
        time_frame = time_frame or self.cfg.get("source", "time_frame")
        max_attempts = self.cfg.get("fetch", "max_attempts")
        backoff = self.cfg.get("fetch", "backoff_base_s")

        body = self._body(symbol, start, end, price_type, time_frame)
        last_err: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            t0 = time.monotonic()
            log.info(
                "attempt %d/%d  symbol=%s range=%s..%s tf=%s type=%s",
                attempt, max_attempts, symbol, start, end, time_frame, price_type,
            )
            try:
                res = self._page.evaluate(_JS_FETCH, body)
                dt = time.monotonic() - t0

                if res["status"] != 200:
                    raise FetchError(f"HTTP {res['status']}")
                if "json" not in res["ctype"]:
                    raise FetchError(
                        f"non-JSON response ({res['ctype']!r}) — Cloudflare re-challenge?"
                    )
                rows = (json.loads(res["text"]).get("data")) or []
                if not rows:
                    raise NoDataError(
                        "empty data array — no history for this symbol/range "
                        "(likely delisted, renamed, or not a priced instrument)"
                    )

                log.info("OK 200  rows=%d  in %.1fs", len(rows), dt)
                return FetchResult(
                    symbol=symbol, time_frame=time_frame, price_type=price_type,
                    rows=rows, elapsed_s=dt, attempts=attempt,
                )
            except NoDataError as e:
                # Not transient — retrying with backoff just wastes ~55s per
                # symbol for something a second attempt will never fix. One
                # quick confirmation retry (network blip aside), then give up.
                last_err = e
                if attempt >= 2:
                    log.warning("no data for %s after %d quick attempt(s) — skipping (not retrying with backoff)", symbol, attempt)
                    raise FetchError(str(e)) from e
                log.info("attempt %d: no data yet, one quick retry (no backoff)", attempt)
                time.sleep(1)
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt == max_attempts:
                    break
                wait = backoff * (2 ** attempt - 1)
                log.warning("attempt %d failed: %s — retrying in %ds", attempt, e, wait)
                time.sleep(wait)
                try:
                    self._reload()
                except Exception as re:  # noqa: BLE001
                    log.warning("reload during retry failed: %s", re)

        try:
            shot = f"logs/fail_{symbol}_{int(time.time())}.png"
            self._page.screenshot(path=shot)
            log.error("saved failure screenshot -> %s", shot)
        except Exception:  # noqa: BLE001
            pass
        raise FetchError(f"all attempts failed for {symbol}: {last_err}")


def write_raw(result: FetchResult, raw_dir) -> None:
    """Persist the raw payload for replay/debugging."""
    from pathlib import Path

    raw_dir = Path(raw_dir)
    out = raw_dir / date.today().isoformat()
    out.mkdir(parents=True, exist_ok=True)
    fp = out / f"{result.symbol}_{result.time_frame}_{result.price_type}.json"
    fp.write_text(json.dumps(result.rows, separators=(",", ":")), encoding="utf-8")
    log.debug("raw payload -> %s", fp)
