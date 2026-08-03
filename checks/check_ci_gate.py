"""check_ci_gate.py — the CI schedule decider (Stream C, offline, no network, no spend).

Guards `scripts/ci_gate.py:decide()` against the schedule block in CONTRACTS.md §1:
  - before poll_time_nzt with no intraday warranted -> skip
  - at/after poll_time_nzt, no digest run yet today -> digest
  - digest already ran today: intraday_alerts + poll_frequency=hourly -> intraday;
    otherwise -> skip
  - intraday_alerts off -> NEVER intraday, at any time of day or poll_frequency
  - `last_digest_date_nzt` reads `ts` (not the timezone-unspecified `date` field),
    tolerates a missing/empty run_log, and skips malformed lines
  - the CLI (`python -m scripts.ci_gate`) round-trips through argv/stdout as JSON
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from checks._harness import run
from scripts import ci_gate as G

ROOT = Path(__file__).resolve().parent.parent
NZT = ZoneInfo("Pacific/Auckland")


def _nzt(y, m, d, h, mi) -> datetime:
    """Build a UTC datetime whose Pacific/Auckland local time is exactly y-m-d h:mi."""
    return datetime(y, m, d, h, mi, tzinfo=NZT).astimezone(timezone.utc)


def _write_log(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "run_log.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return p


def _digest_row(ts_utc: datetime) -> dict:
    return {
        "date": ts_utc.date().isoformat(), "ts": ts_utc.isoformat().replace("+00:00", "Z"),
        "kind": "digest", "processed": 10, "new": 2, "deduped": 8, "material": 1, "needs_look": 0,
        "escalations": 0, "guardrail_flag_counts": {}, "total_cost_nzd": 0.1, "runtime_seconds": 5.0,
        "prompt_version": "v3", "model_primary": "claude-haiku-4-5-20251001", "dashboard_url": None,
    }


def _schedule(poll_time="06:00", poll_frequency="daily", intraday_alerts=False) -> dict:
    return {
        "schedule": {
            "poll_time_nzt": poll_time, "poll_frequency": poll_frequency, "intraday_alerts": intraday_alerts,
        }
    }


def body(check):
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        empty_log = _write_log(tmp, [])

        # --- 1. before poll_time_nzt, nothing warrants an off-cycle check -> skip ---
        rc = _schedule("06:00", "daily", False)
        now = _nzt(2026, 8, 4, 3, 0)  # 03:00 NZT, well before 06:00
        result = G.decide(rc, now, empty_log)
        check.equal(result["action"], "skip", "before poll_time_nzt -> skip")
        check.require("before poll_time_nzt" in result["reason"], "skip reason cites poll_time_nzt")

        # --- 2. at/after poll_time_nzt, no digest run yet today -> digest ---
        now = _nzt(2026, 8, 4, 6, 5)  # just past 06:00 NZT
        result = G.decide(rc, now, empty_log)
        check.equal(result["action"], "digest", "at/after poll_time_nzt with none run today -> digest")
        check.require("no digest has run yet today" in result["reason"], "digest reason cites no run yet today")

        # exactly at poll_time_nzt also counts (>=), not only strictly after
        now = _nzt(2026, 8, 4, 6, 0)
        check.equal(G.decide(rc, now, empty_log)["action"], "digest", "exactly at poll_time_nzt -> digest")

        # --- 3. digest already ran today, intraday off -> skip ---
        log_today = _write_log(tmp, [_digest_row(_nzt(2026, 8, 4, 6, 2))])
        now = _nzt(2026, 8, 4, 9, 0)  # later the same NZT day
        rc_off = _schedule("06:00", "hourly", False)
        result = G.decide(rc_off, now, log_today)
        check.equal(result["action"], "skip", "digest already ran today + intraday off -> skip")
        check.require("already ran today" in result["reason"], "skip reason cites already ran today")

        # --- 4. digest already ran today, intraday on + hourly -> intraday ---
        rc_hourly = _schedule("06:00", "hourly", True)
        result = G.decide(rc_hourly, now, log_today)
        check.equal(result["action"], "intraday", "already ran today + intraday_alerts + hourly -> intraday")
        check.require("hourly" in result["reason"], "intraday reason cites hourly cadence")

        # --- 4b. intraday THROTTLE: a recent run (< gap) suppresses the every-15-min fire ---
        log_recent = _write_log(tmp, [_digest_row(_nzt(2026, 8, 4, 8, 50))])  # 10 min before 09:00
        result = G.decide(rc_hourly, now, log_recent)
        check.equal(result["action"], "skip", "intraday throttled when the last run was < 55min ago")
        check.require("throttled" in result["reason"], "throttle reason says throttled")
        # exactly at/after the gap it fires again
        result = G.decide(rc_hourly, _nzt(2026, 8, 4, 9, 46), log_recent)  # 56 min after 08:50
        check.equal(result["action"], "intraday", "intraday fires again once the 55min gap has passed")

        # --- 5. digest already ran today, intraday on but poll_frequency=daily -> skip ---
        rc_daily_intraday = _schedule("06:00", "daily", True)
        result = G.decide(rc_daily_intraday, now, log_today)
        check.equal(result["action"], "skip", "poll_frequency=daily does not warrant an off-cycle check")
        check.require("daily" in result["reason"], "skip reason cites poll_frequency")

        # --- 6. intraday_alerts off => NEVER intraday, across times/frequencies ---
        for pf in ("daily", "hourly"):
            for hh, mm, log in ((3, 0, empty_log), (9, 0, log_today)):
                rc_never = _schedule("06:00", pf, False)
                action = G.decide(rc_never, _nzt(2026, 8, 4, hh, mm), log)["action"]
                check.require(action != "intraday", f"intraday_alerts off never fires intraday (pf={pf}, {hh:02d}:{mm:02d})")
        check.note("intraday_alerts is a hard gate: off means off, regardless of cadence or time of day")

        # --- last_digest_date_nzt: robustness ---
        check.require(G.last_digest_date_nzt(tmp / "does-not-exist.jsonl") is None,
                      "missing run_log -> no last digest date (never fails)")

        messy = tmp / "messy.jsonl"
        messy.write_text(
            "\n"  # blank line
            "not json at all\n"  # malformed line
            + json.dumps({"kind": "intraday", "ts": "2026-08-04T20:00:00Z"}) + "\n"  # ignored: not a digest
            + json.dumps(_digest_row(_nzt(2026, 8, 3, 6, 0))) + "\n"  # digest on an earlier NZT day
            + json.dumps(_digest_row(_nzt(2026, 8, 4, 6, 0))) + "\n",  # digest today (the latest)
            encoding="utf-8",
        )
        check.equal(G.last_digest_date_nzt(messy), "2026-08-04",
                    "picks the latest NZT digest date, ignoring blank/malformed/non-digest lines")

        # --- the CLI round-trips through argv/stdout as JSON ---
        cfg_path = tmp / "runtime_config.json"
        cfg_path.write_text(json.dumps(rc), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.ci_gate", "--config", str(cfg_path),
             "--run-log", str(empty_log), "--now", "2026-08-04T18:05:00Z"],  # 06:05 NZT (NZST, UTC+12)
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        check.equal(proc.returncode, 0, "CLI exits 0")
        payload = json.loads(proc.stdout.strip())
        check.equal(payload["action"], "digest", "CLI prints the same decision as decide() for the equivalent inputs")

        check.note("offline check — no API calls, no network, no spend")


if __name__ == "__main__":
    run("ci_gate.py schedule decider", body)
