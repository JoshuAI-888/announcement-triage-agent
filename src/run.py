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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from src.brief import render_brief
from src.classify import ClassifyError, classify
from src.config_schema import load_runtime_config, apply_overrides
from src.enrich import enrich
from src.fetch import DB_PATH, RAW_DIR, fetch, load_config
from src.flags import MATERIALITY_LABEL, doc_type_label, explain_flag
from src.models import Announcement
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
) -> dict:
    """Classify→verify→rank→brief over `records`. Returns ranked/needs-look/stats/brief_path."""
    prompt_version = prompt_version or config.get("prompt_version", "v1")
    now = now or datetime.now(timezone.utc)
    exchange = config["exchange"]["reference"]
    # Classify calls are I/O-bound; run them in a pool. This is the Anthropic-side
    # concurrency and is deliberately NOT the EDGAR fetch rate limit (that lives in fetch()).
    concurrency = max(1, int(config.get("eval", {}).get("concurrency", 8)))

    pairs = []
    processed = new = deduped = dead = escalations = off_watchlist = 0
    flag_counts: Counter = Counter()
    max_published: Optional[datetime] = None
    started = time.monotonic()

    # Idempotency first (SPEC §12): only classify genuinely-new records.
    to_process = [ann for ann in records if not store.is_audited(ann.announcement_id)]
    deduped = len(records) - len(to_process)

    def _try_classify(ann: Announcement):
        try:
            return ann, _classify_with_retries(ann, config, client, prompt_version, sleeper), None
        except Exception as exc:  # third failure → dead-letter (recorded in the main thread)
            return ann, None, exc

    # Concurrent classify (order preserved by .map); verify/audit/collect stay single-
    # threaded below because sqlite is single-writer.
    if concurrency > 1 and len(to_process) > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            classified = list(ex.map(_try_classify, to_process))
    else:
        classified = [_try_classify(ann) for ann in to_process]

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
        if c.escalated:
            escalations += 1
        for f in c.guardrail_flags:
            flag_counts[f] += 1
        pairs.append((c, ann))
        new += 1
        if max_published is None or ann.published_at > max_published:
            max_published = ann.published_at

    ranked, needs_look = rank(pairs, config, now)

    # Every classified (verified, non-dead-lettered) record this pass, regardless
    # of materiality — including the immaterial-and-clean records rank() itself
    # excludes from the brief. This is what out/filings/<date>.json and the "All
    # filings this run" table are built from (CONTRACTS.md — frozen shape).
    all_items: list[RankedItem] = []
    for c, ann in pairs:
        score, reason = score_one(c, ann, config, now)
        all_items.append(RankedItem(classification=c, announcement=ann, score=score, reason=reason))

    stats = {
        "processed": processed, "new": new, "deduped": deduped, "dead_letters": dead,
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
        brief_path = render_brief(ranked, needs_look, stats, all_items=all_items, brief_date=now.date())
        # Watermark advances only after a successful full run, never per item / never in dry-run.
        if max_published is not None:
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


def _filings_filename(now: datetime, kind: str) -> str:
    if kind == "intraday":
        return f"{now.date().isoformat()}T{now.hour:02d}-{now.minute:02d}.json"
    return f"{now.date().isoformat()}.json"


def write_filings_json(result: dict, kind: str, now: datetime, out_dir: Path | None = None) -> Path:
    """Write `out/filings/<date>.json` (or `<date>T<HH-MM>.json` for intraday) —
    the portal's own read path (CONTRACTS.md — frozen shape). One file per run."""
    out_dir = out_dir or FILINGS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = result["stats"]
    all_items: list[RankedItem] = result.get("all_items", [])
    payload = {
        "date": now.date().isoformat(),
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kind": kind,
        "counts": _filings_counts(stats, all_items),
        "filings": [_filing_row(it) for it in all_items],
    }
    path = out_dir / _filings_filename(now, kind)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def publish(
    result: dict,
    kind: str,
    now: datetime,
    config: dict,
    briefs_dir: Path | None = None,
    run_log_path: Path = RUN_LOG_PATH,
    filings_dir: Path | None = None,
    news_mode: str = "search",
) -> dict:
    """Render the HTML email brief, the out/filings/<date>.json portal feed, and
    append the run_log row for one run's result.

    Shared by the digest and `--intraday` CLI paths (CONTRACTS §6). `result` is a
    `run_pipeline()` return value; `kind` is `"digest"` or `"intraday"` (CONTRACTS
    §3). Adds `email_path` and `filings_path` to the returned dict.

    The digest email always gets the plain `<DATE>.email.html` name (a bare date
    is passed to `render_email`, regardless of what time of day the digest ran);
    the intraday alert gets the `<DATE>T<HH-MM>.email.html` name (the full `now`
    datetime is passed through) so repeated intraday alerts on the same day never
    collide (CONTRACTS §4). `out/filings/<date>.json` follows the identical naming
    rule.

    `config` carries the `market:`/provider blocks src.company / src.market need
    (both best-effort, never raise — a missing TWELVEDATA_API_KEY or provider
    outage never breaks a run).
    """
    stats = result["stats"]
    all_items = result.get("all_items", [])
    enrichment = enrich(result["ranked"], result["needs_look"], config, news_mode=news_mode)
    brief_date = now if kind == "intraday" else now.date()
    email_path = render_email(result["ranked"], result["needs_look"], stats, enrichment,
                              all_items=all_items, brief_date=brief_date, out_dir=briefs_dir)
    if kind == "digest":
        # Re-render the markdown brief now that enrichment (company/price) is
        # available — run_pipeline already wrote a plain-classification version
        # of this same file before publish() ever ran (SPEC §12: the brief must
        # not depend on network calls that can fail mid-run).
        render_brief(result["ranked"], result["needs_look"], stats, enrichment=enrichment,
                    all_items=all_items, brief_date=now.date(), out_dir=briefs_dir)
    filings_path = write_filings_json(result, kind, now, out_dir=filings_dir)
    append_run_log(_run_log_row(kind, stats, now), run_log_path)
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

    if since or until or args.dry_run:
        # Replay/backfill or a local dry-run: normalise the existing corpus, don't fetch
        # (keeps --dry-run's "no watermark advance" contract intact).
        records = _load_window(config, since, until)
    else:
        # Live incremental path (digest + intraday): pull new filings past the watermark,
        # then normalise only those. This is what runs on the CI runner each morning.
        fr = fetch(config)
        print(f"Fetch: {fr.new} new, {fr.duplicate} duplicate, {fr.seen} seen.")
        records = _load_new_records(config, fr.new_ids)

    store = Store(DB_PATH)
    now = datetime.now(timezone.utc)
    try:
        if args.intraday:
            # Material-only alert pass. dry_run=True so run_pipeline writes no digest brief
            # and doesn't touch the watermark; record_audit=False so alerting a record never
            # removes it from the morning digest. (fetch already advanced the watermark past
            # this window, which is correct — the 06:00 digest ran earlier in the day.)
            result = run_pipeline(records, config, client, store, prompt_version=rc.run.prompt_version,
                                  dry_run=True, now=now, record_audit=False)
            if result["ranked"]:
                result = publish(result, "intraday", now, config, news_mode=news_mode)
                print(f"Intraday alert: {len(result['ranked'])} new material item(s). "
                      f"Email: {result['email_path']}")
            else:
                print("Intraday: no new material item cleared guardrails this pass — nothing published.")
        else:
            result = run_pipeline(records, config, client, store, prompt_version=rc.run.prompt_version,
                                  dry_run=args.dry_run, now=now)
            if not args.dry_run:
                result = publish(result, "digest", now, config, news_mode=news_mode)
    finally:
        store.close()

    s = result["stats"]
    print(f"\nProcessed {s['processed']} ({s['new']} new, {s['deduped']} deduped, {s['dead_letters']} dead-lettered).")
    print(f"Ranked material: {len(result['ranked'])}; needs a look: {len(result['needs_look'])}.")
    print(f"Cost NZ${s['total_cost_nzd']:.4f}. " + ("(dry-run: no brief, no watermark)"
          if args.dry_run and not args.intraday else f"Brief: {result.get('brief_path')}"))


if __name__ == "__main__":
    main()
