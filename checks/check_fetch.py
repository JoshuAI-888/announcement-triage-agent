"""A2 — store.py + fetch.py: one adapter, watermark, hash dedupe.

The acceptance criterion (SPEC.md §14 increment 2) is idempotency: run the
fetch twice, and **the second run must return zero new records**. This check
proves that against the live EDGAR feed from a clean slate — a throwaway
sqlite database and a throwaway raw directory — so the assertion is real on
every execution rather than only the first.

It also asserts the execution semantics in SPEC.md §12: append-only audit,
one watermark row per exchange, dead-letter capture, and that no announcement
is written to data/raw/ twice.

If EDGAR errors, blocks, throttles or requires authentication, tickers land in
the dead-letter table and this check fails deliberately. That is stop
condition S2 (AUTONOMY.md §4) — not something to work around.

Run:  python -m checks.check_fetch
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from checks._harness import Check, run

ROOT = Path(__file__).resolve().parent.parent
REAL_DB = ROOT / "state.db"
REAL_RAW = ROOT / "data" / "raw"


def check_store(c: Check, tmp: Path) -> None:
    """SPEC.md §12 execution semantics, against a throwaway database."""
    from src.store import Store

    store = Store(tmp / "unit.db")
    try:
        names = {
            row["name"]
            for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in ["processed", "watermark", "audit", "dead_letter"]:
            c.require(table in names, f"store creates table: {table}")

        now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

        # --- dedupe -------------------------------------------------------
        c.require(not store.is_processed("id-a"), "unseen announcement_id is not processed")
        store.mark_processed("id-a", "EDGAR", "AAPL", now)
        c.require(store.is_processed("id-a"), "marked announcement_id reads back as processed")
        store.mark_processed("id-a", "EDGAR", "AAPL", now)
        count = store.conn.execute("SELECT COUNT(*) FROM processed").fetchone()[0]
        c.equal(count, 1, "re-marking the same id does not create a second processed row")

        # --- watermark ----------------------------------------------------
        c.require(store.get_watermark("EDGAR") is None, "watermark is None before any successful run")
        store.set_watermark("EDGAR", now)
        c.equal(store.get_watermark("EDGAR"), now, "watermark round-trips as an aware UTC datetime")
        later = now + timedelta(hours=3)
        store.set_watermark("EDGAR", later)
        c.equal(store.get_watermark("EDGAR"), later, "watermark advances in place")
        rows = store.conn.execute("SELECT COUNT(*) FROM watermark WHERE exchange='EDGAR'").fetchone()[0]
        c.equal(rows, 1, "exactly one watermark row per exchange")

        # monotonic guard: an attempt to move the watermark BACKWARDS is a silent no-op
        # (defence-in-depth against a replay/backfill call site ever regressing it).
        store.set_watermark("EDGAR", now)  # earlier than `later`, already set above
        c.equal(store.get_watermark("EDGAR"), later, "set_watermark refuses to regress (monotonic guard)")

        # A naive datetime is a silent-timezone-bug generator; refuse it (SPEC §0.7).
        c.raises(
            ValueError,
            lambda: store.set_watermark("EDGAR", datetime(2026, 7, 1, 12, 0)),
            "store refuses a naive datetime",
        )

        # --- audit is append-only (SPEC.md §12) ---------------------------
        store.append_audit(announcement_id="id-a", decided_at=now, materiality="material", confidence=0.9)
        c.equal(
            store.conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0],
            1,
            "append_audit inserts a row",
        )
        c.raises(
            sqlite3.DatabaseError,
            lambda: store.conn.execute("UPDATE audit SET materiality='immaterial'"),
            "UPDATE against audit is refused (append-only)",
        )
        c.raises(
            sqlite3.DatabaseError,
            lambda: store.conn.execute("DELETE FROM audit"),
            "DELETE against audit is refused (append-only)",
        )

        # --- dead-letter ---------------------------------------------------
        store.add_dead_letter(error="boom", raw_payload={"ticker": "AAPL"}, announcement_id="id-a")
        row = store.conn.execute("SELECT * FROM dead_letter").fetchone()
        c.equal(row["error"], "boom", "dead_letter records the error")
        c.require(row["raw_payload"] is not None, "dead_letter keeps the raw payload")
    finally:
        store.close()


def check_classification_cache(c: Check, tmp: Path) -> None:
    """`classification_cache`: put/get round-trip, a miss, and prompt_version isolation."""
    from src.models import Announcement, Classification, Entities
    from src.store import Store

    store = Store(tmp / "cache.db")
    try:
        ann = Announcement(
            announcement_id="a" * 64, exchange="EDGAR", ticker="AAPL", company_name="AAPL Inc.",
            published_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc), headline="AAPL headline",
            doc_type="guidance_change", native_doc_type="8-K", native_id="acc-1",
            issuer_price_sensitive_flag=None, body_text="body", char_count=4, truncated=False,
            source_url="https://sec.gov/AAPL", fetched_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        )
        cls = Classification(
            announcement_id=ann.announcement_id, materiality="material", confidence=0.9,
            categories=["guidance_change"], evidence_quote="a grounded quote", rationale="rationale text",
            entities=Entities(), previously_disclosed=False, needs_human_review=False,
            model_id="claude-haiku-4-5-20251001", prompt_version="v1", cost_nzd=0.01,
            guardrail_flags=["G2_ungrounded_quote"], escalated=True,
        )

        c.require(store.get_cached_classification(ann.announcement_id, "v1") is None,
                  "a cache miss returns None")

        store.put_cached_classification(ann.announcement_id, "v1", cls)
        rehydrated = store.get_cached_classification(ann.announcement_id, "v1")
        c.require(rehydrated is not None, "a cached classification round-trips")
        c.equal(rehydrated, cls, "the rehydrated Classification is field-for-field identical")

        c.require(store.get_cached_classification(ann.announcement_id, "v2") is None,
                  "a different prompt_version for the same announcement_id is a separate cache entry (miss)")

        # updating the same (announcement_id, prompt_version) key overwrites, not duplicates
        cls_v2 = cls.model_copy(update={"materiality": "immaterial", "confidence": 0.5})
        store.put_cached_classification(ann.announcement_id, "v1", cls_v2)
        rows = store.conn.execute(
            "SELECT COUNT(*) FROM classification_cache WHERE announcement_id = ? AND prompt_version = 'v1'",
            (ann.announcement_id,),
        ).fetchone()[0]
        c.equal(rows, 1, "re-caching the same (announcement_id, prompt_version) key updates in place")
        c.equal(store.get_cached_classification(ann.announcement_id, "v1").materiality, "immaterial",
                "the updated cache entry reflects the latest put")
    finally:
        store.close()


def check_window_since_until(c: Check) -> None:
    """`since`/`until` window filtering, offline — no network.

    `EdgarAdapter._extract_filings` is exercised directly against a synthetic
    submissions-JSON payload spanning timestamps outside/inside `[since, until]`,
    asserting only the in-window ones survive (edgar.py's new upper-bound filter,
    threaded through `_extract_filings`).
    """
    from src.adapters.edgar import EdgarAdapter

    adapter = EdgarAdapter(watchlist=["AAPL"], user_agent="test-agent (test@example.com)",
                           timeout_seconds=10, rate_limit_rps=0)

    since = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc)

    # Four filings: before the window, at the since boundary (exclusive), inside
    # the window, and after the until boundary (exclusive).
    timestamps = [
        "2026-07-05T12:00:00.000Z",  # before since -> excluded
        "2026-07-10T00:00:00.000Z",  # exactly at since (<=) -> excluded (exclusive lower bound)
        "2026-07-12T09:30:00.000Z",  # inside the window -> included
        "2026-07-20T08:00:00.000Z",  # after until -> excluded
    ]
    data = {
        "name": "AAPL Inc.",
        "sicDescription": "Technology",
        "filings": {
            "recent": {
                "accessionNumber": [f"0001-{i}" for i in range(len(timestamps))],
                "form": ["8-K"] * len(timestamps),
                "acceptanceDateTime": timestamps,
                "filingDate": [t[:10] for t in timestamps],
                "reportDate": [t[:10] for t in timestamps],
                "primaryDocument": ["doc.htm"] * len(timestamps),
                "primaryDocDescription": ["desc"] * len(timestamps),
                "items": ["2.02"] * len(timestamps),
            }
        },
    }

    out = adapter._extract_filings("AAPL", "0000320193", data, since, until=until)
    c.equal(len(out), 1, "only the one in-window filing survives since/until filtering")
    c.equal(out[0]["published_at"], "2026-07-12T09:30:00+00:00", "the surviving filing is the in-window one")

    # No until -> only the lower bound applies (existing behaviour, unchanged).
    out_no_until = adapter._extract_filings("AAPL", "0000320193", data, since, until=None)
    c.equal(len(out_no_until), 2, "with no until, both post-since filings survive (12th and 20th)")


def check_fetch_twice(c: Check, tmp: Path) -> None:
    """The acceptance criterion: fetch twice from a clean slate, second run returns 0 new."""
    from src.fetch import fetch, load_config
    from src.models import Announcement
    from src.store import Store, parse_iso

    config = load_config()
    exchange = config["exchange"]["reference"]
    c.equal(exchange, "EDGAR", "reference exchange is EDGAR")

    db_path = tmp / "fetch.db"
    raw_dir = tmp / "raw"

    bootstrap_since = datetime.now(timezone.utc) - timedelta(
        days=config["exchange"]["bootstrap_lookback_days"]
    )

    # fetch()'s window is now lookback_days-driven for every call (default 1 day —
    # see src/fetch.py), not watermark/bootstrap-floored — `config` here is the raw
    # config.yaml with no `_runtime` overlay, so an omitted `since` would default to
    # just 1 day. Pass the wide bootstrap window explicitly so this network check
    # reliably finds records across the ~500-ticker watchlist rather than depending
    # on something having filed in the last 24h.
    c.note(f"run 1: live EDGAR fetch, {len(config['watchlist'])} tickers, clean slate, "
          f"explicit since={bootstrap_since.date().isoformat()} ({config['exchange']['bootstrap_lookback_days']}d)")
    run1 = fetch(config=config, db_path=db_path, raw_dir=raw_dir, since=bootstrap_since)
    first = run1.new
    c.require(first > 0, f"first run fetches new records (got {first})")
    c.equal(run1.duplicate, 0, "first run has nothing to deduplicate")
    c.require(run1.watermark_advanced, "first run advanced the watermark")

    # Any dead-lettered ticker means the source errored or blocked us: that is S2.
    store = Store(db_path)
    try:
        dead = store.conn.execute("SELECT error FROM dead_letter").fetchall()
        if dead:
            for row in dead[:5]:
                c.note(f"dead-letter: {row['error']}")
        c.equal(len(dead), 0, "no ticker was dead-lettered (a dead-letter here is stop condition S2)")

        watermark = store.get_watermark(exchange)
        c.require(watermark is not None, "watermark advanced after a fully successful run")

        processed = store.conn.execute("SELECT COUNT(*) FROM processed").fetchone()[0]
        c.equal(processed, first, "one processed row per new record")
    finally:
        store.close()

    files_after_first = sorted(p.name for p in raw_dir.glob("*.json"))
    c.equal(len(files_after_first), first, "one raw JSON written per new record")

    # --- the criterion --------------------------------------------------
    c.note("run 2: identical fetch (same explicit since) against the same store")
    run2 = fetch(config=config, db_path=db_path, raw_dir=raw_dir, since=bootstrap_since)
    c.equal(run2.new, 0, "SECOND RUN RETURNS ZERO NEW RECORDS (idempotency, SPEC §14 increment 2)")

    files_after_second = sorted(p.name for p in raw_dir.glob("*.json"))
    c.equal(files_after_second, files_after_first, "run 2 wrote no new raw files and overwrote none")

    store = Store(db_path)
    try:
        c.equal(
            store.conn.execute("SELECT COUNT(*) FROM processed").fetchone()[0],
            first,
            "run 2 added no processed rows",
        )
        c.equal(
            store.conn.execute("SELECT COUNT(*) FROM dead_letter").fetchone()[0],
            0,
            "run 2 dead-lettered nothing",
        )
        c.equal(
            store.conn.execute("SELECT COUNT(DISTINCT announcement_id) FROM processed").fetchone()[0],
            first,
            "every processed announcement_id is distinct",
        )
    finally:
        store.close()

    # --- run 3: replay, so the zero is proved by dedupe, not by the window
    #
    # Run 2 legitimately returns zero, but fetch()'s own window (now lookback_days-
    # driven, not watermark-floored — SPEC §12 / the lookback-window feature) filters
    # the feed before dedupe is ever consulted, so on its own it proves only that the
    # filter works. This still requires more: the source re-delivers (at-least-once),
    # and re-running any window must be safe. Pass an EXPLICIT `since` back at the
    # bootstrap point (fetch() no longer reads the watermark to compute its window at
    # all, so rolling the watermark back — the old mechanism — would have zero effect
    # under the new design; the explicit `since` param is the one lever that actually
    # widens the window now) and replay the identical range — every record is
    # re-delivered, and only the announcement_id hash can stop it being written a
    # second time.
    c.note("run 3: explicit since=bootstrap_since — the whole window is re-delivered")
    run3 = fetch(config=config, db_path=db_path, raw_dir=raw_dir, since=bootstrap_since)
    c.require(run3.seen >= first, f"replay re-delivered the whole window ({run3.seen} filings seen)")
    c.equal(run3.new, 0, "REPLAY RETURNS ZERO NEW RECORDS (hash dedupe, not the watermark)")
    c.equal(run3.duplicate, run3.seen, "every re-delivered filing was recognised as already processed")
    c.equal(
        sorted(p.name for p in raw_dir.glob("*.json")),
        files_after_first,
        "replay wrote no new raw files",
    )

    store = Store(db_path)
    try:
        c.equal(
            store.conn.execute("SELECT COUNT(*) FROM processed").fetchone()[0],
            first,
            "replay added no processed rows",
        )
    finally:
        store.close()

    # --- the ids are the documented hash, not an accident -----------------
    sample = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(raw_dir.glob("*.json"))[:25]]
    for raw in sample:
        recomputed = Announcement.compute_id(
            raw["exchange"], raw["ticker"], parse_iso(raw["published_at"]), raw["headline"], raw["accession_number"]
        )
        if recomputed != raw["announcement_id"]:
            c.equal(recomputed, raw["announcement_id"], f"stored id is the SPEC §5.1 hash ({raw['ticker']})")
    c.note(f"recomputed the SPEC §5.1 hash for {len(sample)} raw payloads — all match")
    c.require(
        all((raw_dir / f"{raw['announcement_id']}.json").is_file() for raw in sample),
        "each raw file is named for its announcement_id",
    )
    for field in ["exchange", "ticker", "published_at", "headline", "accession_number", "source_url", "form"]:
        c.require(all(raw.get(field) for raw in sample), f"raw payloads carry a non-empty {field}")
    c.require(
        all(parse_iso(raw["published_at"]).tzinfo is not None for raw in sample),
        "raw published_at parses to an aware datetime",
    )


def check_real_store(c: Check) -> None:
    """The build's own state.db and data/raw must satisfy the same invariants."""
    if not REAL_DB.is_file():
        c.note("state.db does not exist yet — skipping real-store invariants")
        return
    from src.store import Store

    store = Store(REAL_DB)
    try:
        processed = store.conn.execute("SELECT COUNT(*) FROM processed").fetchone()[0]
        distinct = store.conn.execute("SELECT COUNT(DISTINCT announcement_id) FROM processed").fetchone()[0]
        c.equal(distinct, processed, "state.db: every processed announcement_id is distinct")
        raw_files = list(REAL_RAW.glob("*.json")) if REAL_RAW.is_dir() else []
        c.equal(len(raw_files), processed, "state.db: one raw JSON per processed row")
        c.require(store.get_watermark("EDGAR") is not None, "state.db: EDGAR watermark is set")
        c.note(f"state.db holds {processed} processed announcement(s)")
    finally:
        store.close()


def body(c: Check) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        check_store(c, tmp)
        check_classification_cache(c, tmp)
        check_window_since_until(c)
        check_fetch_twice(c, tmp)
    check_real_store(c)


if __name__ == "__main__":
    run("A2 store + fetch", body)
