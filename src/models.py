"""Pydantic data contracts for the Announcement Triage Agent.

These models are the contract between every module (SPEC.md §5). They are the
only place the shape of an Announcement or a Classification is defined.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# --- Enums (fixed vocabularies) ----------------------------------------------

Exchange = Literal["NZX", "ASX", "EDGAR"]

Materiality = Literal["material", "immaterial", "insufficient_info"]

# Category enum (SPEC.md §5.3) — the model must not invent categories.
# Canonical doc_type values (SPEC.md §6.2) are drawn from this same vocabulary,
# with unknown native types mapping to "admin".
Category = Literal[
    "guidance_change",
    "earnings_result",
    "m_and_a",
    "capital_raise",
    "director_dealing",
    "contract_award",
    "operational_incident",
    "governance_change",
    "index_change",
    "regulatory",
    "admin",
]


# --- Canonical record (SPEC.md §5.1) -----------------------------------------

class Announcement(BaseModel):
    """Canonical announcement record — one per fetched announcement."""

    model_config = ConfigDict(extra="forbid")

    announcement_id: str  # sha256, see compute_id(); primary key, makes the system idempotent
    exchange: Exchange
    ticker: str  # uppercase
    company_name: str
    published_at: datetime  # timezone-aware; store UTC, render NZT
    headline: str
    doc_type: Category  # canonical enum (§6.2)
    native_doc_type: str  # as supplied by the source, kept for audit
    native_id: str  # source's own unique id (EDGAR: accession number); folded into announcement_id
    issuer_price_sensitive_flag: Optional[bool] = None  # None where the exchange supplies none
    body_text: str  # plain text, whitespace-normalised
    char_count: int
    truncated: bool  # True if body_text was cut at truncate_input_chars
    source_url: str
    fetched_at: datetime

    @staticmethod
    def compute_id(
        exchange: str,
        ticker: str,
        published_at: datetime,
        headline: str,
        native_id: str,
    ) -> str:
        """Deterministic primary key: sha256 of exchange|ticker|iso-time|headline|native_id.

        native_id (the source's own unique id) guarantees distinct filings never
        collide even when exchange/ticker/time/headline are identical (SPEC.md §5.1).
        """
        raw = f"{exchange}|{ticker}|{published_at.isoformat()}|{headline}|{native_id}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --- Agent output (SPEC.md §5.2) ---------------------------------------------

class Entities(BaseModel):
    """Extracted entities. Each list defaults to empty."""

    model_config = ConfigDict(extra="forbid")

    amounts: list[str] = Field(default_factory=list)
    counterparties: list[str] = Field(default_factory=list)
    effective_dates: list[str] = Field(default_factory=list)


class Classification(BaseModel):
    """Agent output — schema is enforced (guardrail G1 parses against this).

    The first block is what the model returns. The runtime-metadata block is
    appended by classify.py, never by the model, so those fields are optional.
    """

    model_config = ConfigDict(extra="forbid")

    # --- Returned by the model ---
    announcement_id: str
    materiality: Materiality
    confidence: float = Field(ge=0.0, le=1.0)
    categories: list[Category]
    evidence_quote: str = Field(max_length=200)  # verbatim span, max 200 chars
    rationale: str = Field(max_length=200)  # one line, max 200 chars
    entities: Entities
    previously_disclosed: bool
    needs_human_review: bool

    # --- Runtime metadata appended by classify.py (not by the model) ---
    model_id: Optional[str] = None
    prompt_version: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_nzd: Optional[float] = None
    latency_ms: Optional[int] = None
    escalated: Optional[bool] = None
    guardrail_flags: list[str] = Field(default_factory=list)
