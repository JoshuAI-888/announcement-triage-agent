"""check_flags.py — plain-English flag vocabulary + no-raw-code leakage (deploy build, Phase 1).

Offline, no network, no API. Three jobs:
  1. `FLAG_VOCAB` covers every `G#_...` code `src.verify` can actually append to
     `guardrail_flags` (read straight from verify.py's own source, so this check
     fails loudly the day a new guardrail is added without a vocab entry), plus
     the documented `G4_off_watchlist` (never lands in guardrail_flags — G4 drops
     the record before that point — but is still part of the frozen vocabulary)
     and the `insufficient_info` pseudo-key.
  2. `explain_flag`/`explain_flags`/`doc_type_label` behave as specified,
     including graceful degradation on an unknown code.
  3. Rendering a fixture through BOTH `render_email` and `brief.py` never lets a
     raw `G#_...` code or the literal `insufficient_info` reach the page — the
     whole point of this module existing.
"""

from __future__ import annotations

import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from checks._harness import run
from src import verify as V
from src.flags import FLAG_VOCAB, MATERIALITY_LABEL, doc_type_label, explain_flag, explain_flags
from src.models import Announcement, Classification, Entities
from src.rank import RankedItem

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)

# Every G#_code verify.py can append to guardrail_flags — read straight from its
# source so this check fails loudly if a new guardrail is added without a vocab entry.
_VERIFY_SRC = Path(V.__file__).read_text(encoding="utf-8")
_CODES_IN_VERIFY = set(re.findall(r'"(G\d_[a-z_]+)"', _VERIFY_SRC))
# G1 and G4 never appear as string literals appended to guardrail_flags: G1 is
# raised as a GuardrailError before any Classification exists (classify.py's
# retry-then-dead-letter flow, never a flag on a record), and G4 drops the
# record via `return None` in verify() rather than flagging it. Both are still
# part of the frozen vocabulary, so they're asserted separately below.
_CODES_NOT_IN_VERIFY = {"G1_parse_error", "G4_off_watchlist"}

_RAW_CODE_RE = re.compile(r"\bG[1-6]_[a-z_]+\b")


def make_ann(ticker="AAPL"):
    return Announcement(
        announcement_id="a" * 64, exchange="EDGAR", ticker=ticker, company_name=f"{ticker} Inc.",
        industry="Technology", published_at=NOW - timedelta(hours=1), headline=f"{ticker} announcement",
        doc_type="guidance_change", native_doc_type="8-K [2.02]", native_id="acc-1",
        issuer_price_sensitive_flag=None, body_text="body", char_count=4, truncated=False,
        source_url=f"https://sec.gov/{ticker}", fetched_at=NOW,
    )


def make_cls(ann, materiality="material", flags=None, quote="body"):
    return Classification(
        announcement_id=ann.announcement_id, materiality=materiality, confidence=0.9,
        categories=[ann.doc_type], evidence_quote=quote, rationale="rationale text",
        entities=Entities(), previously_disclosed=False, needs_human_review=bool(flags),
        model_id="m", prompt_version="v3", cost_nzd=0.01, guardrail_flags=flags or [],
    )


def body(check):
    # --- vocab completeness ---
    check.require(len(_CODES_IN_VERIFY) >= 4, "sanity: found several G#_ code literals in verify.py")
    missing = _CODES_IN_VERIFY - set(FLAG_VOCAB)
    check.equal(missing, set(), "FLAG_VOCAB covers every G#_ code verify.py can append to guardrail_flags")
    for code in sorted(_CODES_IN_VERIFY | _CODES_NOT_IN_VERIFY):
        entry = FLAG_VOCAB[code]
        check.require(set(entry) == {"label", "meaning", "why"}, f"{code}: vocab entry has exactly label/meaning/why")
        check.require(all(isinstance(v, str) and v for v in entry.values()), f"{code}: every field is a non-empty string")

    check.require("G1_parse_error" in FLAG_VOCAB,
                  "G1_parse_error is documented even though it's raised, never appended to guardrail_flags")
    check.require("G4_off_watchlist" in FLAG_VOCAB,
                  "G4_off_watchlist is documented even though drops happen before guardrail_flags is set")
    check.require("insufficient_info" in FLAG_VOCAB, "the insufficient_info pseudo-key is documented")

    # --- exact copy check on a couple of entries (frozen contract) ---
    check.equal(FLAG_VOCAB["G2_ungrounded_quote"]["label"], "Unverified quote", "G2 label matches the frozen contract")
    check.equal(FLAG_VOCAB["G6_directional_language"]["label"], "Advice wording removed",
               "G6 label matches the frozen contract")
    check.equal(FLAG_VOCAB["G1_parse_error"]["label"], "Unreadable model output", "G1 label matches the frozen contract")
    check.equal(MATERIALITY_LABEL, {"material": "Material", "immaterial": "Immaterial", "insufficient_info": "Needs more info"},
               "MATERIALITY_LABEL matches the frozen contract exactly")

    # --- explain_flag / explain_flags ---
    single = explain_flag("G3_unverified_amount")
    check.equal(set(single), {"label", "meaning", "why"}, "explain_flag returns exactly label/meaning/why")
    check.equal(single["label"], "Unverified figure", "explain_flag looks up the vocab correctly")

    unknown = explain_flag("G9_never_heard_of_it")
    check.equal(unknown, {"label": "G9_never_heard_of_it", "meaning": "G9_never_heard_of_it", "why": ""},
                "an unknown code degrades gracefully instead of raising")

    sample = explain_flags(["G1_parse_error", "G5_low_confidence", "G9_bogus"])
    check.equal(len(sample), 3, "explain_flags returns one entry per input code, in order")
    check.equal(sample[0]["label"], "Unreadable model output", "explain_flags[0] is G1's label")
    check.equal(sample[1]["label"], "Low confidence", "explain_flags[1] is G5's label")
    check.equal(sample[2]["label"], "G9_bogus", "explain_flags degrades the unknown entry too")

    # --- doc_type_label ---
    check.equal(doc_type_label("earnings_result", "10-Q"), "Quarterly report (10-Q)",
                "doc_type_label prefers the native-form label when one exists")
    check.equal(doc_type_label("operational_incident", "8-K"), "Material event report (8-K)",
                "8-K gets its own specific label, not the generic operational_incident one")
    check.equal(doc_type_label("earnings_result", "10-K"), "Annual report (10-K)", "10-K -> Annual report (10-K)")
    check.equal(doc_type_label("earnings_result", None), "Quarterly results",
                "with no native form, falls back to the canonical earnings_result label")
    check.equal(doc_type_label("m_and_a", ""), "M&A / deal", "m_and_a canonical fallback matches the frozen example")
    check.equal(doc_type_label("nonexistent_category", "ZZZ-UNKNOWN-FORM"), "ZZZ-UNKNOWN-FORM",
                "with neither a native-form nor canonical match, falls back to the raw native form string")
    check.require(doc_type_label("nonexistent_category", None), "doc_type_label never returns empty")

    # --- renderers never leak a raw code (the whole point of this module) ---
    ann = make_ann("AAPL")
    flagged = make_cls(ann, "material", flags=["G2_ungrounded_quote", "G3_unverified_amount"])
    flagged_item = RankedItem(classification=flagged, announcement=ann, score=0.4, reason="reason")
    fixture_stats = {"guardrail_flag_counts": {"G2_ungrounded_quote": 1, "G3_unverified_amount": 1}}

    from src.render_email import render_email
    tmp = Path(tempfile.mkdtemp(prefix="flags_check_"))
    html_path = render_email([], [flagged_item], fixture_stats, [], all_items=[flagged_item],
                             brief_date=NOW.date(), out_dir=tmp)
    html = html_path.read_text(encoding="utf-8")
    check.require(not _RAW_CODE_RE.search(html), "render_email never leaks a raw G#_ code")
    check.require("insufficient_info" not in html, "render_email never leaks the literal 'insufficient_info'")
    check.require(FLAG_VOCAB["G2_ungrounded_quote"]["label"] in html,
                  "render_email shows the plain-English label instead of the raw code")

    from src.brief import render_brief
    md_path = render_brief([], [flagged_item], fixture_stats, all_items=[flagged_item],
                           brief_date=NOW.date(), out_dir=tmp)
    md = md_path.read_text(encoding="utf-8")
    check.require(not _RAW_CODE_RE.search(md), "brief.py (markdown) never leaks a raw G#_ code")
    check.require("insufficient_info" not in md, "brief.py never leaks the literal 'insufficient_info'")
    check.require(FLAG_VOCAB["G2_ungrounded_quote"]["label"] in md,
                  "brief.py shows the plain-English label instead of the raw code")

    # --- an abstention (no guardrail_flags, materiality=insufficient_info) uses
    #     the insufficient_info pseudo-key, and STILL never leaks the raw literal ---
    abstained = make_cls(ann, "insufficient_info")
    abst_item = RankedItem(classification=abstained, announcement=ann, score=0.2, reason="reason")
    html2 = render_email([], [abst_item], {}, [], all_items=[abst_item],
                         brief_date=NOW.date(), out_dir=tmp).read_text(encoding="utf-8")
    check.require(FLAG_VOCAB["insufficient_info"]["label"] in html2,
                  "an abstention (no flags) shows the insufficient_info label")
    check.require(not _RAW_CODE_RE.search(html2) and "insufficient_info" not in html2,
                  "abstention rendering still leaks nothing raw")

    md2 = render_brief([], [abst_item], {}, all_items=[abst_item],
                       brief_date=NOW.date(), out_dir=tmp).read_text(encoding="utf-8")
    check.require(FLAG_VOCAB["insufficient_info"]["label"] in md2,
                  "brief.py shows the insufficient_info label for an abstention too")
    check.require(not _RAW_CODE_RE.search(md2) and "insufficient_info" not in md2,
                  "brief.py abstention rendering still leaks nothing raw")

    check.note("offline check — no API calls, no network, no spend")


if __name__ == "__main__":
    run("plain-English flag vocabulary + no-raw-code leakage (src/flags.py)", body)
