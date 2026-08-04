"""check_market.py — best-effort Twelve Data price snapshots (deploy build, Phase 1).

Offline: `src.market.requests.get` is monkeypatched to a canned Twelve Data
payload for every scenario — this check must never touch the network, even
though a real TWELVEDATA_API_KEY is present in this environment's .env.

Covers: normal parsing (last/prev_close/change/series7/asof), the BRK-B ->
BRK.B provider-symbol translation, `None` on a missing key / HTTP error /
`status:"error"` / too-short series / a raised transport exception, and the
in-process per-ticker cache (a second call makes no further HTTP request).
"""

from __future__ import annotations

import os

from checks._harness import run
from src import market as M

CONFIG = {"market": {"provider": "twelvedata", "base_url": "https://api.twelvedata.com",
                     "api_key_env": "CHECK_MARKET_FAKE_KEY"}}


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _refuse_network(*_args, **_kwargs):
    raise AssertionError("network call attempted — price_snapshot must not call requests.get here")


def body(check):
    os.environ["CHECK_MARKET_FAKE_KEY"] = "test-key-not-real"

    # --- normal parsing ---
    M._clear_cache()
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, dict(params or {})))
        closes = [98.0, 99.5, 100.0, 100.5, 101.0, 100.8, 101.5, 102.0]  # oldest -> newest, 8 days
        rows = [{"datetime": f"2026-07-{7 + i:02d}", "close": str(c)} for i, c in enumerate(closes)]
        rows = rows[::-1]  # Twelve Data returns newest-first
        return _Resp({"meta": {"symbol": params["symbol"]}, "status": "ok", "values": rows})

    M.requests.get = fake_get
    snap = M.price_snapshot("AAPL", CONFIG)
    check.require(snap is not None, "a well-formed payload parses to a snapshot")
    check.equal(snap["last"], 102.0, "last is the newest close")
    check.equal(snap["prev_close"], 101.5, "prev_close is the second-newest close")
    check.equal(round(snap["change"], 4), 0.5, "change is last - prev_close")
    check.equal(round(snap["change_pct"], 6), round(0.5 / 101.5 * 100.0, 6), "change_pct matches change/prev_close")
    check.equal(snap["currency"], "USD", "currency is USD")
    check.equal(snap["asof"], "2026-07-14", "asof is the newest datetime, date-only")
    check.equal(len(snap["series7"]), 7, "series7 is capped at 7 points")
    check.equal(snap["series7"], [99.5, 100.0, 100.5, 101.0, 100.8, 101.5, 102.0],
               "series7 is chronological oldest->newest, the most recent 7")
    check.equal(len(calls), 1, "exactly one HTTP call was made")
    check.equal(calls[0][0], f"{CONFIG['market']['base_url']}/time_series", "the time_series endpoint is called")
    check.equal(calls[0][1]["symbol"], "AAPL", "AAPL needs no symbol translation")
    check.equal(calls[0][1]["interval"], "1day", "interval=1day per the frozen contract")
    check.equal(calls[0][1]["outputsize"], 8, "outputsize=8 per the frozen contract")
    check.equal(calls[0][1]["apikey"], "test-key-not-real", "the configured env var's key is used")

    # --- cache: a second call for the same ticker makes no further HTTP request ---
    snap2 = M.price_snapshot("AAPL", CONFIG)
    check.require(snap2 is snap, "a cached ticker returns the identical object, no re-fetch")
    check.equal(len(calls), 1, "the in-process cache prevented a second HTTP call")

    # --- dash -> dot provider-symbol translation ---
    M._clear_cache()
    M.requests.get = fake_get
    M.price_snapshot("BRK-B", CONFIG)
    check.equal(calls[-1][1]["symbol"], "BRK.B", "BRK-B is translated to BRK.B for the provider query")
    M._clear_cache()
    M.requests.get = fake_get
    M.price_snapshot("BF-B", CONFIG)
    check.equal(calls[-1][1]["symbol"], "BF.B", "BF-B is translated to BF.B for the provider query")

    # --- missing key: None, and no HTTP call is even attempted ---
    M._clear_cache()
    M.requests.get = _refuse_network
    os.environ.pop("CHECK_MARKET_MISSING_KEY", None)
    no_key_config = {"market": {"api_key_env": "CHECK_MARKET_MISSING_KEY"}}
    check.equal(M.price_snapshot("MSFT", no_key_config), None, "no configured key -> None, no network attempted")

    # --- HTTP error -> None ---
    M._clear_cache()
    M.requests.get = lambda url, params=None, timeout=None: _Resp({}, status_code=500)
    check.equal(M.price_snapshot("GOOGL", CONFIG), None, "an HTTP error degrades to None")

    # --- status:error payload -> None ---
    M._clear_cache()
    M.requests.get = lambda url, params=None, timeout=None: _Resp(
        {"code": 400, "message": "bad symbol", "status": "error"}
    )
    check.equal(M.price_snapshot("ZZBAD", CONFIG), None, "a Twelve Data status:error payload degrades to None")

    # --- too-short series -> None ---
    M._clear_cache()
    M.requests.get = lambda url, params=None, timeout=None: _Resp(
        {"status": "ok", "values": [{"datetime": "2026-07-14", "close": "100.0"}]}
    )
    check.equal(M.price_snapshot("ONEDAY", CONFIG), None, "a series with under 2 points degrades to None")

    # --- missing/empty values -> None ---
    M._clear_cache()
    M.requests.get = lambda url, params=None, timeout=None: _Resp({"status": "ok", "values": []})
    check.equal(M.price_snapshot("EMPTYSERIES", CONFIG), None, "an empty values list degrades to None")

    # --- a raised transport exception -> None, never raises ---
    M._clear_cache()
    def raising_get(url, params=None, timeout=None):
        raise ConnectionError("simulated network failure")
    M.requests.get = raising_get
    check.equal(M.price_snapshot("NETFAIL", CONFIG), None, "a transport exception degrades to None, never raises")

    check.note("offline check — requests.get is monkeypatched, no network, no TWELVEDATA_API_KEY spend")


if __name__ == "__main__":
    run("Twelve Data price snapshots (src/market.py)", body)
