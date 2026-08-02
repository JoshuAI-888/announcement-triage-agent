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


def rank(
    pairs: list[tuple[Classification, Announcement]],
    config: dict,
    now: datetime | None = None,
) -> tuple[list[RankedItem], list[RankedItem]]:
    """Split into (ranked material, needs-a-look) and sort the ranked list by score.

    Ranked  = material, no guardrail flag, not an abstention.
    Needs a look = any abstention OR any guardrail flag (never mixed in, never buried).
    Immaterial-and-clean records appear in neither — there is nothing to see.
    """
    now = now or datetime.now(timezone.utc)
    ranked: list[RankedItem] = []
    needs_look: list[RankedItem] = []
    for c, ann in pairs:
        score, reason = score_one(c, ann, config, now)
        item = RankedItem(classification=c, announcement=ann, score=score, reason=reason)
        if is_needs_a_look(c):
            needs_look.append(item)
        elif c.materiality == "material":
            ranked.append(item)
        # else: immaterial + clean → excluded from the brief
    ranked.sort(key=lambda it: it.score, reverse=True)
    needs_look.sort(key=lambda it: it.score, reverse=True)
    return ranked, needs_look
