"""check_enrich.py — citation links for ranked material items (deploy build, Phase 1).

Offline, no network, no API — `enrich()` never makes a network call; it only ever
BUILDS a url string. Asserts the news url is well-formed, that only material and
guardrail-clean items ever get a news link, and that the three `news_mode` values
(search / off / resolved) behave as documented.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from checks._harness import run
from src.enrich import enrich
from src.models import Announcement, Classification, Entities
from src.rank import RankedItem

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def make_ann(ticker, headline):
    return Announcement(
        announcement_id=(ticker.lower() + "0" * 64)[:64], exchange="EDGAR", ticker=ticker,
        company_name=f"{ticker} Inc.", published_at=NOW - timedelta(hours=1), headline=headline,
        doc_type="guidance_change", native_doc_type="8-K", native_id=f"acc-{ticker}",
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
    items = [clean_material, flagged_material, abstention]

    # --- news_mode="search": deterministic, well-formed Google News search url ---
    enriched = enrich(items, news_mode="search")
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

    # --- news_mode="off": filing only, no news links for anyone ---
    off = enrich(items, news_mode="off")
    check.require(all(e.news_url is None for e in off), "news_mode='off' gives no news url to any item")
    check.require(all(e.news_label == "" for e in off), "news_mode='off' gives an empty news_label")
    check.require(all(e.filing_url for e in off), "news_mode='off' still carries the filing link")

    # --- news_mode="resolved": Phase 2 stub, falls back to the identical search url today ---
    resolved = enrich(items, news_mode="resolved")
    resolved_clean = next(e for e in resolved if e.announcement_id == clean_material.announcement.announcement_id)
    check.equal(resolved_clean.news_url, clean_enr.news_url,
                "news_mode='resolved' falls back to the same deterministic url as 'search' (documented stub)")

    # --- unknown news_mode is rejected loudly ---
    check.raises(ValueError, lambda: enrich(items, news_mode="bogus"), "an unknown news_mode is rejected")

    check.note("offline check — no network calls, no API spend")


if __name__ == "__main__":
    run("citation links for ranked material items (enrich.py)", body)
