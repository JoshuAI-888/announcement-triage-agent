"""baselines.py — the three mandatory baselines (SPEC §13.4). Increment 7.

Each takes (announcement, config, client) and returns a Classification, so the
harness can run them over the identical gold set:

- flag_all     — everything is material. The recall ceiling, and the price of
                 pure safety in precision.
- rules        — classify from doc_type + a keyword list. No LLM. The real
                 competitor a prompt has to beat.
- naive_prompt — the v1 prompt (Role + schema only). Isolates what prompt design
                 beyond the naive baseline actually buys.

flag_all and rules make no model call; naive_prompt delegates to classify(v1).
Evidence quotes are taken verbatim from the body so the grounding guardrail (G2)
scores them fairly.
"""

from __future__ import annotations

from src.classify import classify
from src.models import Announcement, Classification, Entities

# rules baseline — doc_types that are material by form, and keywords that flip an
# otherwise-routine filing to material. Deliberately simple; this is a competitor,
# not the agent.
MATERIAL_DOC_TYPES = {"guidance_change", "earnings_result", "m_and_a", "contract_award", "regulatory"}
MATERIAL_KEYWORDS = [
    "guidance", "outlook", "acquire", "acquisition", "merger", "takeover", "contract award",
    "results", "dividend", "recall", "investigation", "resign", "downgrade", "impairment", "restate",
]


def _quote(ann: Announcement) -> str:
    """A verbatim ≤200-char span from the body, so G2 grades the baseline fairly."""
    return ann.body_text[:200]


def flag_all(ann: Announcement, config: dict, client=None) -> Classification:
    return Classification(
        announcement_id=ann.announcement_id, materiality="material", confidence=1.0,
        categories=[ann.doc_type], evidence_quote=_quote(ann),
        rationale="flag_all baseline: everything flagged material",
        entities=Entities(), previously_disclosed=False, needs_human_review=False,
        model_id="baseline:flag_all", prompt_version="baseline", cost_nzd=0.0,
    )


def rules(ann: Announcement, config: dict, client=None) -> Classification:
    text = f"{ann.headline}\n{ann.body_text}".lower()
    hit = next((kw for kw in MATERIAL_KEYWORDS if kw in text), None)
    is_material = ann.doc_type in MATERIAL_DOC_TYPES or hit is not None
    reason = (f"doc_type {ann.doc_type}" if ann.doc_type in MATERIAL_DOC_TYPES
              else f"keyword '{hit}'" if hit else "no material doc_type or keyword")
    return Classification(
        announcement_id=ann.announcement_id, materiality="material" if is_material else "immaterial",
        confidence=0.70, categories=[ann.doc_type], evidence_quote=_quote(ann),
        rationale=f"rules baseline: {reason}"[:200],
        entities=Entities(), previously_disclosed=False, needs_human_review=False,
        model_id="baseline:rules", prompt_version="baseline", cost_nzd=0.0,
    )


def naive_prompt(ann: Announcement, config: dict, client=None) -> Classification:
    """The v1 prompt, through the real classify path (isolates prompt design)."""
    return classify(ann, config=config, prompt_version="v1", client=client)


BASELINES = {
    "flag_all": flag_all,
    "rules": rules,
    "naive_prompt": naive_prompt,
}
