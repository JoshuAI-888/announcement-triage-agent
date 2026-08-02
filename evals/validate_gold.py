"""validate_gold.py — the GOLD_REQUIREMENTS.md §F gate, as an executable check.

The human gate in AUTONOMY.md §7 is currently prose: sixty rows of requirements
in GOLD_REQUIREMENTS.md that a person has to hold in their head while labelling.
This turns §A–§D into one command, so the owner can see exactly which rows are
wrong and why, and B1 can start on a machine-verified gate rather than a
believed one.

It validates. It does not label, repair, fill, or suggest a value for any
`label_*`, `slice_tag` or `difficulty` cell — those are the owner's, and an
agent-written gold set measures the agent against itself (AUTONOMY.md §5.1).
Nothing here writes to data/gold/.

Deliberately NOT registered in checks/run_all.py: it fails until the owner has
labelled, and a permanently-red run_all trains people to ignore it.

Run:  python -m evals.validate_gold
      python -m evals.validate_gold --no-body   (skip evidence-span checking)
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from evals.export_candidates import CANDIDATES_PATH, GOLD_COLUMNS
from src.models import Category, Materiality

ROOT = Path(__file__).resolve().parent.parent
GOLD_PATH = ROOT / "data" / "gold" / "gold.csv"

# Owner deviation 2026-08-02 (SPEC §13.1): the gold set is the FULL labelled
# candidate pool, not a stratified n=60. There is no fixed row count — every
# candidate in candidates.csv must be labelled. The numbers below are the
# ORIGINAL stratification, kept only as a printed reference and as the set of
# legal slice_tag values (the enum check in check_provenance); they are NO
# LONGER ENFORCED as quotas.
SLICE_TARGETS = {
    "clear_material": 15,
    "clear_immaterial": 15,
    "hard_negative": 12,
    "hard_positive": 10,
    "ambiguous": 8,
}

# Copied through from the candidate row, never authored (§C).
IDENTIFYING_COLUMNS = ["announcement_id", "exchange", "ticker", "published_at", "doc_type"]

LABEL_COLUMNS = [
    "label_materiality",
    "label_categories",
    "label_evidence_span",
    "label_rationale",
]

MATERIALITY_VALUES = set(Materiality.__args__)
CATEGORY_VALUES = set(Category.__args__)

# §D, decided 2026-08-02. B3's loader must agree with these three.
CATEGORY_DELIMITER = ";"
DIFFICULTY_VALUES = {"easy", "medium", "hard"}

MAX_SPAN_CHARS = 200  # Classification.evidence_quote max_length
MAX_RATIONALE_CHARS = 200  # Classification.rationale max_length


class Report:
    """Collects every failure rather than stopping at the first.

    A labeller wants the whole list of bad rows in one pass, not one error per
    run for sixty runs.
    """

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def emit(self) -> int:
        for note in self.notes:
            print(f"  ..   {note}")
        for warning in self.warnings:
            print(f"  WARN {warning}")
        for error in self.errors:
            print(f"  FAIL {error}")
        if self.errors:
            print(f"\ngold.csv REJECTED — {len(self.errors)} problem(s), "
                  f"{len(self.warnings)} warning(s). The gate is not cleared.")
            return 1
        print(f"\ngold.csv ACCEPTED — full labelled candidate pool, all enums legal, "
              f"evidence spans verbatim, {len(self.warnings)} warning(s). The §F gate is cleared.")
        return 0


def load_candidates() -> dict[str, dict[str, str]]:
    """The pool a gold row must be drawn from, keyed by announcement_id."""
    with CANDIDATES_PATH.open(newline="", encoding="utf-8") as fh:
        return {row["announcement_id"]: row for row in csv.DictReader(fh)}


def load_bodies() -> dict[str, str]:
    """announcement_id -> body_text, for verifying evidence spans are verbatim.

    Reads the cached payloads in data/raw/, so this costs no requests.
    """
    from src.normalise import normalise_all

    return {record.announcement_id: record.body_text for record in normalise_all()}


def check_header(fieldnames: list[str] | None, report: Report) -> None:
    """§A.3 — the 16 SPEC §13.1 columns first, in order. Extras tolerated after."""
    if not fieldnames:
        report.error("gold.csv has no header row")
        return
    actual = fieldnames[: len(GOLD_COLUMNS)]
    if actual != GOLD_COLUMNS:
        for position, (got, want) in enumerate(zip(actual, GOLD_COLUMNS)):
            if got != want:
                report.error(f"header column {position + 1}: expected {want!r}, got {got!r}")
        if len(actual) < len(GOLD_COLUMNS):
            missing = GOLD_COLUMNS[len(actual):]
            report.error(f"header is missing {len(missing)} column(s): {', '.join(missing)}")
    extra = fieldnames[len(GOLD_COLUMNS):]
    if extra:
        report.note(f"{len(extra)} trailing column(s) after the §13.1 set, tolerated: {', '.join(extra)}")


def check_identifying(row: dict[str, str], candidate: dict[str, str], line: int, report: Report) -> None:
    """§C — identifying columns are copied through, not re-typed."""
    for column in IDENTIFYING_COLUMNS:
        if row.get(column, "") != candidate[column]:
            report.error(
                f"row {line}: {column} does not match the candidate row "
                f"(candidates.csv has {candidate[column]!r}, gold.csv has {row.get(column, '')!r}) "
                "— copy it through, do not hand-type it"
            )
    if row.get("id", "") != candidate["id"]:
        report.error(
            f"row {line}: id {row.get('id', '')!r} does not match candidates.csv id "
            f"{candidate['id']!r} for this announcement_id"
        )
    if row.get("issuer_price_sensitive_flag", "").strip():
        report.error(
            f"row {line}: issuer_price_sensitive_flag must be empty on every row "
            "— EDGAR supplies no such signal (§C)"
        )


def check_labels(row: dict[str, str], body: str | None, line: int, report: Report) -> None:
    """§C label columns + §D conventions."""
    for column in LABEL_COLUMNS:
        # label_evidence_span has one narrow carve-out (§D.2); the rest never empty.
        if not row.get(column, "").strip() and column != "label_evidence_span":
            report.error(f"row {line}: {column} is empty — an unlabelled row fails the gate (§A.6)")

    materiality = row.get("label_materiality", "").strip()
    if materiality and materiality not in MATERIALITY_VALUES:
        report.error(
            f"row {line}: label_materiality {materiality!r} is not one of "
            f"{' | '.join(sorted(MATERIALITY_VALUES))}"
        )

    categories = row.get("label_categories", "").strip()
    if categories:
        if " " in categories and CATEGORY_DELIMITER in categories:
            report.error(
                f"row {line}: label_categories {categories!r} contains a space — the §D.1 "
                f"delimiter is {CATEGORY_DELIMITER!r} with no spaces"
            )
        for separator in ("|", ",", "/"):
            if separator in categories:
                report.error(
                    f"row {line}: label_categories uses {separator!r}; the §D.1 delimiter is "
                    f"{CATEGORY_DELIMITER!r}"
                )
        values = [v for v in categories.split(CATEGORY_DELIMITER) if v]
        for value in values:
            if value not in CATEGORY_VALUES:
                report.error(f"row {line}: label_categories value {value!r} is not in the Category enum")
        if len(values) != len(set(values)):
            report.error(f"row {line}: label_categories repeats a value ({categories!r})")

    span = row.get("label_evidence_span", "")
    if len(span) > MAX_SPAN_CHARS:
        report.error(
            f"row {line}: label_evidence_span is {len(span)} chars, over the "
            f"{MAX_SPAN_CHARS}-char Classification.evidence_quote limit"
        )
    if not span.strip():
        if materiality == "insufficient_info":
            # §D.2 allows this only where literally no span applies, which the
            # validator cannot tell from the outside. Surface it, don't reject it.
            report.warn(
                f"row {line}: insufficient_info with an empty label_evidence_span — allowed by §D.2 "
                "only where no span applies; an abstention with a span is testable by G2"
            )
        else:
            report.error(f"row {line}: label_evidence_span is empty on a {materiality or 'labelled'} row")
    elif body is not None and span not in body:
        report.error(
            f"row {line}: label_evidence_span is not a verbatim substring of that record's "
            f"body_text — starts {span[:60]!r}"
        )

    rationale = row.get("label_rationale", "")
    if len(rationale) > MAX_RATIONALE_CHARS:
        report.error(
            f"row {line}: label_rationale is {len(rationale)} chars, over the "
            f"{MAX_RATIONALE_CHARS}-char Classification.rationale limit"
        )
    if "\n" in rationale or "\r" in rationale:
        report.error(f"row {line}: label_rationale must be one line")


def check_provenance(row: dict[str, str], line: int, report: Report) -> None:
    """§C provenance columns + §D.3 difficulty vocabulary."""
    slice_tag = row.get("slice_tag", "").strip()
    if not slice_tag:
        report.error(f"row {line}: slice_tag is empty — it drives per-slice scoring (§C)")
    elif slice_tag not in SLICE_TARGETS:
        report.error(
            f"row {line}: slice_tag {slice_tag!r} is not one of {' | '.join(SLICE_TARGETS)}"
        )

    difficulty = row.get("difficulty", "").strip()
    if not difficulty:
        report.error(f"row {line}: difficulty is empty")
    elif difficulty not in DIFFICULTY_VALUES:
        report.error(
            f"row {line}: difficulty {difficulty!r} is not one of "
            f"{' | '.join(sorted(DIFFICULTY_VALUES))} (§D.3)"
        )

    labelled_at = row.get("labelled_at", "").strip()
    if not labelled_at:
        report.error(f"row {line}: labelled_at is empty")
    else:
        try:
            parsed = datetime.fromisoformat(labelled_at)
        except ValueError:
            report.error(f"row {line}: labelled_at {labelled_at!r} is not ISO-8601")
        else:
            if parsed.tzinfo is None:
                report.error(
                    f"row {line}: labelled_at {labelled_at!r} is naive — the repo rejects "
                    "naive datetimes elsewhere, so this must carry an offset"
                )

    if not row.get("labeller", "").strip():
        report.error(f"row {line}: labeller is empty")

    pass_number = row.get("pass_number", "").strip()
    if not pass_number:
        report.error(f"row {line}: pass_number is empty")
    elif not pass_number.isdigit():
        report.error(f"row {line}: pass_number {pass_number!r} is not an integer")


def validate(check_bodies: bool = True) -> int:
    print(f"== gold.csv gate (GOLD_REQUIREMENTS.md §F)")

    if not GOLD_PATH.is_file():
        print(f"  FAIL {GOLD_PATH.relative_to(ROOT)} does not exist.")
        print(
            "\nThis is the human gate (AUTONOMY.md §7), not a code defect. The gold set is\n"
            "owner-written by design: an agent-labelled gold set measures the agent against\n"
            "itself. Label against GOLD_REQUIREMENTS.md, then re-run this to verify."
        )
        return 1

    report = Report()
    candidates = load_candidates()
    report.note(f"pool: {len(candidates)} unlabelled candidate(s) in {CANDIDATES_PATH.relative_to(ROOT)}")

    with GOLD_PATH.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        check_header(reader.fieldnames, report)
        rows = list(reader)

    report.note(f"{len(rows)} data row(s) read")

    bodies: dict[str, str] = {}
    if check_bodies and rows:
        report.note("loading canonical bodies from data/raw/ to verify evidence spans (no requests)")
        bodies = load_bodies()

    seen_ids: set[str] = set()
    seen_announcements: set[str] = set()
    for offset, row in enumerate(rows):
        line = offset + 2  # header is line 1

        row_id = row.get("id", "").strip()
        if row_id in seen_ids:
            report.error(f"row {line}: duplicate id {row_id!r} (§C: must be unique in gold.csv)")
        seen_ids.add(row_id)

        announcement_id = row.get("announcement_id", "").strip()
        if announcement_id in seen_announcements:
            report.error(f"row {line}: duplicate announcement_id {announcement_id!r}")
        seen_announcements.add(announcement_id)

        candidate = candidates.get(announcement_id)
        if candidate is None:
            report.error(
                f"row {line}: announcement_id {announcement_id!r} is not in candidates.csv — "
                "B3 loads each item by this key and has no record to run against (§A.5)"
            )
            continue

        check_identifying(row, candidate, line, report)
        check_labels(row, bodies.get(announcement_id) if check_bodies else None, line, report)
        check_provenance(row, line, report)

    missing = set(candidates) - seen_announcements
    if missing:
        report.error(
            f"{len(missing)} candidate(s) in candidates.csv are not labelled in gold.csv — "
            "the gold set is the FULL labelled pool (SPEC §13.1, owner deviation "
            "2026-08-02), so every candidate must be labelled"
        )

    counts = Counter(row.get("slice_tag", "").strip() for row in rows)
    print("\n  slice_tag           count  (orig. reference)")
    for tag, reference in SLICE_TARGETS.items():
        print(f"  {tag:<18} {counts.get(tag, 0):>5}  {reference:>8}")
    print("  stratification dropped — counts are descriptive only (SPEC §13.1)")
    unknown = set(counts) - set(SLICE_TARGETS) - {""}
    for tag in sorted(unknown):
        report.error(f"slice_tag {tag!r} is not one of the five valid tags ({counts[tag]} row(s))")

    print()
    return report.emit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--no-body",
        action="store_true",
        help="skip verifying that each label_evidence_span is verbatim in body_text",
    )
    args = parser.parse_args()
    sys.exit(validate(check_bodies=not args.no_body))


if __name__ == "__main__":
    main()
