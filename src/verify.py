"""verify.py — deterministic guardrails G1–G6 (SPEC.md §9). Increment 5.

No LLM calls anywhere in this module. Every guardrail is a mechanical check over
a Classification and its Announcement; each failure either mutates the record
(coerce/strip), flags it for review, or drops it. G2 (verbatim-quote grounding)
is the entire hallucination metric and G6 (directional-language denylist) is the
compliance guardrail — both are exercised firing in checks/check_verify.py.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from pydantic import ValidationError

from src.models import Announcement, Classification

# G6 — case-insensitive denylist of directional / recommendation language.
# Word boundaries so "buy" does not fire on "buyback" or "buyer".
DIRECTIONAL_TERMS = [
    "buy", "sell", "overweight", "underweight", "target price", "we recommend",
    "undervalued", "overvalued", "outperform", "underperform",
]
_DIRECTIONAL_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in DIRECTIONAL_TERMS) + r")\b", re.IGNORECASE)

_WS_RE = re.compile(r"\s+")


class GuardrailError(RuntimeError):
    """G1 hard failure — output could not be parsed/validated into a Classification."""


def _normalise_ws(text: str) -> str:
    """Collapse runs of whitespace and casefold (SPEC §9 G2)."""
    return _WS_RE.sub(" ", text).strip().casefold()


def g1_parse(raw_text: str, announcement_id: str) -> Classification:
    """G1: raw model output must parse as JSON and validate against the schema.

    Raises GuardrailError on any failure. The retry-once-then-dead-letter policy
    (SPEC §9 G1) lives at the classify→verify boundary in the orchestrator; this
    function is the single validating parse it calls.
    """
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not match:
        raise GuardrailError("G1: no JSON object in output")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise GuardrailError(f"G1: invalid JSON ({exc})") from exc
    data["announcement_id"] = announcement_id
    try:
        return Classification(**data)
    except (ValidationError, TypeError) as exc:
        raise GuardrailError(f"G1: schema validation failed ({exc})") from exc


def verify(
    classification: Classification,
    announcement: Announcement,
    config: dict,
) -> Optional[Classification]:
    """Apply G2–G6 to one classified record.

    Returns the (possibly mutated) Classification with any guardrail flags
    appended, or **None** if G4 drops the record (ticker off the watchlist). The
    caller logs the drop. Input is not mutated.
    """
    # G4 — ticker must be on the configured watchlist. Drop (and let the caller log).
    if announcement.ticker not in config["watchlist"]:
        return None

    c = classification.model_copy(deep=True)
    flags = list(c.guardrail_flags)
    body_norm = _normalise_ws(announcement.body_text)

    # G2 — evidence_quote must appear verbatim in body_text (ws-normalised). Hallucination metric.
    if _normalise_ws(c.evidence_quote) not in body_norm:
        c.needs_human_review = True
        flags.append("G2_ungrounded_quote")

    # G3 — every amount must appear in body_text; strip the ones that do not.
    kept_amounts = []
    stripped_any = False
    for amount in c.entities.amounts:
        if amount in announcement.body_text:
            kept_amounts.append(amount)
        else:
            stripped_any = True
    if stripped_any:
        c.entities.amounts = kept_amounts
        flags.append("G3_unverified_amount")

    # G5 — sub-floor confidence coerces the call to an abstention.
    if c.confidence < config["thresholds"]["confidence_floor"]:
        c.materiality = "insufficient_info"
        flags.append("G5_low_confidence")

    # G6 — directional/recommendation language blocks the record from the brief.
    if _DIRECTIONAL_RE.search(c.rationale) or _DIRECTIONAL_RE.search(c.evidence_quote):
        c.needs_human_review = True
        flags.append("G6_directional_language")

    c.guardrail_flags = flags
    return c


# A record is fit for the ranked brief only if it raised no guardrail flag and is
# not an abstention (SPEC §10/§11 route the rest to "Needs a look").
def is_brief_ready(classification: Classification) -> bool:
    return not classification.guardrail_flags and classification.materiality != "insufficient_info"
