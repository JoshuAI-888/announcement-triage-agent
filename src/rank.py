"""rank.py — transparent, hand-set ranking (SPEC.md §10). Increment 8.

    score = materiality_weight[materiality]
          * confidence
          * 0.5 ** (hours_since_published / recency_half_life_hours)
          * watchlist_weight[ticker]

No learned model. Every score decomposes into one sentence (`reason`), so "why is
this third?" always has an answer. Records that abstain (insufficient_info) or that
raised any guardrail flag never enter the ranked list — they go to "Needs a look".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from src.models import Announcement, Classification


@dataclass
class RankedItem:
    classification: Classification
    announcement: Announcement
    score: float
    reason: str


def _watchlist_weight(ticker: str, config: dict) -> float:
    ranking = config["ranking"]
    return ranking.get("watchlist_weight", {}).get(ticker, ranking["watchlist_weight_default"])


def score_one(c: Classification, ann: Announcement, config: dict, now: datetime) -> tuple[float, str]:
    ranking = config["ranking"]
    mw = ranking["materiality_weight"][c.materiality]
    half_life = ranking["recency_half_life_hours"]
    hours = (now - ann.published_at).total_seconds() / 3600.0
    recency = 0.5 ** (hours / half_life)
    ww = _watchlist_weight(ann.ticker, config)
    score = mw * c.confidence * recency * ww
    reason = (f"materiality={c.materiality} (w {mw}) × confidence {c.confidence:.2f} × "
              f"recency {recency:.2f} ({hours:.0f}h, half-life {half_life}h) × "
              f"watchlist {ww} → score {score:.3f}")
    return score, reason


def is_needs_a_look(c: Classification) -> bool:
    return bool(c.guardrail_flags) or c.materiality == "insufficient_info"


# The single source of truth for which of the three brief TIERS a classification
# lands in. rank(), the filings counts, the per-row tier field and the portal must
# all agree, so they all go through here.
#
# Materiality wins over a guardrail flag: a filing the model calls material stays in
# the MATERIAL tier even when a data-quality flag (unverified quote/figure) is present
# — the flag is about the model's OUTPUT, not whether the filing matters, so it shows
# as a "verify this" signal on the material item rather than demoting it. "Needs a
# look" is therefore the NON-material items that still want a human eye: abstentions
# (insufficient_info) and flagged immaterial items.
def tier_of(c: Classification) -> str:
    if c.materiality == "material":
        return "material"
    if is_needs_a_look(c):
        return "needs_look"
    return "immaterial"


def rank(
    pairs: list[tuple[Classification, Announcement]],
    config: dict,
    now: datetime | None = None,
) -> tuple[list[RankedItem], list[RankedItem]]:
    """Split into (ranked material, needs-a-look) and sort the ranked list by score.

    Ranked  = material (materiality wins; a guardrail flag does NOT demote it — it
              rides along as a "verify this" signal on the item).
    Needs a look = NON-material items that still want a human eye: abstentions
              (insufficient_info) and flagged immaterial items.
    Immaterial-and-clean records appear in neither — there is nothing to see.

    Routing goes through tier_of so rank(), the counts and the portal never diverge.
    """
    now = now or datetime.now(timezone.utc)
    ranked: list[RankedItem] = []
    needs_look: list[RankedItem] = []
    for c, ann in pairs:
        score, reason = score_one(c, ann, config, now)
        item = RankedItem(classification=c, announcement=ann, score=score, reason=reason)
        tier = tier_of(c)
        if tier == "material":
            ranked.append(item)
        elif tier == "needs_look":
            needs_look.append(item)
        # else: immaterial + clean → excluded from the brief
    ranked.sort(key=lambda it: it.score, reverse=True)
    needs_look.sort(key=lambda it: it.score, reverse=True)
    return ranked, needs_look
