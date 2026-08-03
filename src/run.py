"""run.py — orchestrator + CLI (SPEC.md §7 flow, §12 semantics). Increment 8.

    python -m src.run                                    # incremental from watermark
    python -m src.run --from 2026-07-01 --to 2026-07-28  # backfill / replay
    python -m src.run --dry-run                          # fetch + classify, no brief, no watermark advance
    python -m src.run --config runtime_config.json       # config-driven (CONTRACTS §6)
    python -m src.run --intraday                         # material-only alert pass, never advances the watermark

Pipeline: normalise → classify → verify → rank → brief. Idempotent (an already-
audited announcement is skipped), append-only audit, two retries with 2s/8s backoff
on transport + G1 failures then dead-letter (the run continues — one bad
announcement never kills the brief), rate-limited between calls, watermark advanced
only after a successful full run and never in --dry-run. Replay is first-class.

`run_pipeline` takes an injectable client / store / sleeper so the check drives the
whole thing offline with no network and no real sleeps.

The CLI is config-driven (CONTRACTS.md §6): `config.yaml` is the immutable base,
`runtime_config.json` (validated + merged by `src.config_schema`) is the UI-editable
overlay — provider, watchlist, thresholds, ranking, prompt version all come from it.
After a successful (non-dry-run) pass, `publish()` writes the Milford HTML email
brief (`src.render_email`, CONTRACTS §4) alongside the existing markdown brief and
appends one row to `out/run_log.jsonl` (CONTRACTS §3). `--intraday` runs a
material-only pass — a dry-run internally, so it never advances the digest
watermark — and only publishes (email + `kind:"intraday"` run_log row) when at
least one NEW record cleared guardrails as material this pass.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from src.brief import render_brief
from src.classify import ClassifyError, classify
from src.config_schema import load_runtime_config, apply_overrides
from src.enrich import enrich
from src.fetch import DB_PATH, load_config
from src.models import Announcement
from src.rank import rank
from src.render_email import render_email
from src.store import Store
from src.verify import verify

ROOT = Path(__file__).resolve().parent.parent
RUN_LOG_PATH = ROOT / "out" / "run_log.jsonl"

RETRYABLE: tuple[type[BaseException], ...] = (ClassifyError, ConnectionError, TimeoutError, OSError)
try:  # transport failures from the SDK
    from anthropic import APIError

    RETRYABLE = RETRYABLE + (APIError,)
except Exception:  # pragma: no cover
    pass

BACKOFF_SECONDS = [2, 8]  # two retries after the first attempt (SPEC §12)


def _classify_with_retries(ann, config, client, prompt_version, sleeper) -> object:
    """classify with two retries on transport/G1 failures; raises after the third."""
    last: Optional[BaseException] = None
    for attempt in range(len(BACKOFF_SECONDS) + 1):
        if attempt:
            sleeper(BACKOFF_SECONDS[attempt - 1])
        try:
            return classify(ann, config=config, prompt_version=prompt_version, client=client)
        except RETRYABLE as exc:
            last = exc
    raise last  # type: ignore[misc]


def run_pipeline(
    records: list[Announcement],
    config: dict,
    client,
    store: Store,
    prompt_version: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict:
    """Classify→verify→rank→brief over `records`. Returns ranked/needs-look/stats/brief_path."""
    prompt_version = prompt_version or config.get("prompt_version", "v1")
    now = now or datetime.now(timezone.utc)
    rps = config["exchange"]["rate_limit_requests_per_second"]
    exchange = config["exchange"]["reference"]

    pairs = []
    processed = new = deduped = dead = escalations = 0
    flag_counts: Counter = Counter()
    max_published: Optional[datetime] = None
    started = time.monotonic()

    for ann in records:
        if store.is_audited(ann.announcement_id):  # idempotency (SPEC §12)
            deduped += 1
            continue
        processed += 1
        if rps:
            sleeper(1.0 / rps)  # rate limit
        try:
            c = _classify_with_retries(ann, config, client, prompt_version, sleeper)
        except Exception as exc:  # third failure → dead-letter, run continues
            store.add_dead_letter(error=f"classify failed: {exc}", announcement_id=ann.announcement_id,
                                  raw_payload={"ticker": ann.ticker, "headline": ann.headline})
            dead += 1
            continue

        v = verify(c, ann, config)
        if v is None:  # G4 dropped an off-watchlist record
            continue
        c = v

        store.append_audit(
            announcement_id=ann.announcement_id, decided_at=now, materiality=c.materiality,
            confidence=c.confidence, prompt_version=prompt_version, model_id=c.model_id,
            escalated=c.escalated, guardrail_flags=c.guardrail_flags,
            input_tokens=c.input_tokens, output_tokens=c.output_tokens, cost_nzd=c.cost_nzd,
        )
        if c.escalated:
            escalations += 1
        for f in c.guardrail_flags:
            flag_counts[f] += 1
        pairs.append((c, ann))
        new += 1
        if max_published is None or ann.published_at > max_published:
            max_published = ann.published_at

    ranked, needs_look = rank(pairs, config, now)
    stats = {
        "processed": processed, "new": new, "deduped": deduped, "dead_letters": dead,
        "model_primary": config["models"]["primary"], "model_escalation": config["models"]["escalation"],
        "prompt_version": prompt_version, "escalation_count": escalations,
        "guardrail_flag_counts": dict(flag_counts),
        "material": len(ranked), "needs_look": len(needs_look),
        "total_cost_nzd": sum((c.cost_nzd or 0.0) for c, _ in pairs),
        "runtime_seconds": time.monotonic() - started,
    }

    brief_path: Optional[Path] = None
    if not dry_run:
        brief_path = render_brief(ranked, needs_look, stats, now.date())
        # Watermark advances only after a successful full run, never per item / never in dry-run.
        if max_published is not None:
            store.set_watermark(exchange, max_published)

    return {"ranked": ranked, "needs_look": needs_look, "stats": stats, "brief_path": brief_path}


def _load_window(config: dict, since: datetime | None, until: datetime | None) -> list[Announcement]:
    from src.normalise import normalise_all

    records = normalise_all(config=config)
    if since:
        records = [r for r in records if r.published_at >= since]
    if until:
        records = [r for r in records if r.published_at <= until]
    return records


# --- publish: HTML email brief + run_log row (CONTRACTS §3, §4, §6) ---------

def _run_log_row(kind: str, stats: dict, now: datetime, dashboard_url: str | None = None) -> dict:
    """Build one `out/run_log.jsonl` row (CONTRACTS.md §3). `kind` is "digest" or "intraday"."""
    return {
        "date": now.date().isoformat(),
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kind": kind,
        "processed": stats.get("processed", 0),
        "new": stats.get("new", 0),
        "deduped": stats.get("deduped", 0),
        "material": stats.get("material", 0),
        "needs_look": stats.get("needs_look", 0),
        "escalations": stats.get("escalation_count", 0),
        "guardrail_flag_counts": stats.get("guardrail_flag_counts", {}),
        "total_cost_nzd": stats.get("total_cost_nzd", 0.0),
        "runtime_seconds": stats.get("runtime_seconds", 0.0),
        "prompt_version": stats.get("prompt_version", ""),
        "model_primary": stats.get("model_primary", ""),
        "dashboard_url": dashboard_url,
    }


def append_run_log(row: dict, path: Path = RUN_LOG_PATH) -> None:
    """Append one JSON row to `out/run_log.jsonl` (append-only, CONTRACTS §3)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def publish(
    result: dict,
    kind: str,
    now: datetime,
    briefs_dir: Path | None = None,
    run_log_path: Path = RUN_LOG_PATH,
    news_mode: str = "search",
) -> dict:
    """Render the HTML email brief and append the run_log row for one run's result.

    Shared by the digest and `--intraday` CLI paths (CONTRACTS §6). `result` is a
    `run_pipeline()` return value; `kind` is `"digest"` or `"intraday"` (CONTRACTS
    §3). Adds `email_path` to the returned dict.

    The digest email always gets the plain `<DATE>.email.html` name (a bare date
    is passed to `render_email`, regardless of what time of day the digest ran);
    the intraday alert gets the `<DATE>T<HH-MM>.email.html` name (the full `now`
    datetime is passed through) so repeated intraday alerts on the same day never
    collide (CONTRACTS §4).
    """
    stats = result["stats"]
    enrichment = enrich(result["ranked"], news_mode=news_mode)
    brief_date = now if kind == "intraday" else now.date()
    email_path = render_email(result["ranked"], result["needs_look"], stats, enrichment,
                              brief_date=brief_date, out_dir=briefs_dir)
    append_run_log(_run_log_row(kind, stats, now), run_log_path)
    return {**result, "email_path": email_path}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="from_date", default=None, help="ISO date; replay window start")
    parser.add_argument("--to", dest="to_date", default=None, help="ISO date; replay window end")
    parser.add_argument("--dry-run", action="store_true", help="classify but write no brief and no watermark")
    parser.add_argument("--config", dest="config_path", default=None,
                        help="runtime_config.json path (default: repo root)")
    parser.add_argument("--intraday", action="store_true",
                        help="material-only alert pass: HTML brief + run_log row only when a NEW "
                             "record cleared guardrails as material this pass; never advances the "
                             "digest watermark")
    args = parser.parse_args()

    base_config = load_config()
    rc_path = Path(args.config_path) if args.config_path else None
    rc = load_runtime_config(rc_path)
    config = apply_overrides(base_config, rc)

    from src.store import parse_iso

    since = parse_iso(args.from_date) if args.from_date else None
    until = parse_iso(args.to_date) if args.to_date else None

    from src.providers import build_client

    client = build_client(rc.run.provider, base_config)
    news_mode = config.get("_runtime", {}).get("news_mode", "search")

    records = _load_window(config, since, until)
    store = Store(DB_PATH)
    now = datetime.now(timezone.utc)
    try:
        if args.intraday:
            # Internally always a dry-run: idempotency (store.is_audited) means only
            # genuinely NEW records are classified/ranked this pass, and dry_run=True
            # guarantees the digest watermark never advances from an intraday pass.
            result = run_pipeline(records, config, client, store, prompt_version=rc.run.prompt_version,
                                  dry_run=True, now=now)
            if result["ranked"]:
                result = publish(result, "intraday", now, news_mode=news_mode)
                print(f"Intraday alert: {len(result['ranked'])} new material item(s). "
                      f"Email: {result['email_path']}")
            else:
                print("Intraday: no new material item cleared guardrails this pass — nothing published.")
        else:
            result = run_pipeline(records, config, client, store, prompt_version=rc.run.prompt_version,
                                  dry_run=args.dry_run, now=now)
            if not args.dry_run:
                result = publish(result, "digest", now, news_mode=news_mode)
    finally:
        store.close()

    s = result["stats"]
    print(f"\nProcessed {s['processed']} ({s['new']} new, {s['deduped']} deduped, {s['dead_letters']} dead-lettered).")
    print(f"Ranked material: {len(result['ranked'])}; needs a look: {len(result['needs_look'])}.")
    print(f"Cost NZ${s['total_cost_nzd']:.4f}. " + ("(dry-run: no brief, no watermark)"
          if args.dry_run and not args.intraday else f"Brief: {result.get('brief_path')}"))


if __name__ == "__main__":
    main()
