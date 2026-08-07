"""A3 — normalise.py + doc_type map + stub adapter.

Acceptance (SPEC.md §14 increment 3): at least 50 records in data/raw/, no
nulls in required fields, announcement_id unique.

This check also pins the parts of SPEC.md §6 that increment 3 introduces: the
externalised doc_type map, the "unknown native type -> admin, and log it, never
crash" rule, and a stub adapter that satisfies the ExchangeAdapter protocol
without doing any work — proving the interface generalises past EDGAR.

Run:  python -m checks.check_normalise
"""

from __future__ import annotations

import json
import re
import typing
from datetime import timezone
from pathlib import Path

import yaml

from checks._harness import Check, run

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
DOC_TYPE_MAP = ROOT / "config" / "doc_type_map.yaml"

CATEGORIES = set(typing.get_args(__import__("src.models", fromlist=["Category"]).Category))

# SPEC.md §5.1 — every field must be populated on a normalised record. The
# price-sensitive flag is the sole exception: EDGAR supplies no such signal.
REQUIRED_NON_NULL = [
    "announcement_id",
    "exchange",
    "ticker",
    "company_name",
    "published_at",
    "headline",
    "doc_type",
    "native_doc_type",
    "native_id",
    "body_text",
    "char_count",
    "source_url",
    "fetched_at",
]


def check_doc_type_map(c: Check) -> None:
    """SPEC.md §6.2 — externalised, readable, canonical values only."""
    c.require(DOC_TYPE_MAP.is_file(), "config/doc_type_map.yaml exists (SPEC §6.2)")
    mapping = yaml.safe_load(DOC_TYPE_MAP.read_text(encoding="utf-8"))
    c.require(isinstance(mapping, dict), "doc_type_map.yaml parses to a mapping")
    c.require("EDGAR" in mapping, "doc_type_map has an EDGAR section")

    for exchange, entries in mapping.items():
        for native, canonical in entries.items():
            c.require(
                canonical in CATEGORIES,
                f"{exchange}:{native} maps to a canonical category ({canonical})",
            )
            c.require(isinstance(native, str), f"{exchange}:{native} native key is a string")

    # The three mappings SPEC §6.2 states outright for EDGAR.
    c.equal(mapping["EDGAR"].get("8-K"), "operational_incident", "SPEC §6.2: EDGAR 8-K -> operational_incident")
    c.equal(mapping["EDGAR"].get("10-Q"), "earnings_result", "SPEC §6.2: EDGAR 10-Q -> earnings_result")

    # Every form actually present in the corpus should be a deliberate decision,
    # not an accidental fall-through. Unmapped forms are reported, not failed.
    forms = {json.loads(p.read_text(encoding="utf-8"))["form"] for p in RAW_DIR.glob("*.json")}
    unmapped = sorted(f for f in forms if f not in mapping["EDGAR"])
    c.note(f"{len(forms) - len(unmapped)}/{len(forms)} corpus form types explicitly mapped")
    if unmapped:
        c.note(f"unmapped (fall through to admin): {unmapped}")


def check_adapters(c: Check) -> None:
    """SPEC.md §6.1 — the protocol, the reference implementation, and the stub."""
    from src.adapters import ExchangeAdapter
    from src.adapters.stub import StubAdapter
    from src.fetch import build_adapter, load_config

    config = load_config()
    edgar = build_adapter(config)
    stub = StubAdapter()

    for name, adapter in [("EdgarAdapter", edgar), ("StubAdapter", stub)]:
        c.require(isinstance(adapter, ExchangeAdapter), f"{name} satisfies the ExchangeAdapter protocol")
        for method in ["poll", "normalise", "map_doc_type", "price_sensitive_flag"]:
            c.require(callable(getattr(adapter, method, None)), f"{name} implements {method}()")
        c.require(isinstance(adapter.exchange_code, str) and adapter.exchange_code, f"{name} declares exchange_code")

    # Reference implementation: the mappings SPEC §6.2 names.
    c.equal(edgar.map_doc_type("8-K"), "operational_incident", "EDGAR adapter maps 8-K")
    c.equal(edgar.map_doc_type("10-Q"), "earnings_result", "EDGAR adapter maps 10-Q")
    c.equal(edgar.map_doc_type("4"), "director_dealing", "EDGAR adapter maps Form 4 to director_dealing")

    # Unknown native type -> admin, with a warning, never a crash (SPEC §6.2).
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = edgar.map_doc_type("ZZZ-NOT-A-REAL-FORM")
    c.equal(result, "admin", "unknown native doc type maps to admin instead of crashing")
    c.require(len(caught) == 1, "unknown native doc type emits exactly one warning")
    c.require(
        "ZZZ-NOT-A-REAL-FORM" in str(caught[0].message),
        "the warning names the offending native type",
    )

    # The stub exists to prove the interface generalises, not to work.
    c.equal(stub.poll(__import__("datetime").datetime.now(timezone.utc)), [], "StubAdapter.poll() returns []")
    c.equal(stub.price_sensitive_flag({}), None, "StubAdapter.price_sensitive_flag() returns None")
    c.equal(stub.map_doc_type("anything"), "admin", "StubAdapter maps any native type to admin")


def check_normalised_records(c: Check) -> None:
    """The acceptance criterion: >=50 records, no nulls, unique ids."""
    from src.fetch import load_config
    from src.models import Announcement

    config = load_config()
    raw_files = list(RAW_DIR.glob("*.json"))
    c.require(len(raw_files) >= 50, f"at least 50 records in data/raw/ (got {len(raw_files)})")

    from src.normalise import normalise_all

    records = normalise_all(config=config)
    c.require(len(records) >= 50, f"at least 50 records normalise cleanly (got {len(records)})")
    c.require(all(isinstance(r, Announcement) for r in records), "every record is an Announcement")

    watchlist = {t.upper() for t in config["watchlist"]}
    truncate_at = config["thresholds"]["truncate_input_chars"]

    for r in records:
        for field in REQUIRED_NON_NULL:
            value = getattr(r, field)
            if value is None or value == "":
                c.require(False, f"{r.announcement_id[:12]}: required field {field} is null/empty")
        c.require(r.issuer_price_sensitive_flag is None, f"{r.ticker}: EDGAR supplies no price-sensitive flag")

    c.note(f"all {len(records)} records populate every required field in SPEC §5.1")

    ids = [r.announcement_id for r in records]
    c.equal(len(set(ids)), len(ids), "every announcement_id is unique")
    for r in records:
        expected = Announcement.compute_id(r.exchange, r.ticker, r.published_at, r.headline, r.native_id)
        if expected != r.announcement_id:
            c.equal(expected, r.announcement_id, f"{r.ticker}: announcement_id is the SPEC §5.1 hash")
    c.note("every announcement_id recomputes to the SPEC §5.1 hash")

    for r in records:
        problems = []
        if r.exchange != "EDGAR":
            problems.append(f"exchange={r.exchange}")
        if r.ticker != r.ticker.upper() or r.ticker not in watchlist:
            problems.append(f"ticker={r.ticker}")
        if r.doc_type not in CATEGORIES:
            problems.append(f"doc_type={r.doc_type}")
        if r.published_at.tzinfo is None or r.published_at.utcoffset().total_seconds() != 0:
            problems.append("published_at not UTC-aware")
        if r.fetched_at.tzinfo is None:
            problems.append("fetched_at not aware")
        if not r.source_url.startswith("https://"):
            problems.append("source_url not https")
        if r.char_count != len(r.body_text):
            problems.append(f"char_count {r.char_count} != len(body_text) {len(r.body_text)}")
        if r.char_count > truncate_at:
            problems.append(f"body_text exceeds truncate_input_chars ({r.char_count})")
        # The pre-truncation text is cached next to the raw payload, so the
        # truncated flag can be checked exactly rather than inferred.
        cached = RAW_DIR / f"{r.announcement_id}.txt"
        if cached.is_file():
            full = cached.read_text(encoding="utf-8")
            if r.truncated != (len(full) > truncate_at):
                problems.append(f"truncated={r.truncated} but source text is {len(full)} chars")
            if r.truncated and r.body_text != full[:truncate_at].rstrip():
                problems.append("truncated body_text is not the leading slice of the source text")
            if not r.truncated and r.body_text != full:
                problems.append("untruncated body_text differs from the source text")
        else:
            problems.append("no cached source text to verify truncation against")
        if problems:
            c.require(False, f"{r.ticker} {r.native_doc_type}: {'; '.join(problems)}")
    c.note("exchange, ticker, doc_type, timezone, url, char_count and truncation are consistent on every record")

    # body_text is "plain text, whitespace-normalised" (SPEC §5.1).
    for r in records:
        problems = []
        if "  " in r.body_text:
            problems.append("runs of spaces survive")
        if "\t" in r.body_text or "\r" in r.body_text:
            problems.append("tabs/CR survive")
        if "\n\n\n" in r.body_text:
            problems.append("blank-line runs survive")
        if r.body_text != r.body_text.strip():
            problems.append("leading/trailing whitespace")
        if re.search(r"<\s*(script|style|div|span|table|p)\b", r.body_text, re.I):
            problems.append("HTML markup survives")
        if "&nbsp;" in r.body_text or "&amp;" in r.body_text:
            problems.append("HTML entities survive")
        if problems:
            c.require(False, f"{r.ticker} {r.native_doc_type} body_text: {'; '.join(problems)}")
    c.note("body_text is plain text with whitespace normalised on every record")

    # Filings whose primary document is a non-text container (PDF/xlsx/image) get
    # a short, synthesised metadata body instead of the ingested bytes — see
    # EdgarAdapter._placeholder_body. That body is intentionally short, so it is
    # excluded from the real-content floor and validated on its own terms below.
    from src.adapters.edgar import NON_TEXT_BODY_SENTINEL

    placeholders = [r for r in records if NON_TEXT_BODY_SENTINEL in r.body_text]
    ingested = [r for r in records if NON_TEXT_BODY_SENTINEL not in r.body_text]

    shortest = min(ingested, key=lambda r: r.char_count)
    c.require(
        shortest.char_count > 200,
        f"even the shortest ingested body_text carries real content ({shortest.char_count} "
        f"chars, {shortest.ticker} {shortest.native_doc_type})",
    )
    for r in placeholders:
        c.require(
            r.body_text.startswith("[") and "Form " in r.body_text,
            f"{r.ticker} {r.native_doc_type} non-text placeholder names its form "
            f"and marks the skipped document",
        )
    c.note(
        f"{len(ingested)} ingested bodies (floor 200 chars); "
        f"{len(placeholders)} non-text-document placeholders"
    )

    # Normalisation is a pure function of the raw payload.
    from src.normalise import normalise_one

    raw = json.loads((RAW_DIR / f"{records[0].announcement_id}.json").read_text(encoding="utf-8"))
    again = normalise_one(raw, config=config)
    c.equal(
        again.model_dump(exclude={"fetched_at"}),
        records[0].model_dump(exclude={"fetched_at"}),
        "normalising the same raw payload twice yields an identical record",
    )

    forms = {r.native_doc_type for r in records}
    doc_types = {r.doc_type for r in records}
    tickers = {r.ticker for r in records}
    c.require(len(forms) >= 10, f"the sample spans many native form types ({len(forms)})")
    c.require(len(tickers) >= 10, f"the sample spans many issuers ({len(tickers)})")
    c.note(f"{len(records)} records; {len(forms)} native forms; doc_types={sorted(doc_types)}")


def check_pin_decoupling(c: Check) -> None:
    """The gold-candidate pin sampler must never abort an operational window run.

    Regression guard for the backfill failure: the pin file exists only to keep the
    labelling export's row ids stable, and its divergence guard aborts the whole run
    when a pinned id is absent from the corpus. A backfill (src.run._load_window)
    fetches a window that cannot be guaranteed to contain the frozen pin ids, so the
    window path must NOT consult the pin sampler — while the pinned export path
    (normalise_all with a pin_file) still fails loudly on divergence.
    """
    import copy
    import tempfile
    from datetime import timedelta

    from src.fetch import load_config
    from src.normalise import load_raw_payloads, normalise_all
    from src.run import _load_window
    from src.store import parse_iso

    config = copy.deepcopy(load_config())
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        fh.write("# forced divergence — an id that cannot be in the corpus\n")
        fh.write("edgar:0000000000-00-000000:NONEXISTENT-FORM\n")
        bogus_pin = fh.name
    config["normalise"] = copy.deepcopy(config["normalise"])
    config["normalise"]["pin_file"] = str(Path(bogus_pin).resolve())

    try:
        # 1. Export safety unchanged: normalise_all still aborts loudly on divergence.
        raised = False
        try:
            normalise_all(config=config, limit=5)
        except RuntimeError as exc:
            raised = "pinned announcement_id" in str(exc)
        c.require(raised, "the pinned export path still aborts loudly when the pin file has diverged")

        # 2. The backfill/window path is immune to that guard even with a diverged pin
        #    file configured. Use a narrow window around the newest payload so the check
        #    stays fast (and proves the window pre-filter, not a whole-corpus normalise).
        payloads = load_raw_payloads()
        newest = max(parse_iso(raw["published_at"]) for raw in payloads)
        since, until = newest - timedelta(days=2), newest
        records = _load_window(config, since, until)
        c.require(
            len(records) > 0,
            f"_load_window ignores the pin file and normalises the window ({len(records)} records) "
            "— a backfill can no longer be aborted by pin divergence",
        )
        c.note("backfill/window path is decoupled from the gold-candidate pin sampler")
    finally:
        Path(bogus_pin).unlink(missing_ok=True)


def body(c: Check) -> None:
    check_doc_type_map(c)
    check_adapters(c)
    check_normalised_records(c)
    check_pin_decoupling(c)


if __name__ == "__main__":
    run("A3 normalise + doc_type map + stub adapter", body)
