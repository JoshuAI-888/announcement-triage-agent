"""check_render.py — the Milford HTML email brief + eval_summary.json (CONTRACTS.md §2, §4).

Offline. Synthetic RankedItems + stats drive `src.render_email.render_email` and
assert the rendered HTML carries the material items, the VERBATIM evidence quote,
a clickable filing link, a news link, company/industry context, a price block
with a 7-day bar sparkline, the needs-a-look flags in PLAIN ENGLISH (never a raw
`G#_` code), the "All filings this run" table, and the run footer figures — the
same content brief.py's markdown brief carries, just themed. Also exercises
`src.run`'s run_log row builder (CONTRACTS §3 shape) and
`evals.report.write_eval_summary` on a synthetic ledger/detail (CONTRACTS §2 shape).

`src.company.company_profile` and `src.market.price_snapshot` are monkeypatched
(via `src.enrich`'s module-level references) so `enrich()` never touches the
real network — this environment's .env carries real ANTHROPIC_API_KEY /
TWELVEDATA_API_KEY values.
"""

from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from checks._harness import run
from evals.report import SCORECARD_COLUMNS, write_eval_summary
from src.fetch import load_config
from src.flags import FLAG_VOCAB
from src.models import Announcement, Classification, Entities
from src.rank import RankedItem
from src.run import _run_log_row, append_run_log

import src.enrich as ENRICH_MOD
from src.enrich import enrich

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
CONFIG = load_config()

_RAW_CODE_RE = re.compile(r"\bG[1-6]_[a-z_]+\b")

_FAKE_PRICE = {
    "last": 245.67, "prev_close": 240.10, "change": 5.57, "change_pct": 2.32,
    "currency": "USD", "series7": [230.0, 232.5, 238.0, 236.0, 241.0, 240.10, 245.67],
    "asof": "2026-07-14",
}


def _fake_company_profile(ticker, company_name, industry, config):
    return {
        "industry": industry,
        "business": f"{company_name} makes and sells products in its sector.",
        "edge": "Its edge is a well-known brand and a large distribution network.",
        "caveat": "AI-generated context from general knowledge — verify before relying.",
    }


def _fake_price_snapshot(ticker, config):
    return dict(_FAKE_PRICE)


ENRICH_MOD.company_profile = _fake_company_profile
ENRICH_MOD.price_snapshot = _fake_price_snapshot


def make_ann(ticker, hours_ago=1, headline=None, body="body", industry="Technology"):
    return Announcement(
        announcement_id=(ticker.lower() + "0" * 64)[:64], exchange="EDGAR", ticker=ticker,
        company_name=f"{ticker} Inc.", industry=industry, published_at=NOW - timedelta(hours=hours_ago),
        headline=headline or f"{ticker} raises full-year guidance", doc_type="guidance_change",
        native_doc_type="8-K", native_id=f"acc-{ticker}", issuer_price_sensitive_flag=None,
        body_text=body, char_count=len(body), truncated=False,
        source_url=f"https://sec.gov/{ticker}", fetched_at=NOW,
    )


def make_cls(ann, materiality="material", confidence=0.9, flags=None, quote="body", rationale=None):
    return Classification(
        announcement_id=ann.announcement_id, materiality=materiality, confidence=confidence,
        categories=[ann.doc_type], evidence_quote=quote, rationale=rationale or f"{ann.ticker} rationale",
        entities=Entities(), previously_disclosed=False, needs_human_review=bool(flags),
        model_id="claude-haiku-4-5-20251001", prompt_version="v3", cost_nzd=0.01, guardrail_flags=flags or [],
    )


def body(check):
    # --- build a ranked material list + a needs-a-look list ---
    aapl = make_ann("AAPL", hours_ago=1, headline="AAPL raises full-year guidance")
    msft = make_ann("MSFT", hours_ago=2, headline="MSFT announces acquisition")
    googl = make_ann("GOOGL", hours_ago=1, headline="GOOGL lawsuit filed")
    nvda = make_ann("NVDA", hours_ago=1, headline="NVDA supply agreement")
    intc = make_ann("INTC", hours_ago=1, headline="INTC routine 10-Q filed")

    aapl_c = make_cls(aapl, "material", 0.92, quote="raised full-year guidance to $4.2 billion",
                      rationale="Guidance raise, quantified.")
    msft_c = make_cls(msft, "material", 0.88, quote="agreed to acquire a supplier",
                      rationale="Acquisition announced.")
    googl_c = make_cls(googl, "insufficient_info", 0.5, quote="a lawsuit was filed")
    nvda_c = make_cls(nvda, "material", 0.9, flags=["G2_ungrounded_quote"], quote="unverifiable claim")
    intc_c = make_cls(intc, "immaterial", 0.85, quote="body", rationale="Routine quarterly filing, nothing new.")

    ranked = [
        RankedItem(classification=aapl_c, announcement=aapl, score=0.83, reason="aapl reason"),
        RankedItem(classification=msft_c, announcement=msft, score=0.61, reason="msft reason"),
    ]
    needs_look = [
        RankedItem(classification=googl_c, announcement=googl, score=0.20, reason="googl reason"),
        RankedItem(classification=nvda_c, announcement=nvda, score=0.55, reason="nvda reason"),
    ]
    immaterial_item = RankedItem(classification=intc_c, announcement=intc, score=0.05, reason="intc reason")
    all_items = ranked + needs_look + [immaterial_item]

    stats = {
        "processed": 5, "new": 5, "deduped": 0, "model_primary": "claude-haiku-4-5-20251001",
        "model_escalation": "claude-opus-4-6", "prompt_version": "v3", "escalation_count": 1,
        "guardrail_flag_counts": {"G2_ungrounded_quote": 1}, "material": 2, "needs_look": 2,
        "total_cost_nzd": 0.4567, "runtime_seconds": 12.3,
    }
    enrichment = enrich(ranked, needs_look, CONFIG, news_mode="search")
    check.equal(len(enrichment), 4, "enrich() returns one Enrichment per item across both ranked+needs_look")

    # --- render the digest email ---
    from src.render_email import render_email

    tmp = Path(tempfile.mkdtemp(prefix="email_"))
    DIGEST_RUN_ID = "2026-07-14T00-00-00"
    path = render_email(ranked, needs_look, stats, enrichment, all_items=all_items,
                        brief_date=NOW.date(), run_id=DIGEST_RUN_ID, kind="digest", out_dir=tmp)
    check.equal(path.name, f"{DIGEST_RUN_ID}.email.html", "digest email uses the <run_id>.email.html name")
    html = path.read_text(encoding="utf-8")
    check.require("Daily digest" in html, "the email heading shows the 'Daily digest' kind label")

    check.require("AAPL" in html and "AAPL raises full-year guidance" in html, "material item AAPL is rendered")
    check.require("MSFT" in html and "MSFT announces acquisition" in html, "material item MSFT is rendered")
    check.require("raised full-year guidance to $4.2 billion" in html,
                  "the VERBATIM evidence_quote appears in the rendered HTML")
    check.require(f'href="{aapl.source_url}"' in html, "a clickable filing link (announcement.source_url) is present")
    aapl_news = next(e.news_url for e in enrichment if e.announcement_id == aapl.announcement_id)
    check.require(aapl_news is not None and f'href="{aapl_news}"' in html, "a clickable news link is present")

    # --- company/industry context on material items ---
    check.require("Technology" in html, "the announcement's industry is rendered on a material item")
    check.require("makes and sells products in its sector" in html, "the AI-generated business line is rendered")
    check.require("verify before relying" in html, "the company-profile caveat is rendered")

    # --- price block: last price, change arrow, and a mail-safe (non-svg) sparkline ---
    check.require("245.67" in html, "the price snapshot's last price is rendered")
    check.require("<svg" not in html.lower(), "no inline <svg> anywhere — Gmail strips it")
    check.require("<table" in html, "the sparkline (and the all-filings table) use <table>, not <svg>")

    # --- needs-a-look: plain-English flag labels, never a raw code ---
    check.require("GOOGL" in html and FLAG_VOCAB["insufficient_info"]["label"] in html,
                  "needs-a-look shows the plain-English insufficient_info label for an abstention")
    check.require("NVDA" in html and FLAG_VOCAB["G2_ungrounded_quote"]["label"] in html,
                  "needs-a-look shows the plain-English label for a guardrail flag")
    check.require("Why flagged" in html, "needs-a-look has a 'Why flagged' lead-in")
    check.require(not _RAW_CODE_RE.search(html), "no raw G#_ literal anywhere in the rendered email")
    check.require("insufficient_info" not in html, "no raw 'insufficient_info' literal anywhere in the rendered email")

    # --- footer: guardrail flag counts are expanded to plain English too ---
    check.require(f'{FLAG_VOCAB["G2_ungrounded_quote"]["label"]} (1)' in html,
                  "the footer's guardrail-flag-count line uses the plain-English label")

    # --- "All filings this run" table: every classified filing, including immaterial ---
    check.require("All filings this run" in html, "the all-filings section header is present")
    check.require("INTC" in html, "the immaterial (excluded-from-brief) filing still appears in the all-filings table")
    check.require("Routine quarterly filing, nothing new." in html, "the all-filings table carries the rationale")
    check.require("Material event report (8-K)" in html, "the all-filings table uses the friendly doc_type_label")

    check.require("processed: 4" in html or "Announcements processed: 5" in html, "footer reports processed count")
    check.require("NZ$0.4567" in html, "footer reports total cost")
    check.require("Escalations: 1" in html, "footer reports escalation count")
    check.require("12.3s" in html, "footer reports runtime")
    check.require("<style" not in html.lower() and "@font-face" not in html.lower(),
                  "no <style> block and no @font-face — mail clients drop both")

    # --- empty sections render a clear placeholder, not an empty page ---
    empty_path = render_email([], [], stats, [], brief_date=NOW.date(),
                              run_id="2026-07-14T00-00-01", kind="digest", out_dir=tmp)
    empty_html = empty_path.read_text(encoding="utf-8")
    check.require("No material announcements this run" in empty_html, "empty ranked list has a placeholder")
    check.require("Nothing needs a look this run" in empty_html, "empty needs-look list has a placeholder")
    check.require("No filings classified this run" in empty_html, "empty all-filings list has a placeholder")

    # --- run_id naming: every kind is named by run_id, not by date/time ---
    intraday_dt = datetime(2026, 7, 14, 18, 2, tzinfo=timezone.utc)
    INTRADAY_RUN_ID = "2026-07-14T18-02-00"
    intraday_path = render_email(ranked, needs_look, stats, enrichment, all_items=all_items,
                                 brief_date=intraday_dt, run_id=INTRADAY_RUN_ID, kind="intraday", out_dir=tmp)
    check.equal(intraday_path.name, f"{INTRADAY_RUN_ID}.email.html",
                "an intraday run is named by its own run_id, not a <DATE>T<HH-MM> filename trick")
    intraday_html = intraday_path.read_text(encoding="utf-8")
    check.require("Intraday" in intraday_html, "the intraday email heading shows the 'Intraday' kind label")

    # --- backfill: heading shows the kind + the covered window ---
    BACKFILL_RUN_ID = "2026-07-14T09-00-00"
    backfill_window = {"as_of": "2026-08-02", "lookback_days": 5,
                       "since": "2026-07-28T00:00:00Z", "until": "2026-08-02T23:59:59Z"}
    backfill_path = render_email(ranked, needs_look, stats, enrichment, all_items=all_items,
                                 brief_date=NOW, run_id=BACKFILL_RUN_ID, kind="backfill",
                                 window=backfill_window, out_dir=tmp)
    check.equal(backfill_path.name, f"{BACKFILL_RUN_ID}.email.html", "a backfill is named by its run_id too")
    backfill_html = backfill_path.read_text(encoding="utf-8")
    check.require("Backfill" in backfill_html, "the backfill email heading shows the 'Backfill' kind label")
    check.require("2026-07-28" in backfill_html and "2026-08-02" in backfill_html,
                  "the backfill heading shows the covered window (since..until)")

    # --- brief.py (markdown) mirrors the same content, in markdown form ---
    from src.brief import render_brief

    md_path = render_brief(ranked, needs_look, stats, enrichment=enrichment, all_items=all_items,
                           brief_date=NOW.date(), run_id=DIGEST_RUN_ID, kind="digest", out_dir=tmp)
    check.equal(md_path.name, f"{DIGEST_RUN_ID}.md", "brief.py's markdown twin is also named by run_id")
    md = md_path.read_text(encoding="utf-8")
    check.require("## All filings this run" in md, "brief.py has the all-filings section")
    check.require("INTC" in md, "brief.py's all-filings table carries the immaterial filing")
    check.require(FLAG_VOCAB["G2_ungrounded_quote"]["label"] in md, "brief.py needs-a-look uses the plain-English label")
    check.require(not _RAW_CODE_RE.search(md) and "insufficient_info" not in md,
                  "brief.py leaks no raw G#_ code or 'insufficient_info' literal")
    check.require("makes and sells products in its sector" in md, "brief.py carries the AI business line too")
    check.require("Daily digest" in md, "brief.py heading shows the 'Daily digest' kind label")

    # --- run_log.jsonl row shape (CONTRACTS §3) ---
    digest_window = {"as_of": None, "lookback_days": 1, "since": "2026-07-13T12:00:00Z", "until": None}
    row = _run_log_row("digest", stats, NOW, DIGEST_RUN_ID, digest_window)
    expected_keys = {"date", "ts", "run_id", "kind", "processed", "new", "deduped", "reused", "material",
                     "needs_look", "escalations", "guardrail_flag_counts", "total_cost_nzd", "runtime_seconds",
                     "prompt_version", "model_primary", "window_days", "as_of"}
    check.equal(set(row.keys()), expected_keys, "run_log row carries exactly the CONTRACTS §3 keys")
    check.equal(row["kind"], "digest", "row records kind")
    check.equal(row["run_id"], DIGEST_RUN_ID, "row records run_id")
    check.equal(row["window_days"], 1, "row records window_days from the window dict")
    check.equal(row["as_of"], None, "row records as_of (None for a non-backfill run)")
    check.equal(row["material"], 2, "row records the material count")
    check.equal(row["guardrail_flag_counts"], {"G2_ungrounded_quote": 1}, "row carries guardrail flag counts")
    check.require(row["ts"].endswith("Z"), "ts is a UTC Zulu timestamp")

    backfill_row = _run_log_row("backfill", stats, NOW, BACKFILL_RUN_ID, backfill_window)
    check.equal(backfill_row["as_of"], "2026-08-02", "a backfill row's as_of carries the window's as_of date")
    check.equal(backfill_row["window_days"], 5, "a backfill row's window_days carries the window's lookback_days")

    log_path = tmp / "run_log.jsonl"
    append_run_log(row, log_path)
    append_run_log(_run_log_row("intraday", stats, NOW, INTRADAY_RUN_ID), log_path)
    append_run_log(backfill_row, log_path)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    check.equal(len(lines), 3, "append_run_log appends one JSON line per call (append-only)")
    parsed = [json.loads(l) for l in lines]
    check.equal([p["kind"] for p in parsed], ["digest", "intraday", "backfill"],
               "kind is one of digest/intraday/backfill, in append order")
    check.equal([p["run_id"] for p in parsed], [DIGEST_RUN_ID, INTRADAY_RUN_ID, BACKFILL_RUN_ID],
               "each row's run_id matches what was passed in")

    # --- run-id uniqueness: two runs on the same UTC date get two distinct files,
    #     neither overwriting the other (the whole point of this feature) ---
    briefs_before = set(tmp.glob("*.email.html"))
    render_email(ranked, needs_look, stats, enrichment, all_items=all_items, brief_date=NOW.date(),
                run_id="2026-07-14T11-00-00", kind="digest", out_dir=tmp)
    render_email(ranked, needs_look, stats, enrichment, all_items=all_items, brief_date=NOW.date(),
                run_id="2026-07-14T11-00-01", kind="digest", out_dir=tmp)
    briefs_after = set(tmp.glob("*.email.html"))
    check.equal(len(briefs_after - briefs_before), 2,
               "two runs one second apart on the same UTC date write two distinct files")

    # --- write_eval_summary (CONTRACTS §2 shape) ---
    def _headline(recall, precision, grounded, wrong, abstain, cost):
        return {"recall_material": recall, "precision_material": precision, "grounded_pct": grounded,
                "confidently_wrong": wrong, "abstention_ambiguous": abstain, "cost_per_item_nzd": cost}

    ledger = {"rows": {
        "v3": {"headline": _headline(0.939, 0.408, 0.374, 0.218, 0.30, 0.0186),
               "stability": {}, "meta": {"n": 220, "runs": 3}},
        "baseline: flag_all": {"headline": _headline(1.0, 0.15, 0.0, 0.85, 0.0, 0.0),
                               "stability": {}, "meta": {"n": 220, "runs": 1}},
        "v3 (openai)": {"headline": _headline(0.94, 0.5, 0.94, 0.1, 0.4, 0.03),
                       "stability": {}, "meta": {"n": 220, "runs": 3, "model": "gpt-5.6-terra"}},
    }}
    detail = {"n_items": 220, "runs": 3, "ranking": {"precision_at_5": 0.80, "precision_at_10": 0.80}}
    out_path = tmp / "eval_summary.json"
    summary = write_eval_summary(ledger, detail, "a1b2c3d4e5f60718", out_path)

    check.require(out_path.exists(), "write_eval_summary writes evals/eval_summary.json")
    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    check.equal(on_disk, summary, "the file on disk matches the returned dict")
    check.equal(summary["eval_config_fingerprint"], "a1b2c3d4e5f60718", "fingerprint field is carried through")
    check.equal(summary["n_items"], 220, "n_items comes from detail")
    check.equal(summary["runs"], 3, "runs comes from detail")
    check.equal(summary["ranking"], {"precision_at_5": 0.80, "precision_at_10": 0.80}, "ranking comes from detail")
    check.require(summary["generated_at"].endswith("Z"), "generated_at is a UTC Zulu timestamp")
    check.equal(set(summary["scorecard"]["v3"].keys()), {key for key, _ in SCORECARD_COLUMNS},
                "scorecard row uses exactly the SCORECARD_COLUMNS keys")
    check.equal(summary["scorecard"]["v3"]["recall_material"], 0.939, "scorecard values come from the ledger")
    check.require("baseline: flag_all" in summary["scorecard"], "every ledger row becomes a scorecard row")
    check.equal(len(summary["providers"]), 1, "only the ledger row with a meta.model becomes a providers entry")
    check.equal(summary["providers"][0]["model"], "gpt-5.6-terra", "providers entry carries the model id")
    check.equal(summary["providers"][0]["recall"], 0.94, "providers entry carries its own headline numbers")
    check.require(any("Haiku" in c for c in summary["caveats"]), "caveats include the Haiku-grounding note")

    check.note("offline check — src.company/src.market are monkeypatched, no API calls, no spend")


if __name__ == "__main__":
    run("email brief + markdown brief + eval_summary.json (CONTRACTS §2, §4)", body)
