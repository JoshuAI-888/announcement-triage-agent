"""check_enrich.py — citation links + company/price context (deploy build, Phase 1).

Offline, no network, no API — `enrich()` itself never makes a network call; it
only ever builds a url string and delegates to `src.company`/`src.market`,
BOTH of which are monkeypatched here to canned in-memory results (this
environment's .env carries real ANTHROPIC_API_KEY/TWELVEDATA_API_KEY values, so
this check must not let the real functions run). Asserts the news url is
well-formed, that only material and guardrail-clean items ever get a news link
AND a price snapshot, that company profiles reach material AND needs-a-look
items alike (never every filing), and that the three `news_mode` values
(search / off / resolved) behave as documented.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from checks._harness import run
from src.fetch import load_config
from src.models import Announcement, Classification, Entities
from src.rank import RankedItem

import src.enrich as ENRICH_MOD
from src.enrich import enrich

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
CONFIG = load_config()

_FAKE_COMPANY = {
    "industry": None, "business": "Fake Co. makes things.", "edge": "Fake moat.",
    "caveat": "AI-generated context from general knowledge — verify before relying.",
}
_FAKE_PRICE = {
    "last": 101.5, "prev_close": 100.0, "change": 1.5, "change_pct": 1.5,
    "currency": "USD", "series7": [98, 99, 100, 100.5, 101, 100.8, 101.5], "asof": "2026-07-14",
}


def _fake_company_profile(ticker, company_name, industry, config):
    return {**_FAKE_COMPANY, "industry": industry}


def _fake_price_snapshot(ticker, config):
    return dict(_FAKE_PRICE)


# Monkeypatch the module-level names enrich() calls — never the real network/API.
ENRICH_MOD.company_profile = _fake_company_profile
ENRICH_MOD.price_snapshot = _fake_price_snapshot


def make_ann(ticker, headline):
    return Announcement(
        announcement_id=(ticker.lower() + "0" * 64)[:64], exchange="EDGAR", ticker=ticker,
        company_name=f"{ticker} Inc.", industry="Technology", published_at=NOW - timedelta(hours=1),
        headline=headline, doc_type="guidance_change", native_doc_type="8-K", native_id=f"acc-{ticker}",
        issuer_price_sensitive_flag=None, body_text="body", char_count=4, truncated=False,
        source_url=f"https://sec.gov/{ticker}", fetched_at=NOW,
    )


def make_item(ticker, headline, materiality="material", flags=None):
    ann = make_ann(ticker, headline)
    c = Classification(
        announcement_id=ann.announcement_id, materiality=materiality, confidence=0.9,
        categories=[ann.doc_type], evidence_quote="body", rationale=f"{ticker} rationale",
        entities=Entities(), previously_disclosed=False, needs_human_review=bool(flags),
        model_id="claude-haiku-4-5-20251001", prompt_version="v3", cost_nzd=0.01, guardrail_flags=flags or [],
    )
    return RankedItem(classification=c, announcement=ann, score=0.5, reason="reason")


def body(check):
    clean_material = make_item("AAPL", "AAPL raises full-year guidance to $4.2 billion")
    flagged_material = make_item("MSFT", "MSFT reports results", flags=["G2_ungrounded_quote"])
    abstention = make_item("GOOGL", "GOOGL lawsuit filed", materiality="insufficient_info")
    # Real routing: rank() would put clean_material in "ranked" and the other
    # two in "needs_look" — enrich()'s two-list signature mirrors that exactly.
    ranked_items = [clean_material]
    needs_look_items = [flagged_material, abstention]

    # --- news_mode="search": deterministic, well-formed Google News search url ---
    enriched = enrich(ranked_items, needs_look_items, CONFIG, news_mode="search")
    check.equal(len(enriched), 3, "enrich() returns one Enrichment per item, across both lists")
    by_id = {e.announcement_id: e for e in enriched}
    clean_enr = by_id[clean_material.announcement.announcement_id]

    check.equal(clean_enr.filing_url, clean_material.announcement.source_url,
                "filing_url is the announcement's source_url")
    check.require(clean_enr.news_url is not None, "a material, guardrail-clean item gets a news url")
    parsed = urlsplit(clean_enr.news_url)
    check.equal(parsed.scheme, "https", "news url is well-formed: https scheme")
    check.equal(parsed.netloc, "news.google.com", "news url is well-formed: points at news.google.com")
    check.require("q=" in parsed.query, "news url is well-formed: carries a q= search query")
    check.require(" " not in clean_enr.news_url, "news url has no raw spaces (query is percent/plus-encoded)")
    check.require("AAPL" in clean_enr.news_url, "news url query is built from the ticker")
    check.equal(clean_enr.news_label, "News search", "news_label documents what the link is")

    # --- only material AND guardrail-clean items get news, even under "search" ---
    flagged_enr = by_id[flagged_material.announcement.announcement_id]
    abstention_enr = by_id[abstention.announcement.announcement_id]
    check.require(flagged_enr.news_url is None, "a guardrail-flagged item gets no news url, even in search mode")
    check.require(abstention_enr.news_url is None, "a non-material (abstention) item gets no news url")
    check.equal(flagged_enr.filing_url, flagged_material.announcement.source_url,
                "a flagged item still gets its filing url")

    # --- company profile: reaches material AND needs-a-look items alike ---
    check.require(clean_enr.company is not None, "a material item gets a company profile")
    check.equal(clean_enr.company["business"], _FAKE_COMPANY["business"], "company profile carries the business line")
    check.equal(clean_enr.company["industry"], "Technology", "company profile carries the announcement's industry")
    check.require(flagged_enr.company is not None, "a needs-a-look (flagged) item ALSO gets a company profile")
    check.require(abstention_enr.company is not None, "a needs-a-look (abstention) item ALSO gets a company profile")

    # --- price snapshot: material items ONLY ---
    check.require(clean_enr.price is not None, "a material item gets a price snapshot")
    check.equal(clean_enr.price["last"], _FAKE_PRICE["last"], "price snapshot carries the fake last price")
    check.require(flagged_enr.price is None, "a guardrail-flagged item gets NO price snapshot")
    check.require(abstention_enr.price is None, "an abstention gets NO price snapshot")

    # --- news_mode="off": filing only, no news links for anyone ---
    off = enrich(ranked_items, needs_look_items, CONFIG, news_mode="off")
    check.require(all(e.news_url is None for e in off), "news_mode='off' gives no news url to any item")
    check.require(all(e.news_label == "" for e in off), "news_mode='off' gives an empty news_label")
    check.require(all(e.filing_url for e in off), "news_mode='off' still carries the filing link")

    # --- news_mode="resolved": Phase 2 stub, falls back to the identical search url today ---
    resolved = enrich(ranked_items, needs_look_items, CONFIG, news_mode="resolved")
    resolved_clean = next(e for e in resolved if e.announcement_id == clean_material.announcement.announcement_id)
    check.equal(resolved_clean.news_url, clean_enr.news_url,
                "news_mode='resolved' falls back to the same deterministic url as 'search' (documented stub)")

    # --- unknown news_mode is rejected loudly ---
    check.raises(ValueError, lambda: enrich(ranked_items, needs_look_items, CONFIG, news_mode="bogus"),
                "an unknown news_mode is rejected")

    check.note("offline check — src.company/src.market are monkeypatched, no network calls, no API spend")


if __name__ == "__main__":
    run("citation links + company/price context (enrich.py)", body)
