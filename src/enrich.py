"""enrich.py — citation links + company/price context (deploy build, Phase 1).

Attaches the filing link (already on the `Announcement`) and a deterministic news
link to every ranked item so the HTML email can cite its claims. No API calls, no
network — `news_mode="search"` builds a Google News SEARCH url (zero cost, no key)
from the ticker plus a few keywords lifted from the headline; `news_mode="off"`
omits the news link entirely; `news_mode="resolved"` is a documented Phase 2 stub
(a real news-resolver integration) that falls back to the identical search url
until that lands — the output shape does not change when it does.

Only MATERIAL, guardrail-clean items ever get a news link: a defensive check on
`classification.materiality` means even an accidental needs-a-look item slipped
into the input list gets a filing link but no news link.

`enrich()` also attaches an AI company profile (`src.company`) to every item it
is given — material AND needs-a-look, never the excluded immaterial-clean items,
since those never reach this function (SPEC §10 routes them out before rank())
— and a market price snapshot (`src.market`) to material items only. Both are
best-effort and never raise; a failed lookup just means `company`/`price` is
`None`/industry-only on the returned `Enrichment`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus

from src.company import company_profile
from src.market import price_snapshot
from src.rank import RankedItem

_STOPWORDS = {
    "a", "an", "and", "the", "to", "of", "for", "in", "on", "with", "its", "at",
    "is", "as", "by", "from", "into", "over", "after", "new", "will", "has", "have",
}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]+")


@dataclass
class Enrichment:
    """Citation links + company/price context for one ranked or needs-a-look item."""

    announcement_id: str
    filing_url: str
    news_url: str | None
    news_label: str
    company: dict | None = None
    price: dict | None = None


def _headline_keywords(headline: str, max_words: int = 4) -> list[str]:
    """Pick the first few non-stopword words from the headline, in order."""
    words = _WORD_RE.findall(headline)
    kept = [w for w in words if w.lower() not in _STOPWORDS]
    return (kept or words)[:max_words]


def _search_url(ticker: str, headline: str) -> str:
    """Deterministic Google News search url — zero cost, no API key, no network

    call made by this module; the url is only ever opened by a human reading
    the brief.
    """
    query = " ".join([ticker, *_headline_keywords(headline)])
    return f"https://news.google.com/search?q={quote_plus(query)}"


def enrich(
    ranked_items: list[RankedItem],
    needs_look_items: list[RankedItem],
    config: dict,
    news_mode: str = "search",
) -> list[Enrichment]:
    """Attach filing/news links + company/price context to every ranked & needs-a-look item.

    `ranked_items` and `needs_look_items` are exactly rank()'s two output lists —
    together they are every classified filing that is not immaterial-and-clean
    (SPEC §10 excludes those from the brief entirely, so they never reach here).
    That's what bounds the company-profile cost to "material + needs-a-look"
    rather than every filing this run classified.

    `news_mode`:
      - "search"   (default) deterministic Google News search url from ticker + headline.
      - "off"      filing link only, no news link.
      - "resolved" Phase 2 stub: no live resolver is wired up yet, so this falls back
                   to the identical "search" url — the output shape is stable for
                   when a real resolver lands, but no behaviour changes today.
    """
    if news_mode not in ("search", "off", "resolved"):
        raise ValueError(f"unknown news_mode {news_mode!r}")

    out: list[Enrichment] = []
    for item in [*ranked_items, *needs_look_items]:
        ann = item.announcement
        is_material = item.classification.materiality == "material" and not item.classification.guardrail_flags
        if news_mode == "off" or not is_material:
            news_url, news_label = None, ""
        else:  # "search" and "resolved" (documented fallback) behave identically today
            news_url = _search_url(ann.ticker, ann.headline)
            news_label = "News search"

        # Best-effort, never raises (see src.company / src.market docstrings).
        company = company_profile(ann.ticker, ann.company_name, ann.industry, config)
        price = price_snapshot(ann.ticker, config) if is_material else None

        out.append(Enrichment(
            announcement_id=ann.announcement_id,
            filing_url=ann.source_url,
            news_url=news_url,
            news_label=news_label,
            company=company,
            price=price,
        ))
    return out
