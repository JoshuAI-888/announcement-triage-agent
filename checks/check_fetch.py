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

    c.note(f"run 1: live EDGAR fetch, {len(config['watchlist'])} tickers, clean slate")
    run1 = fetch(config=config, db_path=db_path, raw_dir=raw_dir)
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
    c.note("run 2: identical fetch against the same store")
    run2 = fetch(config=config, db_path=db_path, raw_dir=raw_dir)
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

    # --- run 3: replay, so the zero is proved by dedupe, not by the watermark
    #
    # Run 2 legitimately returns zero, but the watermark filters the feed before
    # dedupe is ever consulted, so on its own it proves only that the filter
    # works. SPEC §12 requires more: the source re-delivers (at-least-once), and
    # re-running any window must be safe. Roll the watermark back to the
    # bootstrap point and replay the identical window — every record is
    # re-delivered, and only the announcement_id hash can stop it being written
    # a second time.
    store = Store(db_path)
    try:
        store.set_watermark(exchange, bootstrap_since)
    finally:
        store.close()

    c.note("run 3: watermark rolled back — the whole window is re-delivered")
    run3 = fetch(config=config, db_path=db_path, raw_dir=raw_dir)
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
        check_fetch_twice(c, tmp)
    check_real_store(c)


if __name__ == "__main__":
    run("A2 store + fetch", body)
