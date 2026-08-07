"""check_market.py — best-effort Twelve Data price snapshots (deploy build, Phase 1).

Offline: `src.market.requests.get` is monkeypatched to a canned Twelve Data
payload for every scenario — this check must never touch the network, even
though a real TWELVEDATA_API_KEY is present in this environment's .env.

Covers: normal parsing (last/prev_close/change/series7/series30/series90/asof
+ the window_7d/30d/90d change fields), the BRK-B -> BRK.B provider-symbol
translation, `None` on a missing key / HTTP error / `status:"error"` /
too-short series / a raised transport exception, and the in-process
per-ticker cache (a second call makes no further HTTP request).
"""

from __future__ import annotations

import datetime as dt
import os

from checks._harness import run
from src import market as M

CONFIG = {"market": {"provider": "twelvedata", "base_url": "https://api.twelvedata.com",
                     "api_key_env": "CHECK_MARKET_FAKE_KEY"}}

# 130 chronological (oldest -> newest) closes — enough to exercise series90 and
# every window (outputsize is 130 per the frozen contract, Phase 2).
_CLOSES_130 = [100.0 + i * 0.37 for i in range(130)]
_BASE_DATE = dt.date(2026, 1, 1)


def _expected_window(closes: list[float], n: int) -> tuple[float, float]:
    """Mirrors src.market._window_change's definition, independently, so this
    check catches a regression in the slicing/baseline logic."""
    last = closes[-1]
    baseline = closes[-n] if len(closes) >= n else closes[0]
    change = last - baseline
    change_pct = (change / baseline * 100.0) if baseline else 0.0
    return change, change_pct


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
        closes = _CLOSES_130  # oldest -> newest, 130 trading days
        rows = [{"datetime": (_BASE_DATE + dt.timedelta(days=i)).isoformat(), "close": str(c)}
                for i, c in enumerate(closes)]
        rows = rows[::-1]  # Twelve Data returns newest-first
        return _Resp({"meta": {"symbol": params["symbol"]}, "status": "ok", "values": rows})

    M.requests.get = fake_get
    snap = M.price_snapshot("AAPL", CONFIG)
    check.require(snap is not None, "a well-formed payload parses to a snapshot")
    check.equal(snap["last"], _CLOSES_130[-1], "last is the newest close")
    check.equal(snap["prev_close"], _CLOSES_130[-2], "prev_close is the second-newest close")
    check.equal(round(snap["change"], 4), round(_CLOSES_130[-1] - _CLOSES_130[-2], 4), "change is last - prev_close")
    check.equal(round(snap["change_pct"], 6),
               round((_CLOSES_130[-1] - _CLOSES_130[-2]) / _CLOSES_130[-2] * 100.0, 6),
               "change_pct matches change/prev_close")
    check.equal(snap["currency"], "USD", "currency is USD")
    check.equal(snap["asof"], (_BASE_DATE + dt.timedelta(days=129)).isoformat(), "asof is the newest datetime, date-only")

    # --- series7/30/90: chronological oldest->newest, capped at their own length ---
    check.equal(len(snap["series7"]), 7, "series7 is capped at 7 points")
    check.equal(snap["series7"], _CLOSES_130[-7:], "series7 is chronological oldest->newest, the most recent 7")
    check.equal(len(snap["series30"]), 30, "series30 is capped at 30 points")
    check.equal(snap["series30"], _CLOSES_130[-30:], "series30 is chronological oldest->newest, the most recent 30")
    check.equal(len(snap["series90"]), 90, "series90 is capped at 90 points")
    check.equal(snap["series90"], _CLOSES_130[-90:], "series90 is chronological oldest->newest, the most recent 90")

    # --- window_7d/30d/90d: change/change_pct vs. the close ~N trading days earlier ---
    for n, key in ((7, "window_7d"), (30, "window_30d"), (90, "window_90d")):
        check.require(key in snap, f"{key} is present in the snapshot")
        exp_change, exp_change_pct = _expected_window(_CLOSES_130, n)
        check.equal(round(snap[key]["change"], 6), round(exp_change, 6), f"{key}.change matches last vs. {n}-day-earlier close")
        check.equal(round(snap[key]["change_pct"], 6), round(exp_change_pct, 6), f"{key}.change_pct matches change/baseline")

    check.equal(len(calls), 1, "exactly one HTTP call was made")
    check.equal(calls[0][0], f"{CONFIG['market']['base_url']}/time_series", "the time_series endpoint is called")
    check.equal(calls[0][1]["symbol"], "AAPL", "AAPL needs no symbol translation")
    check.equal(calls[0][1]["interval"], "1day", "interval=1day per the frozen contract")
    check.equal(calls[0][1]["outputsize"], 130, "outputsize=130 per the frozen contract (Phase 2: covers 90 trading days)")
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
