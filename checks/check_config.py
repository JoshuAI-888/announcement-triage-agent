"""check_config.py — the runtime_config.json contract (Phase 0, offline, no spend).

Guards the configuration boundary the dashboard writes across:
  - the committed runtime_config.json validates;
  - malformed payloads (bad enum, out-of-range, bad time/email) are rejected;
  - the NO-GOLD-FIELD rule holds (prohibition #1 / S4) — a config can never carry a
    gold label, slice tag, or a data/gold path;
  - apply_overrides overlays config.yaml without mutating the base;
  - the eval fingerprint is stable and moves iff an eval-affecting field changes.
"""

from __future__ import annotations

import copy
import json

from checks._harness import run
from src import config_schema as C
from src.config_schema import GoldFieldError, RuntimeConfig
from src.fetch import load_config


def _valid_payload() -> dict:
    return json.loads(C.RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))


def body(check):
    base = load_config()

    # --- the committed file is valid ---
    rc = C.load_runtime_config()
    check.require(isinstance(rc, RuntimeConfig), "committed runtime_config.json validates")
    check.equal(rc.draft.email, "joshuafang@gmail.com", "draft email carried through")
    check.require(len(rc.watchlist) >= 1, "watchlist non-empty")

    # --- schema rejects malformed payloads ---
    def _bad(mut):
        p = _valid_payload()
        mut(p)
        return lambda: C.validate(p)

    check.raises(Exception, _bad(lambda p: p["run"].__setitem__("provider", "gemini")),
                 "unknown provider rejected")
    check.raises(Exception, _bad(lambda p: p["thresholds"].__setitem__("confidence_floor", 1.5)),
                 "confidence_floor > 1 rejected")
    check.raises(Exception, _bad(lambda p: p["schedule"].__setitem__("poll_time_nzt", "25:00")),
                 "invalid poll time rejected")
    check.raises(Exception, _bad(lambda p: p["draft"].__setitem__("email", "not-an-email")),
                 "invalid draft email rejected")
    check.raises(Exception, _bad(lambda p: p.__setitem__("watchlist", ["aapl"])),
                 "lowercase ticker rejected")
    check.raises(Exception, _bad(lambda p: p.__setitem__("unknown_key", 1)),
                 "unknown top-level key rejected (extra=forbid)")

    # --- schedule.lookback_days: int, default 1, min 1 (round-trips through all
    #     four schema surfaces on the Python side; regenerated JSON schema
    #     + dashboard mirrors are the other three, out of scope for this stream) ---
    payload_no_lookback = _valid_payload()
    del payload_no_lookback["schedule"]["lookback_days"]
    rc_default = C.validate(payload_no_lookback)
    check.equal(rc_default.schedule.lookback_days, 1, "lookback_days defaults to 1 when omitted")

    check.raises(Exception, _bad(lambda p: p["schedule"].__setitem__("lookback_days", 0)),
                 "lookback_days == 0 rejected (min 1)")
    check.raises(Exception, _bad(lambda p: p["schedule"].__setitem__("lookback_days", -3)),
                 "negative lookback_days rejected")

    payload_lookback_5 = _valid_payload()
    payload_lookback_5["schedule"]["lookback_days"] = 5
    rc_5 = C.validate(payload_lookback_5)
    check.equal(rc_5.schedule.lookback_days, 5, "a valid positive lookback_days round-trips")
    check.equal(rc_5.model_dump()["schedule"]["lookback_days"], 5,
                "lookback_days survives model_dump() round-trip")
    merged_5 = C.apply_overrides(base, rc_5)
    check.equal(merged_5["_runtime"]["schedule"]["lookback_days"], 5,
                "lookback_days threads into cfg['_runtime']['schedule'] via apply_overrides")

    # --- the NO-GOLD-FIELD boundary (prohibition #1 / S4) ---
    check.raises(GoldFieldError, _bad(lambda p: p.__setitem__("gold_labels", {"x": "material"})),
                 "a gold_labels key is refused")
    check.raises(GoldFieldError, _bad(lambda p: p.__setitem__("slice_tag", "clear_material")),
                 "a slice_tag key is refused")
    check.raises(GoldFieldError, _bad(lambda p: p["draft"].__setitem__("prompt", "read data/gold/gold.csv")),
                 "a value pointing at data/gold is refused")
    check.note("no config route can reach the gold set")

    # --- apply_overrides overlays without mutating the base ---
    base_snapshot = copy.deepcopy(base)
    merged = C.apply_overrides(base, rc)
    check.equal(base, base_snapshot, "apply_overrides does not mutate the base config")
    check.equal(merged["watchlist"], list(rc.watchlist), "watchlist overlaid")
    check.equal(merged["thresholds"]["confidence_floor"], rc.thresholds.confidence_floor,
                "threshold overlaid")
    check.equal(merged["_runtime"]["draft_email"], rc.draft.email, "runtime block carries draft email")
    check.equal(merged["_runtime"]["schedule"]["intraday_alerts"], rc.schedule.intraday_alerts,
                "schedule carried into runtime block")

    # --- run.provider actually swaps the primary model id + pricing (P flag #3) ---
    prov = (base.get("providers", {}) or {})
    if prov.get("openai", {}).get("model"):
        rc_oa = rc.model_copy(deep=True)
        rc_oa.run.provider = "openai"
        m_oa = C.apply_overrides(base, rc_oa)
        check.equal(m_oa["models"]["primary"], prov["openai"]["model"],
                    "non-claude run.provider swaps the primary model id")
        check.equal(m_oa["models"]["escalation"], prov["openai"]["model"],
                    "non-claude run.provider pins escalation to the same model")
        check.equal(m_oa["pricing_usd_per_mtok"]["primary_input"], prov["openai"]["pricing"]["input"],
                    "non-claude run.provider swaps primary input pricing")
    check.equal(merged["models"]["primary"], base["models"]["primary"],
                "claude run.provider leaves the primary model unchanged")

    # --- eval fingerprint: stable, and moves only on eval-affecting change ---
    fp1 = C.eval_fingerprint(rc, base)
    fp1_again = C.eval_fingerprint(C.load_runtime_config(), base)
    check.equal(fp1, fp1_again, "fingerprint is stable for the same config")

    rc_items = rc.model_copy(deep=True)
    rc_items.items_shown = 5  # a non-eval field
    check.equal(C.eval_fingerprint(rc_items, base), fp1,
                "fingerprint unchanged when a non-eval field changes")

    rc_prompt = rc.model_copy(deep=True)
    rc_prompt.run.prompt_version = "v1"  # an eval-affecting field
    check.require(C.eval_fingerprint(rc_prompt, base) != fp1,
                  "fingerprint changes when the prompt version changes")

    rc_run_provider = rc.model_copy(deep=True)
    rc_run_provider.run.provider = "openai"
    check.require(C.eval_fingerprint(rc_run_provider, base) != fp1,
                  "fingerprint changes when the RUN provider changes (the daily classifier)")

    rc_eval_provider = rc.model_copy(deep=True)
    rc_eval_provider.eval.provider = "openai"
    check.equal(C.eval_fingerprint(rc_eval_provider, base), fp1,
                "fingerprint is NOT moved by eval.provider alone (it describes the daily run)")

    check.note("offline check — no API calls, no spend")


if __name__ == "__main__":
    run("runtime_config.json contract", body)
