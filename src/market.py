"""market.py — best-effort price snapshots via Twelve Data (deploy build, Phase 1).

`price_snapshot()` powers the price block + 7-day sparkline on MATERIAL items in
the brief. It is best-effort and must NEVER raise: no configured key, an HTTP
error, a Twelve Data `status:"error"` response, or too short a series all
degrade to `None` rather than breaking a run — market data is a nice-to-have,
not something a filing's classification should ever depend on (same spirit as
`src.adapters.edgar`'s tiered PDF pipeline, where one flaky external call never
takes down the whole fetch).

A small in-process cache means a single run never double-calls the API for the
same ticker (a ticker can appear in both the ranked list's price block and, in
principle, elsewhere in the same pass).

Config lives in `config.yaml`'s `market:` block:
    market:
      provider: twelvedata
      base_url: "https://api.twelvedata.com"
      api_key_env: TWELVEDATA_API_KEY
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")  # make TWELVEDATA_API_KEY available, like src/classify.py

DEFAULT_BASE_URL = "https://api.twelvedata.com"
DEFAULT_API_KEY_ENV = "TWELVEDATA_API_KEY"

# In-process cache, keyed by ticker (the announcement's own ticker, not the
# provider-translated symbol) — one run, one call per ticker.
_cache: dict[str, Optional[dict]] = {}


def _clear_cache() -> None:
    """Reset the in-process cache. Exposed for checks; a real run never needs it."""
    _cache.clear()


def _provider_symbol(ticker: str) -> str:
    """EDGAR dash tickers (e.g. BRK-B, BF-B) -> Twelve Data's dot form (BRK.B, BF.B)."""
    return ticker.replace("-", ".")


def _parse_time_series(payload: object) -> Optional[dict]:
    """Twelve Data `time_series` payload -> the normalised snapshot shape, or None.

    Twelve Data returns `values` newest-first; the snapshot's `series7` is
    chronological oldest -> newest, capped at 7 points, per the frozen shape.
    """
    if not isinstance(payload, dict) or payload.get("status") == "error":
        return None
    values = payload.get("values")
    if not isinstance(values, list) or len(values) < 2:
        return None
    try:
        parsed = sorted(
            ((row["datetime"], float(row["close"])) for row in values),
            key=lambda pair: pair[0],
        )
        closes = [close for _, close in parsed]
        last = closes[-1]
        prev_close = closes[-2]
        change = last - prev_close
        change_pct = (change / prev_close * 100.0) if prev_close else 0.0
        return {
            "last": last,
            "prev_close": prev_close,
            "change": change,
            "change_pct": change_pct,
            "currency": "USD",
            "series7": closes[-7:],
            "asof": parsed[-1][0][:10],
        }
    except (KeyError, TypeError, ValueError):
        return None


def _fetch(ticker: str, config: dict) -> Optional[dict]:
    market_cfg = ((config or {}).get("market")) or {}
    base_url = market_cfg.get("base_url", DEFAULT_BASE_URL)
    api_key_env = market_cfg.get("api_key_env", DEFAULT_API_KEY_ENV)
    api_key = os.environ.get(api_key_env)
    if not api_key:
        return None

    try:
        resp = requests.get(
            f"{base_url}/time_series",
            params={
                "symbol": _provider_symbol(ticker),
                "interval": "1day",
                "outputsize": 8,
                "apikey": api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return None

    return _parse_time_series(payload)


def price_snapshot(ticker: str, config: dict) -> Optional[dict]:
    """Best-effort price snapshot for one ticker. NEVER raises — see module docstring.

    Returns `None` on any failure, or:
        {"last": float, "prev_close": float, "change": float, "change_pct": float,
         "currency": "USD", "series7": [float, ...], "asof": "YYYY-MM-DD"}
    """
    if ticker in _cache:
        return _cache[ticker]
    result = _fetch(ticker, config)
    _cache[ticker] = result
    return result
