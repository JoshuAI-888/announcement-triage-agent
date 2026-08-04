"""check_company.py — cached, Claude-pinned AI company profiles (deploy build, Phase 1).

Offline: `src.company.Anthropic` is monkeypatched to a fake client class — this
check must never touch the real Anthropic API, even though a real
ANTHROPIC_API_KEY is present in this environment's .env. Covers: a cache miss
generates via the (fake) model and writes `data/company_profiles.json`-shaped
cache to a TEMP file; a cache hit reads without calling the model again;
degrade-on-failure (no SDK / no key / a raising model call / a corrupt cache
file) always falls back to an industry-only profile and never raises; and the
model used is PINNED to `_PROFILE_MODEL` regardless of anything provider-related.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from checks._harness import run
from src import company as C

CONFIG: dict = {}  # company_profile's config arg isn't consulted by this module today


class _FakeMessages:
    def __init__(self, text=None, raise_exc=None):
        self._text = text
        self._raise_exc = raise_exc
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise_exc:
            raise self._raise_exc
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)])


class _FakeAnthropic:
    """Stands in for `anthropic.Anthropic` — records the api_key it was built with."""

    last_instance: "_FakeAnthropic | None" = None

    def __init__(self, api_key=None):
        self.api_key = api_key
        self.messages = _FakeMessages(
            text="Acme Corp makes widgets for industrial buyers. "
                 "Its edge is a decade-long supplier network competitors lack."
        )
        _FakeAnthropic.last_instance = self


class _RaisingAnthropic(_FakeAnthropic):
    def __init__(self, api_key=None):
        super().__init__(api_key=api_key)
        self.messages = _FakeMessages(raise_exc=RuntimeError("simulated Claude API failure"))
        _FakeAnthropic.last_instance = self


def body(check):
    orig_anthropic = C.Anthropic
    orig_api_key = os.environ.get("ANTHROPIC_API_KEY")
    tmp = Path(tempfile.mkdtemp(prefix="company_check_"))
    cache_path = tmp / "company_profiles.json"

    try:
        os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"

        # --- cache miss: generates via the (fake) Claude call, writes the cache file ---
        C.Anthropic = _FakeAnthropic
        profile = C.company_profile("ACME", "Acme Corp", "Industrials", CONFIG, cache_path=cache_path)
        check.require(bool(profile["business"]), "a cache miss generates a business line")
        check.require(bool(profile["edge"]), "a cache miss generates an edge line")
        check.equal(profile["industry"], "Industrials", "industry passes through unchanged")
        check.equal(profile["caveat"], C.CAVEAT, "the caveat is the fixed disclosure string")
        check.require(cache_path.is_file(), "generating a profile writes the cache file (to the TEMP path)")

        on_disk = json.loads(cache_path.read_text(encoding="utf-8"))
        check.require("ACME" in on_disk, "the cache file is keyed by ticker")
        check.require(bool(on_disk["ACME"]["business"]), "the cached entry carries the business line")
        check.require("generated_at" in on_disk["ACME"], "the cached entry records generated_at")

        used_model = _FakeAnthropic.last_instance.messages.calls[0]["model"]
        check.equal(used_model, C._PROFILE_MODEL, "the model is PINNED to _PROFILE_MODEL")
        check.equal(C._PROFILE_MODEL, "claude-haiku-4-5-20251001", "_PROFILE_MODEL is the pinned Claude model id")

        # --- cache hit: a second call for the same ticker does NOT call the model again ---
        calls_before = len(_FakeAnthropic.last_instance.messages.calls)
        profile2 = C.company_profile("ACME", "Acme Corp", "Industrials", CONFIG, cache_path=cache_path)
        check.equal(profile2["business"], profile["business"], "a cache hit returns the same business text")
        check.equal(len(_FakeAnthropic.last_instance.messages.calls), calls_before,
                   "a cache hit makes no further Claude call")

        # --- degrade on failure: SDK class missing ---
        C.Anthropic = None
        degraded = C.company_profile("NOSDK", "No SDK Inc.", "Tech", CONFIG, cache_path=cache_path)
        check.equal(degraded, {"industry": "Tech", "business": "", "edge": "", "caveat": C.CAVEAT},
                   "no Anthropic SDK available -> industry-only degrade, never raises")

        # --- degrade on failure: no API key ---
        C.Anthropic = _FakeAnthropic
        os.environ.pop("ANTHROPIC_API_KEY", None)
        degraded_key = C.company_profile("NOKEY", "No Key Inc.", None, CONFIG, cache_path=cache_path)
        check.equal(degraded_key, {"industry": None, "business": "", "edge": "", "caveat": C.CAVEAT},
                   "no ANTHROPIC_API_KEY -> industry-only degrade, never raises")
        os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"

        # --- degrade on failure: the model call raises ---
        C.Anthropic = _RaisingAnthropic
        degraded_err = C.company_profile("ERRCO", "Err Co.", "Energy", CONFIG, cache_path=cache_path)
        check.equal(degraded_err, {"industry": "Energy", "business": "", "edge": "", "caveat": C.CAVEAT},
                   "a raising Claude call degrades to industry-only, never raises")
        check.require("ERRCO" not in json.loads(cache_path.read_text(encoding="utf-8")),
                      "a failed generation is never cached")

        # --- a corrupt cache file is treated as empty and regenerated, not fatal ---
        corrupt_path = tmp / "corrupt.json"
        corrupt_path.write_text("{not valid json", encoding="utf-8")
        C.Anthropic = _FakeAnthropic
        recovered = C.company_profile("CORRUPT", "Corrupt Inc.", None, CONFIG, cache_path=corrupt_path)
        check.require(bool(recovered["business"]), "a corrupt cache file doesn't crash generation")
        on_disk_recovered = json.loads(corrupt_path.read_text(encoding="utf-8"))
        check.require("CORRUPT" in on_disk_recovered, "the corrupt file is overwritten with a valid cache")

        # --- module default CACHE_PATH points at the committed data/ location ---
        check.equal(C.CACHE_PATH.name, "company_profiles.json", "the default cache filename is company_profiles.json")
        check.equal(C.CACHE_PATH.parent.name, "data", "the default cache lives under data/ (committed)")

        check.note("offline check — Anthropic is monkeypatched, no network, no ANTHROPIC_API_KEY spend")
    finally:
        C.Anthropic = orig_anthropic
        if orig_api_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = orig_api_key
        else:
            os.environ.pop("ANTHROPIC_API_KEY", None)


if __name__ == "__main__":
    run("cached, Claude-pinned company profiles (src/company.py)", body)
