"""check_verify.py — B2: deterministic guardrails G1–G6 (SPEC §9).

Offline, no API. Every guardrail is exercised, and G2 (grounding / hallucination
metric) and G6 (directional-language compliance block) are shown FIRING on
synthetic fixtures — a guardrail never observed failing is not tested.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from checks._harness import run
from src import verify as V
from src.fetch import load_config
from src.models import Announcement, Classification, Entities

CONFIG = load_config()

BODY = (
    "Apple today raised its full-year revenue guidance to $4.2 billion, "
    "citing strong iPhone demand across all regions."
)


def make_announcement(ticker: str = "AAPL") -> Announcement:
    now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    return Announcement(
        announcement_id="a" * 64, exchange="EDGAR", ticker=ticker, company_name="Apple Inc.",
        published_at=now, headline="Apple raises full-year guidance", doc_type="guidance_change",
        native_doc_type="8-K", native_id="0000320193-26-000010", issuer_price_sensitive_flag=None,
        body_text=BODY, char_count=len(BODY), truncated=False, source_url="https://sec.gov/x", fetched_at=now,
    )


def make_classification(**over) -> Classification:
    base = dict(
        announcement_id="a" * 64, materiality="material", confidence=0.90,
        categories=["guidance_change"],
        evidence_quote="raised its full-year revenue guidance to $4.2 billion",
        rationale="FY guidance raised ~10%, plainly price-moving",
        entities=Entities(amounts=["$4.2 billion"]), previously_disclosed=False, needs_human_review=False,
    )
    base.update(over)
    return Classification(**base)


def body(check):
    ann = make_announcement()

    # --- G1: raw output must parse + validate; failures raise GuardrailError ---
    good = json.dumps({
        "materiality": "material", "confidence": 0.9, "categories": ["guidance_change"],
        "evidence_quote": "raised its full-year revenue guidance to $4.2 billion",
        "rationale": "guidance up", "entities": {"amounts": [], "counterparties": [], "effective_dates": []},
        "previously_disclosed": False, "needs_human_review": False,
    })
    parsed = V.g1_parse(good, ann.announcement_id)
    check.equal(parsed.materiality, "material", "G1 parses valid JSON into a Classification")
    check.equal(parsed.announcement_id, ann.announcement_id, "G1 sets announcement_id authoritatively")
    check.raises(V.GuardrailError, lambda: V.g1_parse("not json", ann.announcement_id), "G1 rejects non-JSON")
    bad_enum = good.replace('"material"', '"enormous"')
    check.raises(V.GuardrailError, lambda: V.g1_parse(bad_enum, ann.announcement_id), "G1 rejects an invalid enum value")
    missing = json.dumps({"materiality": "material"})
    check.raises(V.GuardrailError, lambda: V.g1_parse(missing, ann.announcement_id), "G1 rejects a record missing required fields")

    # --- G2 grounding — PASS then FIRE (the hallucination metric) ---
    grounded = V.verify(make_classification(), ann, CONFIG)
    check.require("G2_ungrounded_quote" not in grounded.guardrail_flags, "G2 passes when the quote is verbatim in the body")

    check.note("--- G2 fixture (FIRING) ---")
    hallucinated = make_classification(evidence_quote="the board approved a special dividend of $5.00 per share")
    check.note(f"    body_text     : {BODY!r}")
    check.note(f"    evidence_quote: {hallucinated.evidence_quote!r}   (NOT present in body_text)")
    g2 = V.verify(hallucinated, ann, CONFIG)
    check.note(f"    → guardrail_flags   : {g2.guardrail_flags}")
    check.note(f"    → needs_human_review: {g2.needs_human_review}")
    check.require("G2_ungrounded_quote" in g2.guardrail_flags, "G2 FIRES on an ungrounded quote → G2_ungrounded_quote")
    check.equal(g2.needs_human_review, True, "G2 firing sets needs_human_review=true")

    # G2 uses whitespace-normalised + casefolded comparison (SPEC §9)
    ws = make_classification(evidence_quote="RAISED  its   full-year\nrevenue guidance TO $4.2 billion")
    g2ws = V.verify(ws, ann, CONFIG)
    check.require("G2_ungrounded_quote" not in g2ws.guardrail_flags, "G2 tolerates whitespace/case differences (normalised match)")

    # --- G3: unverified amount stripped + flagged ---
    g3 = V.verify(make_classification(entities=Entities(amounts=["$4.2 billion", "$99 trillion"])), ann, CONFIG)
    check.require("G3_unverified_amount" in g3.guardrail_flags, "G3 fires on an amount absent from the body")
    check.equal(g3.entities.amounts, ["$4.2 billion"], "G3 strips the unverified amount, keeps the grounded one")

    # --- G4: off-watchlist record is dropped (None) ---
    dropped = V.verify(make_classification(), make_announcement(ticker="ZZZZ"), CONFIG)
    check.equal(dropped, None, "G4 drops a record whose ticker is not on the watchlist")
    kept = V.verify(make_classification(), make_announcement(ticker="AAPL"), CONFIG)
    check.require(kept is not None, "G4 keeps a watchlisted ticker")

    # --- G5: sub-floor confidence coerced to insufficient_info ---
    floor = CONFIG["thresholds"]["confidence_floor"]
    g5 = V.verify(make_classification(confidence=floor - 0.1, materiality="material"), ann, CONFIG)
    check.equal(g5.materiality, "insufficient_info", "G5 coerces a sub-floor call to insufficient_info")
    check.require("G5_low_confidence" in g5.guardrail_flags, "G5 appends G5_low_confidence")

    # --- G6 directional language — PASS then FIRE (compliance) ---
    clean = V.verify(make_classification(), ann, CONFIG)
    check.require("G6_directional_language" not in clean.guardrail_flags, "G6 passes on neutral, descriptive language")

    check.note("--- G6 fixture (FIRING) ---")
    directional = make_classification(rationale="clear beat, we recommend an overweight position here")
    check.note(f"    rationale: {directional.rationale!r}   (contains 'we recommend' / 'overweight')")
    g6 = V.verify(directional, ann, CONFIG)
    check.note(f"    → guardrail_flags   : {g6.guardrail_flags}")
    check.note(f"    → needs_human_review: {g6.needs_human_review}")
    check.require("G6_directional_language" in g6.guardrail_flags, "G6 FIRES on directional language → G6_directional_language")
    check.equal(V.is_brief_ready(g6), False, "a G6-flagged record is NOT brief-ready (routes to Needs a look)")

    # G6 also scans the evidence_quote, and does not false-fire on 'buyback'
    g6q = V.verify(make_classification(evidence_quote="we set a target price of $250"), ann, CONFIG)
    check.require("G6_directional_language" in g6q.guardrail_flags, "G6 scans evidence_quote too ('target price')")
    g6fp = V.verify(make_classification(rationale="announced a $10bn share buyback programme"), ann, CONFIG)
    check.require("G6_directional_language" not in g6fp.guardrail_flags, "G6 does not false-fire on 'buyback' (word boundary)")

    check.note("offline check — no API calls, no spend")


if __name__ == "__main__":
    run("B2 guardrails G1-G6 + synthetic fixtures", body)
