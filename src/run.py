"""run.py — orchestrator + CLI (SPEC.md §7 flow, §12 semantics). Increment 8.

    python -m src.run                                    # incremental from watermark
    python -m src.run --from 2026-07-01 --to 2026-07-28  # backfill / replay
    python -m src.run --dry-run                          # fetch + classify, no brief, no watermark advance

Pipeline: normalise → classify → verify → rank → brief. Idempotent (an already-
audited announcement is skipped), append-only audit, two retries with 2s/8s backoff
on transport + G1 failures then dead-letter (the run continues — one bad
announcement never kills the brief), rate-limited between calls, watermark advanced
only after a successful full run and never in --dry-run. Replay is first-class.

`run_pipeline` takes an injectable client / store / sleeper so the check drives the
whole thing offline with no network and no real sleeps.
"""

from __future__ import annotations

import argparse
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from src.brief import render_brief
from src.classify import ClassifyError, classify
from src.fetch import DB_PATH, load_config
from src.models import Announcement
from src.rank import rank
from src.store import Store
from src.verify import verify

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="from_date", default=None, help="ISO date; replay window start")
    parser.add_argument("--to", dest="to_date", default=None, help="ISO date; replay window end")
    parser.add_argument("--dry-run", action="store_true", help="classify but write no brief and no watermark")
    args = parser.parse_args()

    config = load_config()
    from src.store import parse_iso

    since = parse_iso(args.from_date) if args.from_date else None
    until = parse_iso(args.to_date) if args.to_date else None

    from anthropic import Anthropic

    records = _load_window(config, since, until)
    store = Store(DB_PATH)
    try:
        result = run_pipeline(records, config, Anthropic(), store, dry_run=args.dry_run)
    finally:
        store.close()

    s = result["stats"]
    print(f"\nProcessed {s['processed']} ({s['new']} new, {s['deduped']} deduped, {s['dead_letters']} dead-lettered).")
    print(f"Ranked material: {len(result['ranked'])}; needs a look: {len(result['needs_look'])}.")
    print(f"Cost NZ${s['total_cost_nzd']:.4f}. " + ("(dry-run: no brief, no watermark)"
          if args.dry_run else f"Brief: {result['brief_path']}"))


if __name__ == "__main__":
    main()
