"""A4 — export data/gold/candidates.csv, UNLABELLED.

SPEC.md §13.1 and AUTONOMY.md §5.1: the agent may export unlabelled candidate
rows and nothing else. Every `label_*` column, `slice_tag` and `difficulty`
stays empty. An agent-labelled gold set makes the entire evaluation worthless,
so the emptiness of those columns is the assertion this check exists for, and
it must hold on every row forever — including after the owner has built
`gold.csv` from these candidates.

The identifying columns (id, announcement_id, exchange, ticker, published_at,
doc_type, issuer_price_sensitive_flag) are source facts carried over from the
canonical record, not judgements, and are checked for accuracy against the
normalised corpus.

Run:  python -m checks.check_candidates
"""

from __future__ import annotations

import csv
import re
import typing
from pathlib import Path

from checks._harness import Check, run

ROOT = Path(__file__).resolve().parent.parent
GOLD_DIR = ROOT / "data" / "gold"
CANDIDATES = GOLD_DIR / "candidates.csv"

CATEGORIES = set(typing.get_args(__import__("src.models", fromlist=["Category"]).Category))

# SPEC.md §13.1 — the gold.csv column list, in order. candidates.csv must be a
# prefix-compatible superset so a gold set built by filling in the blanks has
# these columns in this order.
GOLD_COLUMNS = [
    "id",
    "announcement_id",
    "exchange",
    "ticker",
    "published_at",
    "doc_type",
    "issuer_price_sensitive_flag",
    "label_materiality",
    "label_categories",
    "label_evidence_span",
    "label_rationale",
    "slice_tag",
    "difficulty",
    "labelled_at",
    "labeller",
    "pass_number",
]

# Every column the agent is forbidden from populating (AUTONOMY.md §5.1).
# labelled_at / labeller / pass_number describe the labelling act itself, so
# they are the owner's to fill too.
OWNER_ONLY_COLUMNS = [
    "label_materiality",
    "label_categories",
    "label_evidence_span",
    "label_rationale",
    "slice_tag",
    "difficulty",
    "labelled_at",
    "labeller",
    "pass_number",
]

# Source-fact columns appended after the SPEC §13.1 set so the owner can read,
# find and open each announcement while labelling. None of these is a judgement.
CONTEXT_COLUMNS = ["headline", "native_doc_type", "char_count", "truncated", "source_url"]


def body(c: Check) -> None:
    from src.fetch import load_config

    config = load_config()
    watchlist = {t.upper() for t in config["watchlist"]}

    c.require(CANDIDATES.is_file(), "data/gold/candidates.csv exists")

    with CANDIDATES.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        rows = list(reader)

    c.equal(header[: len(GOLD_COLUMNS)], GOLD_COLUMNS, "header opens with the SPEC §13.1 columns, in order")
    c.equal(header[len(GOLD_COLUMNS) :], CONTEXT_COLUMNS, "header ends with the documented source-fact columns")

    c.require(len(rows) >= 60, f"at least 60 candidates to build an n=60 gold set from (got {len(rows)})")

    # --- THE POINT OF THIS CHECK ------------------------------------------
    # Every owner-only column empty, on every row. No exceptions, ever.
    populated: list[str] = []
    for row in rows:
        for column in OWNER_ONLY_COLUMNS:
            if (row[column] or "").strip() != "":
                populated.append(f"row id={row['id']} column={column} value={row[column]!r}")
    if populated:
        for entry in populated[:10]:
            c.note(entry)
    c.equal(len(populated), 0, "EVERY label column, slice_tag and difficulty is EMPTY on EVERY row")
    c.note(f"{len(OWNER_ONLY_COLUMNS)} owner-only columns x {len(rows)} rows verified empty")

    # --- identifying columns are accurate source facts ---------------------
    from src.normalise import normalise_all

    records = {r.announcement_id: r for r in normalise_all(config=config)}

    ids = [row["id"] for row in rows]
    c.equal(len(set(ids)), len(ids), "row ids are unique")
    c.equal(sorted(int(i) for i in ids), list(range(1, len(rows) + 1)), "row ids run 1..n")

    announcement_ids = [row["announcement_id"] for row in rows]
    c.equal(len(set(announcement_ids)), len(announcement_ids), "announcement_ids are unique")
    c.require(
        all(re.fullmatch(r"[0-9a-f]{64}", a) for a in announcement_ids),
        "every announcement_id is a sha256 hex digest",
    )

    unmatched = [a for a in announcement_ids if a not in records]
    c.equal(len(unmatched), 0, "every candidate corresponds to a normalised record in the corpus")

    for row in rows:
        record = records[row["announcement_id"]]
        problems = []
        if row["exchange"] != record.exchange:
            problems.append("exchange")
        if row["ticker"] != record.ticker or row["ticker"] not in watchlist:
            problems.append("ticker")
        if row["published_at"] != record.published_at.isoformat():
            problems.append("published_at")
        if row["doc_type"] != record.doc_type or row["doc_type"] not in CATEGORIES:
            problems.append("doc_type")
        if row["headline"] != record.headline:
            problems.append("headline")
        if row["source_url"] != record.source_url:
            problems.append("source_url")
        if row["char_count"] != str(record.char_count):
            problems.append("char_count")
        if problems:
            c.require(False, f"row id={row['id']}: disagrees with the corpus on {', '.join(problems)}")
    c.note(f"all {len(rows)} rows agree with the canonical record they point at")

    # EDGAR supplies no price-sensitive signal, so the column is empty — an
    # empty cell here is an absent source field, never an unmade judgement.
    c.require(
        all((row["issuer_price_sensitive_flag"] or "") == "" for row in rows),
        "issuer_price_sensitive_flag is empty for every row (EDGAR supplies no flag)",
    )

    # --- the owner's files are the owner's ---------------------------------
    for owner_file in ["gold.csv", "RUBRIC.md"]:
        path = GOLD_DIR / owner_file
        c.note(f"data/gold/{owner_file}: {'present (owner-written)' if path.is_file() else 'not present'}")

    c.note(
        f"{len(rows)} unlabelled candidates spanning "
        f"{len({row['ticker'] for row in rows})} issuers and "
        f"{len({row['doc_type'] for row in rows})} doc_types"
    )


if __name__ == "__main__":
    run("A4 unlabelled candidates export", body)
