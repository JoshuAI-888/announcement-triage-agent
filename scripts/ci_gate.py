"""ci_gate.py — the CI schedule decider (CONTRACTS.md §1 `schedule` block, §6 CLI).

A PURE, offline, stdlib-only function that turns `runtime_config.json`'s `schedule`
block plus the committed run history (`out/run_log.jsonl`, CONTRACTS.md §3) into one
of three actions for the `daily-brief.yml` workflow to take on each cron tick:

    decide(runtime_config, now_utc) -> {"action": "digest" | "intraday" | "skip", "reason": str}

Rules (schedule block: `poll_time_nzt`, `poll_frequency`, `intraday_alerts`):
  1. **digest** — the current NZT time is at/just past `poll_time_nzt` AND no digest
     has run yet on the current NZT calendar date (per `out/run_log.jsonl`). Digest
     always takes priority over intraday on the tick it is due.
  2. **intraday** — `intraday_alerts` is true AND `poll_frequency == "hourly"` (a
     "daily" cadence does not warrant an extra off-cycle look between digests) AND a
     digest is not due on this tick.
  3. **skip** — otherwise (before poll time with no intraday warranted, or digest
     already ran today and no intraday warranted).

No network, no imports outside the stdlib — this module must be trivially callable
from a check and from the workflow with nothing but Python 3.9+ (`zoneinfo`).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

NZT = ZoneInfo("Pacific/Auckland")

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_CONFIG_PATH = ROOT / "runtime_config.json"
RUN_LOG_PATH = ROOT / "out" / "run_log.jsonl"

DEFAULT_POLL_TIME = "06:00"
DEFAULT_POLL_FREQUENCY = "daily"
# Minimum gap between intraday passes so a */15 cron does not fire 4×/hour. Sized just
# under an hour so it lands on the tick closest to each hour when poll_frequency=hourly.
INTRADAY_MIN_GAP_MIN = 55


def _parse_hhmm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


def _to_nzt(dt: datetime) -> datetime:
    """Normalise any datetime (naive treated as UTC) to Pacific/Auckland local time."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(NZT)


def last_digest_date_nzt(run_log_path: Path = RUN_LOG_PATH) -> Optional[str]:
    """The latest NZT calendar date (YYYY-MM-DD) a `kind:"digest"` row completed on.

    CONTRACTS.md §3 documents a `date` field on each row but does not pin its
    timezone, and the schedule this gate serves is defined entirely in NZT — so
    "ran today" is computed here by converting each row's authoritative `ts` (UTC,
    the moment the run finished) to NZT ourselves, rather than trusting `date`'s
    unspecified timezone. See the CONTRACTS ambiguity note in the stream report.
    """
    if not run_log_path.exists():
        return None
    latest: Optional[str] = None
    with run_log_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") != "digest":
                continue
            ts = row.get("ts")
            if not isinstance(ts, str):
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            date_str = _to_nzt(dt).date().isoformat()
            if latest is None or date_str > latest:
                latest = date_str
    return latest


def last_run_dt(run_log_path: Path = RUN_LOG_PATH) -> Optional[datetime]:
    """The most recent run timestamp (UTC, tz-aware) across ALL run_log rows, digest or
    intraday — used to throttle intraday so it can't fire on every 15-minute tick."""
    if not run_log_path.exists():
        return None
    latest: Optional[datetime] = None
    with run_log_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                dt = datetime.fromisoformat(str(row["ts"]).replace("Z", "+00:00"))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if latest is None or dt > latest:
                latest = dt
    return latest


def decide(runtime_config: dict, now_utc: datetime, run_log_path: Path = RUN_LOG_PATH) -> dict:
    """Decide the CI action for this tick. Pure: no I/O except reading `run_log_path`."""
    schedule = runtime_config.get("schedule") or {}
    poll_time = schedule.get("poll_time_nzt", DEFAULT_POLL_TIME)
    poll_frequency = schedule.get("poll_frequency", DEFAULT_POLL_FREQUENCY)
    intraday_alerts = bool(schedule.get("intraday_alerts", False))

    now_nzt = _to_nzt(now_utc)
    poll_h, poll_m = _parse_hhmm(poll_time)
    today_nzt = now_nzt.date().isoformat()
    at_or_past_poll = (now_nzt.hour, now_nzt.minute) >= (poll_h, poll_m)

    digest_ran_today = last_digest_date_nzt(run_log_path) == today_nzt

    if at_or_past_poll and not digest_ran_today:
        return {
            "action": "digest",
            "reason": (
                f"NZT time {now_nzt:%H:%M} is at/after poll_time_nzt {poll_time} "
                f"and no digest has run yet today ({today_nzt})"
            ),
        }

    if intraday_alerts and poll_frequency == "hourly":
        last = last_run_dt(run_log_path)
        gap_min = None if last is None else (now_utc - last).total_seconds() / 60.0
        if last is None or gap_min >= INTRADAY_MIN_GAP_MIN:
            return {
                "action": "intraday",
                "reason": ("intraday_alerts on, poll_frequency=hourly, last run "
                           + ("never" if last is None else f"{int(gap_min)}min ago")
                           + f" (≥{INTRADAY_MIN_GAP_MIN}min gap)"),
            }
        return {
            "action": "skip",
            "reason": f"intraday throttled — last run {int(gap_min)}min ago (< {INTRADAY_MIN_GAP_MIN}min gap)",
        }

    if not intraday_alerts:
        if digest_ran_today:
            reason = f"digest already ran today ({today_nzt}) and intraday_alerts is off"
        else:
            reason = f"NZT time {now_nzt:%H:%M} is before poll_time_nzt {poll_time} and intraday_alerts is off"
        return {"action": "skip", "reason": reason}

    # intraday_alerts is on, but poll_frequency (e.g. "daily") does not warrant an
    # off-cycle check between digests.
    return {
        "action": "skip",
        "reason": f"intraday_alerts is on but poll_frequency={poll_frequency!r} does not warrant an off-cycle check",
    }


def _load_runtime_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=str(RUNTIME_CONFIG_PATH), help="path to runtime_config.json")
    parser.add_argument("--run-log", default=str(RUN_LOG_PATH), help="path to out/run_log.jsonl")
    parser.add_argument("--now", default=None, help="ISO8601 UTC timestamp override (testing only)")
    args = parser.parse_args()

    rc = _load_runtime_config(Path(args.config))
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
    result = decide(rc, now, Path(args.run_log))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
