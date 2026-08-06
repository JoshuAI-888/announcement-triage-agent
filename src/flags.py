"""flags.py — plain-English vocabulary for guardrail flags + doc types (deploy build, Phase 1).

The portal (dashboard/) and every renderer in this build (render_email.py,
brief.py, run.py's out/filings/<date>.json writer) must NEVER show a raw
`G#_...` code or the literal `insufficient_info` to a human — everywhere one of
those codes would otherwise surface, it is expanded through `FLAG_VOCAB` first.
This is the single source of truth for that vocabulary, frozen by CONTRACTS.md
so the portal's own copy stays in lock-step.

`doc_type_label()` is the same idea for document types: `Announcement.doc_type`
is the canonical enum (SPEC.md §5.3 / config/doc_type_map.yaml), but a human
reads "Material event report (8-K)", not "operational_incident".
"""

from __future__ import annotations

from typing import Optional

# --- guardrail-flag vocabulary (CONTRACTS.md — frozen, exact copy) -----------

FLAG_VOCAB: dict[str, dict[str, str]] = {
    "G2_ungrounded_quote": {
        "label": "Unverified quote",
        "meaning": "The supporting quote couldn't be found word-for-word in the filing.",
        "why": "Possible paraphrase or model error — confirm the quote against the source before relying on it.",
    },
    "G3_unverified_amount": {
        "label": "Unverified figure",
        "meaning": "One or more dollar/number figures the model cited couldn't be matched in the filing and were removed.",
        "why": "Treat amounts as unconfirmed — check the filing for the actual numbers.",
    },
    "G5_low_confidence": {
        "label": "Low confidence",
        "meaning": "The model's confidence was below the threshold, so the call was downgraded to 'Needs more info'.",
        "why": "The signal was weak or ambiguous — a person should read the filing to decide.",
    },
    "G6_directional_language": {
        "label": "Advice wording removed",
        "meaning": "The draft contained buy/sell-style wording, which this system may not publish.",
        "why": "Wording was withheld for compliance — the underlying facts still stand; read them directly.",
    },
    "G1_parse_error": {
        "label": "Unreadable model output",
        "meaning": "The model returned malformed output that couldn't be parsed.",
        "why": "The item was retried and set aside — no classification was produced.",
    },
    "G4_off_watchlist": {
        "label": "Off-watchlist",
        "meaning": "The filer isn't on your watchlist.",
        "why": "Dropped from the brief by design.",
    },
    # Pseudo-key: an abstention, not a G-flag (Classification.guardrail_flags
    # never contains this literal — materiality=="insufficient_info" is a
    # separate field). Renderers reach for this entry when a record has no
    # guardrail_flags but is still an abstention.
    "insufficient_info": {
        "label": "Needs more info",
        "meaning": "There wasn't enough in the filing to judge materiality confidently.",
        "why": "Flagged for a person to review.",
    },
}

MATERIALITY_LABEL: dict[str, str] = {
    "material": "Material",
    "immaterial": "Immaterial",
    "insufficient_info": "Needs more info",
}

# Display mapping for a run's `kind` (CONTRACTS.md — frozen). The internal enum
# slug (`"digest"`/`"intraday"`/`"backfill"`) never changes — only what's shown
# to a human does. Single source of truth for the Python side; the portal's own
# copy lives in dashboard/lib/flags.ts.
KIND_LABEL: dict[str, str] = {
    "digest": "Daily digest",
    "intraday": "Intraday",
    "backfill": "Backfill",
}


def explain_flag(code: str) -> dict[str, str]:
    """Plain-English `{label, meaning, why}` for one flag code.

    An unknown code degrades gracefully — it must never raise, since a future
    guardrail or a hand-edited record could carry a code this vocabulary
    hasn't caught up with yet.
    """
    entry = FLAG_VOCAB.get(code)
    if entry is None:
        return {"label": code, "meaning": code, "why": ""}
    return dict(entry)


def explain_flags(codes: list[str]) -> list[dict[str, str]]:
    """`explain_flag` over a list, in order."""
    return [explain_flag(code) for code in codes]


# --- doc-type vocabulary -------------------------------------------------

# Native-form-specific labels take priority over the canonical-doc_type
# fallback below: the same canonical doc_type (e.g. "operational_incident")
# covers a wide family of native forms (8-K, 6-K, ...), and a human wants to
# know which one this actually was. Keys are EDGAR native form strings,
# uppercased (matches config/doc_type_map.yaml's EDGAR block).
_NATIVE_FORM_LABELS: dict[str, str] = {
    "8-K": "Material event report (8-K)",
    "8-K/A": "Material event report, amended (8-K/A)",
    "6-K": "Foreign private issuer report (6-K)",
    "10-Q": "Quarterly report (10-Q)",
    "10-Q/A": "Quarterly report, amended (10-Q/A)",
    "10-K": "Annual report (10-K)",
    "10-K/A": "Annual report, amended (10-K/A)",
    "20-F": "Annual report — foreign private issuer (20-F)",
    "40-F": "Annual report — Canadian issuer (40-F)",
    "11-K": "Employee benefit plan annual report (11-K)",
    "3": "Initial insider ownership (Form 3)",
    "3/A": "Initial insider ownership, amended (Form 3/A)",
    "4": "Insider trade (Form 4)",
    "4/A": "Insider trade, amended (Form 4/A)",
    "5": "Annual insider ownership (Form 5)",
    "5/A": "Annual insider ownership, amended (Form 5/A)",
    "144": "Notice of proposed insider sale (Form 144)",
    "144/A": "Notice of proposed insider sale, amended (Form 144/A)",
    "424B1": "Prospectus supplement (424B1)",
    "424B2": "Prospectus supplement (424B2)",
    "424B3": "Prospectus supplement (424B3)",
    "424B4": "Prospectus supplement (424B4)",
    "424B5": "Prospectus supplement (424B5)",
    "424B7": "Prospectus supplement (424B7)",
    "424B8": "Prospectus supplement (424B8)",
    "FWP": "Free writing prospectus (FWP)",
    "S-1": "IPO registration statement (S-1)",
    "S-3": "Shelf registration statement (S-3)",
    "S-3ASR": "Automatic shelf registration statement (S-3ASR)",
    "S-8": "Employee stock plan registration (S-8)",
    "S-4": "Merger/acquisition registration statement (S-4)",
    "S-4/A": "Merger/acquisition registration statement, amended (S-4/A)",
    "SC 13E3": "Going-private transaction statement (SC 13E3)",
    "SC TO-T": "Tender offer statement (SC TO-T)",
    "SC 14D9": "Tender offer response (SC 14D9)",
    "SCHEDULE 13D": "Beneficial ownership report (13D)",
    "SCHEDULE 13D/A": "Beneficial ownership report, amended (13D/A)",
    "SCHEDULE 13G": "Passive ownership report (13G)",
    "SCHEDULE 13G/A": "Passive ownership report, amended (13G/A)",
    "DEF 14A": "Proxy statement (DEF 14A)",
    "DEFA14A": "Additional proxy material (DEFA14A)",
    "PX14A6G": "Exempt shareholder solicitation (PX14A6G)",
    "13F-HR": "Institutional holdings report (13F-HR)",
    "13F-HR/A": "Institutional holdings report, amended (13F-HR/A)",
    "IRANNOTICE": "Iran-related disclosure notice",
    "SD": "Specialised disclosure report (SD)",
    "ARS": "Annual report to shareholders (ARS)",
}

# Fallback when the native form isn't in the table above — keyed by the
# canonical Category enum (SPEC.md §5.3 / src/models.py).
_CANONICAL_LABELS: dict[str, str] = {
    "guidance_change": "Guidance update",
    "earnings_result": "Quarterly results",
    "m_and_a": "M&A / deal",
    "capital_raise": "Capital raise",
    "director_dealing": "Insider transaction",
    "contract_award": "Contract award",
    "operational_incident": "Operational update",
    "governance_change": "Governance change",
    "index_change": "Index change",
    "regulatory": "Regulatory filing",
    "admin": "Administrative filing",
}


def doc_type_label(canonical_doc_type: str, native_form: Optional[str] = None) -> str:
    """A friendly label for a document type.

    Tries the native-form-specific label first (most specific — "8-K" ->
    "Material event report (8-K)"), then the canonical-doc_type fallback
    ("earnings_result" -> "Quarterly results"), then the raw native form
    string itself. Never raises, never returns empty.
    """
    form_key = (native_form or "").strip().upper()
    if form_key in _NATIVE_FORM_LABELS:
        return _NATIVE_FORM_LABELS[form_key]
    if canonical_doc_type in _CANONICAL_LABELS:
        return _CANONICAL_LABELS[canonical_doc_type]
    return native_form or canonical_doc_type or "Filing"
