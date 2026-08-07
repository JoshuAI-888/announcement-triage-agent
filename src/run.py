"""run.py — orchestrator + CLI (SPEC.md §7 flow, §12 semantics). Increment 8.

    python -m src.run                                    # incremental, lookback_days window
    python -m src.run --from 2026-07-01 --to 2026-07-28  # local-corpus replay (no fetch)
    python -m src.run --as-of 2026-08-02 --lookback-days 5  # backfill: real fetch, isolated, watermark untouched
    python -m src.run --dry-run                          # fetch + classify, no brief, no watermark advance
    python -m src.run --config runtime_config.json       # config-driven (CONTRACTS §6)
    python -m src.run --intraday                         # material-only alert pass, never advances the watermark

Pipeline: normalise → classify → verify → rank → brief. Every run is uniquely
identified (`run_id` = UTC execution time to the second) so reruns never clobber
a previous brief/filings artifact, and covers a configurable "last N days" window
(`schedule.lookback_days`) rather than an unbounded watermark floor. Records
already classified for the current prompt_version are REUSED from
`classification_cache` (0 LLM calls) rather than re-classified — see
`run_pipeline`. Append-only audit, two retries with 2s/8s backoff on transport +
G1 failures then dead-letter (the run continues — one bad announcement never
kills the brief), rate-limited between calls, watermark advanced only after a
successful full run and never in --dry-run or during a `--as-of` backfill
(isolated: a backfill re-fetches and reuses cache but never moves the live
watermark). Replay is first-class.

`run_pipeline` takes an injectable client / store / sleeper so the check drives the
whole thing offline with no network and no real sleeps.

The CLI is config-driven (CONTRACTS.md §6): `config.yaml` is the immutable base,
`runtime_config.json` (validated + merged by `src.config_schema`) is the UI-editable
overlay — provider, watchlist, thresholds, ranking, prompt version, lookback_days
all come from it. After a successful (non-dry-run) pass, `publish()` writes the
Milford HTML email brief (`src.render_email`, CONTRACTS §4) alongside the existing
markdown brief and appends one row to `out/run_log.jsonl` (CONTRACTS §3).
`--intraday` runs a material-only pass — a dry-run internally, so it never
advances the digest watermark — and only publishes (email + `kind:"intraday"`
run_log row) when at least one NEW record cleared guardrails as material this pass.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from src.brief import render_brief
from src.classify import ClassifyError, classify
from src.config_schema import load_runtime_config, apply_overrides
from src.enrich import enrich
from src.fetch import DB_PATH, RAW_DIR, fetch, load_config
from src.flags import KIND_LABEL, MATERIALITY_LABEL, doc_type_label, explain_flag
from src.models import Announcement, Classification
from src.rank import RankedItem, is_needs_a_look, rank, score_one
from src.render_email import render_email
from src.store import Store
from src.verify import verify

ROOT = Path(__file__).resolve().parent.parent
RUN_LOG_PATH = ROOT / "out" / "run_log.jsonl"
FILINGS_DIR = ROOT / "out" / "filings"

RETRYABLE: tuple[type[BaseException], ...] = (ClassifyError, ConnectionError, TimeoutError, OSError)
try:  # transport failures from the SDK
    from anthropic import APIError

    RETRYABLE = RETRYABLE + (APIError,)
except Exception:  # pragma: no cover
    pass

BACKOFF_SECONDS = [2, 8]  # two retries after the first attempt (SPEC §12)


def compute_run_id(now: datetime) -> str:
    """UTC execution time to the second, filesystem-safe: `YYYY-MM-DDTHH-MM-SS`.

    The single per-run identity: briefs, filings JSON, and the run_log row are
    all keyed by this so a rerun on the same day never overwrites a prior one.
    """
    return now.strftime("%Y-%m-%dT%H-%M-%S")


def _empty_window() -> dict:
    return {"as_of": None, "lookback_days": None, "since": None, "until": None}


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
    record_audit: bool = True,
    run_id: str | None = None,
    kind: str = "digest",
    window: dict | None = None,
) -> dict:
    """Classify→verify→rank→brief over `records`. Returns ranked/needs-look/stats/brief_path.

    Reuse, not skip (this replaces the old is_audited-skip idempotency): for
    every record, a `classification_cache` hit for the current prompt_version
    is REHYDRATED as-is (0 LLM calls, `stats["reused"]` counts it) rather than
    re-classified. `verify()` is NOT idempotent (it can duplicate guardrail
    flags if run twice on the same object), so a reused Classification — already
    verified when it was first cached — SKIPS re-verify entirely. Only a cache
    MISS goes through classify()->verify()->cache. Every window record (cached
    + freshly-classified) ends up in `pairs`/`all_items`, so the brief covers
    the whole window, not just this pass's new classifications.
    """
    prompt_version = prompt_version or config.get("prompt_version", "v1")
    now = now or datetime.now(timezone.utc)
    run_id = run_id or compute_run_id(now)
    window = window or _empty_window()
    exchange = config["exchange"]["reference"]
    # Classify calls are I/O-bound; run them in a pool. This is the Anthropic-side
    # concurrency and is deliberately NOT the EDGAR fetch rate limit (that lives in fetch()).
    concurrency = max(1, int(config.get("eval", {}).get("concurrency", 8)))

    pairs: list[tuple[Classification, Announcement]] = []
    processed = new = dead = escalations = off_watchlist = 0
    flag_counts: Counter = Counter()
    max_published: Optional[datetime] = None
    started = time.monotonic()

    # Reuse-from-cache (replaces the old is_audited skip): partition the window
    # into cache hits (rehydrate, 0 LLM calls) and cache misses (classify).
    reused_pairs: list[tuple[Classification, Announcement]] = []
    to_classify: list[Announcement] = []
    for ann in records:
        cached = store.get_cached_classification(ann.announcement_id, prompt_version)
        if cached is not None:
            reused_pairs.append((cached, ann))
        else:
            to_classify.append(ann)
    reused = len(reused_pairs)
    for c, ann in reused_pairs:
        if max_published is None or ann.published_at > max_published:
            max_published = ann.published_at

    def _try_classify(ann: Announcement):
        try:
            return ann, _classify_with_retries(ann, config, client, prompt_version, sleeper), None
        except Exception as exc:  # third failure → dead-letter (recorded in the main thread)
            return ann, None, exc

    # Concurrent classify (order preserved by .map); verify/audit/collect stay single-
    # threaded below because sqlite is single-writer.
    if concurrency > 1 and len(to_classify) > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            classified = list(ex.map(_try_classify, to_classify))
    else:
        classified = [_try_classify(ann) for ann in to_classify]

    for ann, c, exc in classified:
        processed += 1
        if exc is not None:
            store.add_dead_letter(error=f"classify failed: {exc}", announcement_id=ann.announcement_id,
                                  raw_payload={"ticker": ann.ticker, "headline": ann.headline})
            dead += 1
            continue

        v = verify(c, ann, config)
        if v is None:  # G4 dropped an off-watchlist record
            off_watchlist += 1
            continue
        c = v

        if record_audit:  # intraday passes False so an alert never consumes a record from the morning digest
            store.append_audit(
                announcement_id=ann.announcement_id, decided_at=now, materiality=c.materiality,
                confidence=c.confidence, prompt_version=prompt_version, model_id=c.model_id,
                escalated=c.escalated, guardrail_flags=c.guardrail_flags,
                input_tokens=c.input_tokens, output_tokens=c.output_tokens, cost_nzd=c.cost_nzd,
            )
            # Cache the exact post-verify object — the one that gets audited/ranked —
            # so a future reuse rehydrates byte-identical output (never re-verify it).
            store.put_cached_classification(ann.announcement_id, prompt_version, c)
        if c.escalated:
            escalations += 1
        for f in c.guardrail_flags:
            flag_counts[f] += 1
        pairs.append((c, ann))
        new += 1
        if max_published is None or ann.published_at > max_published:
            max_published = ann.published_at

    # Reused (cache-hit) records are counted for guardrail-flag stats too — they
    # are as much a part of "what's in this brief" as freshly classified ones —
    # but never re-verified (see docstring) and never re-audited (append-only;
    # they were already audited when first classified).
    for c, ann in reused_pairs:
        if c.escalated:
            escalations += 1
        for f in c.guardrail_flags:
            flag_counts[f] += 1

    pairs = reused_pairs + pairs

    ranked, needs_look = rank(pairs, config, now)

    # Every classified (verified, non-dead-lettered) record this pass, regardless
    # of materiality — including the immaterial-and-clean records rank() itself
    # excludes from the brief. This is what out/filings/<run_id>.json and the "All
    # filings this run" table are built from (CONTRACTS.md — frozen shape).
    all_items: list[RankedItem] = []
    for c, ann in pairs:
        score, reason = score_one(c, ann, config, now)
        all_items.append(RankedItem(classification=c, announcement=ann, score=score, reason=reason))

    stats = {
        "processed": processed, "new": new, "deduped": 0, "reused": reused, "dead_letters": dead,
        "dropped_offwatchlist": off_watchlist,
        "model_primary": config["models"]["primary"], "model_escalation": config["models"]["escalation"],
        "prompt_version": prompt_version, "escalation_count": escalations,
        "guardrail_flag_counts": dict(flag_counts),
        "material": len(ranked), "needs_look": len(needs_look),
        "total_cost_nzd": sum((c.cost_nzd or 0.0) for c, _ in pairs),
        "runtime_seconds": time.monotonic() - started,
    }

    brief_path: Optional[Path] = None
    if not dry_run:
        brief_path = render_brief(ranked, needs_look, stats, all_items=all_items, brief_date=now.date(),
                                  run_id=run_id, kind=kind, window=window)
        # Watermark advances only after a successful full run, never per item, never in
        # dry-run, and NEVER for a backfill (isolated by kind — a backfill covers a
        # historical window and must never move the live daily watermark, even though
        # it is not itself a dry-run and does write a brief).
        if kind != "backfill" and max_published is not None:
            store.set_watermark(exchange, max_published)

    return {
        "ranked": ranked, "needs_look": needs_look, "all_items": all_items,
        "stats": stats, "brief_path": brief_path,
    }


def _load_window(config: dict, since: datetime | None, until: datetime | None) -> list[Announcement]:
    """Replay/backfill: normalise the EXISTING corpus in a date window (--from/--to)."""
    from src.normalise import normalise_all

    records = normalise_all(config=config)
    if since:
        records = [r for r in records if r.published_at >= since]
    if until:
        records = [r for r in records if r.published_at <= until]
    return records


def _load_new_records(config: dict, new_ids: tuple[str, ...]) -> list[Announcement]:
    """Incremental daily path: normalise ONLY the filings this fetch pass just wrote.

    No gold-candidate sampler, no pin file — just the genuinely-new announcements, read
    from their raw payloads in data/raw/ and normalised one by one (body text is fetched
    + cached by the adapter). New ids are unprocessed by construction, so the pipeline's
    is_audited skip is a no-op for them.
    """
    import json

    from src.normalise import build_normalising_adapter, normalise_one

    adapter = build_normalising_adapter(config)
    records: list[Announcement] = []
    for aid in new_ids:
        path = RAW_DIR / f"{aid}.json"
        if not path.exists():
            continue
        try:
            records.append(normalise_one(json.loads(path.read_text(encoding="utf-8")), config, adapter))
        except Exception as exc:  # one bad filing never kills the brief
            print(f"WARNING: could not normalise {aid[:12]}: {exc}")
    return records


# --- publish: HTML email brief + run_log row (CONTRACTS §3, §4, §6) ---------

def _run_log_row(
    kind: str, stats: dict, now: datetime, run_id: str | None = None, window: dict | None = None,
) -> dict:
    """Build one `out/run_log.jsonl` row (CONTRACTS.md §3). `kind` is "digest"/"intraday"/"backfill"."""
    run_id = run_id or compute_run_id(now)
    window = window or _empty_window()
    return {
        "date": now.date().isoformat(),
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": run_id,
        "kind": kind,
        "processed": stats.get("processed", 0),
        "new": stats.get("new", 0),
        "deduped": stats.get("deduped", 0),
        "reused": stats.get("reused", 0),
        "material": stats.get("material", 0),
        "needs_look": stats.get("needs_look", 0),
        "escalations": stats.get("escalation_count", 0),
        "guardrail_flag_counts": stats.get("guardrail_flag_counts", {}),
        "total_cost_nzd": stats.get("total_cost_nzd", 0.0),
        "runtime_seconds": stats.get("runtime_seconds", 0.0),
        "prompt_version": stats.get("prompt_version", ""),
        "model_primary": stats.get("model_primary", ""),
        "window_days": window.get("lookback_days"),
        "as_of": window.get("as_of"),
    }


def append_run_log(row: dict, path: Path = RUN_LOG_PATH) -> None:
    """Append one JSON row to `out/run_log.jsonl` (append-only, CONTRACTS §3)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


# --- out/filings/<date>.json (the portal's own read path — frozen shape) ----

def _filing_row(item: RankedItem) -> dict:
    """One `filings[]` entry (frozen shape). Flags are ALWAYS pre-expanded to
    plain English via src.flags — a raw `G#_...` code must never reach this file."""
    c, ann = item.classification, item.announcement
    native_form = ann.native_doc_type.split(" [")[0]
    flags = [
        {"code": code, "label": explain_flag(code)["label"], "why": explain_flag(code)["why"]}
        for code in c.guardrail_flags
    ]
    return {
        "announcement_id": ann.announcement_id,
        "ticker": ann.ticker,
        "company_name": ann.company_name,
        "industry": ann.industry,
        "native_form": native_form,
        "doc_type": ann.doc_type,
        "doc_type_label": doc_type_label(ann.doc_type, native_form),
        "materiality": c.materiality,
        "materiality_label": MATERIALITY_LABEL.get(c.materiality, c.materiality),
        "confidence": c.confidence,
        "rationale": c.rationale,
        "flags": flags,
        "source_url": ann.source_url,
        "published_at": ann.published_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "score": item.score,
    }


def _filings_counts(stats: dict, all_items: list[RankedItem]) -> dict:
    """CONTRACTS.md `counts` block. `total_received` == every attempt this pass made
    (material + immaterial + needs_more_info + dropped_offwatchlist + dead_lettered
    sum back to it exactly — see run_pipeline's `processed` counter)."""
    material = sum(1 for it in all_items
                   if it.classification.materiality == "material" and not it.classification.guardrail_flags)
    needs_more_info = sum(1 for it in all_items if is_needs_a_look(it.classification))
    immaterial = sum(1 for it in all_items
                     if it.classification.materiality == "immaterial" and not it.classification.guardrail_flags)
    return {
        "total_received": stats.get("processed", 0),
        "material": material,
        "immaterial": immaterial,
        "needs_more_info": needs_more_info,
        "dropped_offwatchlist": stats.get("dropped_offwatchlist", 0),
        "dead_lettered": stats.get("dead_letters", 0),
    }


def _filings_filename(run_id: str) -> str:
    return f"{run_id}.json"


def write_filings_json(
    result: dict, kind: str, now: datetime, run_id: str, window: dict, out_dir: Path | None = None
) -> Path:
    """Write `out/filings/<run_id>.json` — the portal's own read path (CONTRACTS.md
    — frozen shape). One file per run; `run_id` (UTC execution time to the second)
    makes every run's filings file unique, for every kind (digest/intraday/backfill)."""
    out_dir = out_dir or FILINGS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = result["stats"]
    all_items: list[RankedItem] = result.get("all_items", [])
    payload = {
        "date": now.date().isoformat(),
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": run_id,
        "kind": kind,
        "window": window,
        "counts": _filings_counts(stats, all_items),
        "filings": [_filing_row(it) for it in all_items],
    }
    path = out_dir / _filings_filename(run_id)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def publish(
    result: dict,
    kind: str,
    now: datetime,
    config: dict,
    run_id: str,
    window: dict,
    briefs_dir: Path | None = None,
    run_log_path: Path = RUN_LOG_PATH,
    filings_dir: Path | None = None,
    news_mode: str = "search",
) -> dict:
    """Render the HTML email brief, the out/filings/<run_id>.json portal feed, and
    append the run_log row for one run's result.

    Shared by the digest, `--intraday`, and `--as-of` (backfill) CLI paths
    (CONTRACTS §6). `result` is a `run_pipeline()` return value; `kind` is
    `"digest"`, `"intraday"`, or `"backfill"` (CONTRACTS §3). Adds `email_path`
    and `filings_path` to the returned dict.

    Every kind is named by `run_id` (UTC execution time to the second) —
    `out/briefs/<run_id>.email.html`, `out/filings/<run_id>.json` — so reruns on
    the same day never clobber a previous brief. The markdown twin
    (`out/briefs/<run_id>.md`) is only re-rendered here for `kind == "digest"`,
    matching the existing "digest gets a markdown twin" behaviour — intraday and
    backfill still get their pre-enrichment markdown safety-net copy from
    `run_pipeline` itself (also now named by `run_id`).

    `config` carries the `market:`/provider blocks src.company / src.market need
    (both best-effort, never raise — a missing TWELVEDATA_API_KEY or provider
    outage never breaks a run).
    """
    stats = result["stats"]
    all_items = result.get("all_items", [])
    enrichment = enrich(result["ranked"], result["needs_look"], config, news_mode=news_mode)
    email_path = render_email(result["ranked"], result["needs_look"], stats, enrichment,
                              all_items=all_items, brief_date=now, run_id=run_id, kind=kind,
                              window=window, out_dir=briefs_dir)
    if kind == "digest":
        # Re-render the markdown brief now that enrichment (company/price) is
        # available — run_pipeline already wrote a plain-classification version
        # of this same file before publish() ever ran (SPEC §12: the brief must
        # not depend on network calls that can fail mid-run).
        render_brief(result["ranked"], result["needs_look"], stats, enrichment=enrichment,
                    all_items=all_items, brief_date=now.date(), run_id=run_id, kind=kind,
                    window=window, out_dir=briefs_dir)
    filings_path = write_filings_json(result, kind, now, run_id, window, out_dir=filings_dir)
    append_run_log(_run_log_row(kind, stats, now, run_id, window), run_log_path)
    return {**result, "email_path": email_path, "filings_path": filings_path}


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
    parser.add_argument("--as-of", dest="as_of_date", default=None,
                        help="ISO date (UTC); backfill window end. kind=backfill, isolated: real "
                             "fetch over [as_of - lookback_days, as_of end-of-day], reuses "
                             "classification_cache, NEVER advances the live watermark. run_id is "
                             "still the actual execution time, so it sorts as the latest run.")
    parser.add_argument("--lookback-days", dest="lookback_days_override", type=int, default=None,
                        help="override schedule.lookback_days for this run")
    args = parser.parse_args()

    base_config = load_config()
    rc_path = Path(args.config_path) if args.config_path else None
    rc = load_runtime_config(rc_path)
    config = apply_overrides(base_config, rc)

    from src.store import parse_iso

    since_arg = parse_iso(args.from_date) if args.from_date else None
    until_arg = parse_iso(args.to_date) if args.to_date else None

    from src.providers import build_client

    client = build_client(rc.run.provider, base_config)
    news_mode = config.get("_runtime", {}).get("news_mode", "search")

    now = datetime.now(timezone.utc)
    run_id = compute_run_id(now)

    schedule_lookback = config.get("_runtime", {}).get("schedule", {}).get("lookback_days", 1)
    lookback_days = args.lookback_days_override if args.lookback_days_override is not None else schedule_lookback

    if args.as_of_date:
        # Manual backfill / override — isolated as-of run (CONTRACTS §6, plan §4).
        # A REAL fetch against the historical window (not the local-corpus replay
        # path below), so filings not already in data/raw/ actually get pulled;
        # advance_watermark=False keeps it fully isolated from the live daily
        # watermark. run_id is still `now` (the actual execution time), so a
        # backfill sorts as the latest run in the portal.
        as_of_start = parse_iso(args.as_of_date)  # midnight UTC of that date
        until = as_of_start.replace(hour=23, minute=59, second=59)
        since = until - timedelta(days=lookback_days)
        kind = "backfill"
        window = {
            "as_of": as_of_start.date().isoformat(),
            "lookback_days": lookback_days,
            "since": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "until": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        fr = fetch(config, since=since, until=until, advance_watermark=False)
        print(f"Backfill fetch: {fr.new} new, {fr.duplicate} duplicate, {fr.seen} seen "
              f"(watermark untouched).")
        # The whole point of reuse-cache is that this window likely overlaps
        # filings already sitting in data/raw/ from an earlier daily run (cache-
        # eligible, but NOT in fr.new_ids since fetch's hash-dedup already saw
        # them) — load the full existing-corpus window, not just what this fetch
        # pass wrote as new, so the backfill brief covers cached + newly-fetched
        # filings alike.
        records = _load_window(config, since, until)
    elif since_arg or until_arg or args.dry_run:
        # Replay or a local dry-run: normalise the existing corpus, don't fetch
        # (keeps --dry-run's "no watermark advance" contract intact). Unaffected
        # by the lookback-window feature; kind is decided by the intraday/digest
        # branch below as before.
        kind = "digest"
        records = _load_window(config, since_arg, until_arg)
        window = {"as_of": None, "lookback_days": lookback_days, "since": None, "until": None}
    else:
        # Live incremental path (digest + intraday): pull filings in the last
        # lookback_days, then normalise only the ones this fetch pass wrote as new.
        # This is what runs on the CI runner each morning.
        kind = "digest"
        fr = fetch(config)
        print(f"Fetch: {fr.new} new, {fr.duplicate} duplicate, {fr.seen} seen.")
        records = _load_new_records(config, fr.new_ids)
        since_computed = now - timedelta(days=lookback_days)
        window = {
            "as_of": None,
            "lookback_days": lookback_days,
            "since": since_computed.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "until": None,
        }

    store = Store(DB_PATH)
    try:
        if args.intraday:
            # Material-only alert pass. dry_run=True so run_pipeline writes no digest brief
            # and doesn't touch the watermark; record_audit=False so alerting a record never
            # removes it from the morning digest. (fetch already advanced the watermark past
            # this window, which is correct — the 06:00 digest ran earlier in the day.)
            result = run_pipeline(records, config, client, store, prompt_version=rc.run.prompt_version,
                                  dry_run=True, now=now, record_audit=False,
                                  run_id=run_id, kind="intraday", window=window)
            if result["ranked"]:
                result = publish(result, "intraday", now, config, run_id, window, news_mode=news_mode)
                print(f"Intraday alert: {len(result['ranked'])} new material item(s). "
                      f"Email: {result['email_path']}")
            else:
                print("Intraday: no new material item cleared guardrails this pass — nothing published.")
        elif kind == "backfill":
            result = run_pipeline(records, config, client, store, prompt_version=rc.run.prompt_version,
                                  dry_run=args.dry_run, now=now, run_id=run_id, kind="backfill", window=window)
            if not args.dry_run:
                # run_pipeline itself never advances the watermark for kind="backfill"
                # (isolated — see run_pipeline's own guard); publish() only writes artifacts.
                result = publish(result, "backfill", now, config, run_id, window, news_mode=news_mode)
        else:
            result = run_pipeline(records, config, client, store, prompt_version=rc.run.prompt_version,
                                  dry_run=args.dry_run, now=now, run_id=run_id, kind="digest", window=window)
            if not args.dry_run:
                result = publish(result, "digest", now, config, run_id, window, news_mode=news_mode)
    finally:
        store.close()

    s = result["stats"]
    print(f"\nRun {run_id} ({KIND_LABEL.get(kind, kind)}).")
    print(f"Processed {s['processed']} ({s['new']} new, {s['reused']} reused, {s['dead_letters']} dead-lettered).")
    print(f"Ranked material: {len(result['ranked'])}; needs a look: {len(result['needs_look'])}.")
    print(f"Cost NZ${s['total_cost_nzd']:.4f}. " + ("(dry-run: no brief, no watermark)"
          if args.dry_run and not args.intraday else f"Brief: {result.get('brief_path')}"))


if __name__ == "__main__":
    main()
