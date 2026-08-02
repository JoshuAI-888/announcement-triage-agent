"""export_candidates.py — write data/gold/candidates.csv, UNLABELLED.

SPEC.md §13.1 / AUTONOMY.md §5.1. This module exists to hand the owner a
labelling queue and nothing else. It writes the identifying columns of the gold
schema — which are facts copied from the canonical record — and leaves every
`label_*` column, plus `slice_tag`, `difficulty`, `labelled_at`, `labeller` and
`pass_number`, empty.

Those columns are not empty because they are unfinished. They are empty because
an agent-labelled gold set measures the agent against itself, which makes the
entire evaluation worthless. Filling them in is the owner's job, and the
stratification targets in SPEC.md §13.1 are the owner's call.

Row order is publication time, newest first. No ordering, filtering or emphasis
in this file encodes a view about whether an announcement matters.

Run:  python -m evals.export_candidates
"""

from __future__ import annotations

import csv
from pathlib import Path

from src.fetch import load_config
from src.models import Announcement
from src.normalise import normalise_all

ROOT = Path(__file__).resolve().parent.parent
GOLD_DIR = ROOT / "data" / "gold"
CANDIDATES_PATH = GOLD_DIR / "candidates.csv"

# SPEC.md §13.1, in order.
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

# Left empty by this exporter, always. See the module docstring.
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

# Appended after the gold schema so the owner can read and open each
# announcement while labelling. Source facts, not judgements.
CONTEXT_COLUMNS = ["headline", "native_doc_type", "char_count", "truncated", "source_url"]


def candidate_row(index: int, record: Announcement) -> dict[str, str]:
    """One canonical record -> one unlabelled candidate row."""
    row = {column: "" for column in GOLD_COLUMNS + CONTEXT_COLUMNS}
    row.update(
        {
            "id": str(index),
            "announcement_id": record.announcement_id,
            "exchange": record.exchange,
            "ticker": record.ticker,
            "published_at": record.published_at.isoformat(),
            "doc_type": record.doc_type,
            # EDGAR supplies no price-sensitive signal (SPEC §5.1), so this is
            # an absent source field rather than an unmade judgement.
            "issuer_price_sensitive_flag": "" if record.issuer_price_sensitive_flag is None
            else str(record.issuer_price_sensitive_flag).lower(),
            "headline": record.headline,
            "native_doc_type": record.native_doc_type,
            "char_count": str(record.char_count),
            "truncated": str(record.truncated).lower(),
            "source_url": record.source_url,
        }
    )
    for column in OWNER_ONLY_COLUMNS:
        row[column] = ""  # belt and braces: never populated, whatever changes above
    return row


def export(records: list[Announcement] | None = None, path: Path | None = None) -> Path:
    config = load_config()
    records = records if records is not None else normalise_all(config=config)
    # With a pin file the selection order is load-bearing: the pinned block must
    # keep the row ids it already has in a previously-exported candidates.csv.
    # Re-sorting here would renumber them and invalidate labelling in progress.
    if not config["normalise"].get("pin_file"):
        records = sorted(records, key=lambda r: (r.published_at, r.announcement_id), reverse=True)

    path = path or CANDIDATES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=GOLD_COLUMNS + CONTEXT_COLUMNS)
        writer.writeheader()
        for index, record in enumerate(records, start=1):
            writer.writerow(candidate_row(index, record))

    print(f"Wrote {len(records)} UNLABELLED candidate(s) to {path.relative_to(ROOT)}.")
    print(f"Empty and owner-only: {', '.join(OWNER_ONLY_COLUMNS)}.")
    return path


def main() -> None:
    export()


if __name__ == "__main__":
    main()
