"""check_render.py — the Milford HTML email brief + eval_summary.json (CONTRACTS.md §2, §4).

Offline. Synthetic RankedItems + stats drive `src.render_email.render_email` and
assert the rendered HTML carries the material items, the VERBATIM evidence quote,
a clickable filing link, a news link, the named needs-a-look flags, and the run
footer figures — the same content brief.py's markdown brief carries, just themed.
Also exercises `src.run`'s run_log row builder (CONTRACTS §3 shape) and
`evals.report.write_eval_summary` on a synthetic ledger/detail (CONTRACTS §2 shape).
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from checks._harness import run
from evals.report import SCORECARD_COLUMNS, write_eval_summary
from src.enrich import enrich
from src.models import Announcement, Classification, Entities
from src.rank import RankedItem
from src.run import _run_log_row, append_run_log

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def make_ann(ticker, hours_ago=1, headline=None, body="body"):
    return Announcement(
        announcement_id=(ticker.lower() + "0" * 64)[:64], exchange="EDGAR", ticker=ticker,
        company_name=f"{ticker} Inc.", published_at=NOW - timedelta(hours=hours_ago),
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

    aapl_c = make_cls(aapl, "material", 0.92, quote="raised full-year guidance to $4.2 billion",
                      rationale="Guidance raise, quantified.")
    msft_c = make_cls(msft, "material", 0.88, quote="agreed to acquire a supplier",
                      rationale="Acquisition announced.")
    googl_c = make_cls(googl, "insufficient_info", 0.5, quote="a lawsuit was filed")
    nvda_c = make_cls(nvda, "material", 0.9, flags=["G2_ungrounded_quote"], quote="unverifiable claim")

    ranked = [
        RankedItem(classification=aapl_c, announcement=aapl, score=0.83, reason="aapl reason"),
        RankedItem(classification=msft_c, announcement=msft, score=0.61, reason="msft reason"),
    ]
    needs_look = [
        RankedItem(classification=googl_c, announcement=googl, score=0.20, reason="googl reason"),
        RankedItem(classification=nvda_c, announcement=nvda, score=0.55, reason="nvda reason"),
    ]
    stats = {
        "processed": 4, "new": 4, "deduped": 0, "model_primary": "claude-haiku-4-5-20251001",
        "model_escalation": "claude-opus-4-6", "prompt_version": "v3", "escalation_count": 1,
        "guardrail_flag_counts": {"G2_ungrounded_quote": 1}, "material": 2, "needs_look": 2,
        "total_cost_nzd": 0.4567, "runtime_seconds": 12.3,
    }
    enrichment = enrich(ranked, news_mode="search")
    check.equal(len(enrichment), 2, "enrich() returns one Enrichment per ranked item")

    # --- render the digest email ---
    from src.render_email import render_email

    tmp = Path(tempfile.mkdtemp(prefix="email_"))
    path = render_email(ranked, needs_look, stats, enrichment, brief_date=NOW.date(), out_dir=tmp)
    check.equal(path.name, "2026-07-14.email.html", "digest email uses the plain <DATE>.email.html name")
    html = path.read_text(encoding="utf-8")

    check.require("AAPL" in html and "AAPL raises full-year guidance" in html, "material item AAPL is rendered")
    check.require("MSFT" in html and "MSFT announces acquisition" in html, "material item MSFT is rendered")
    check.require("raised full-year guidance to $4.2 billion" in html,
                  "the VERBATIM evidence_quote appears in the rendered HTML")
    check.require(f'href="{aapl.source_url}"' in html, "a clickable filing link (announcement.source_url) is present")
    aapl_news = next(e.news_url for e in enrichment if e.announcement_id == aapl.announcement_id)
    check.require(aapl_news is not None and f'href="{aapl_news}"' in html, "a clickable news link is present")
    check.require("GOOGL" in html and "abstained (insufficient_info)" in html,
                  "needs-a-look names the abstention")
    check.require("NVDA" in html and "G2_ungrounded_quote" in html, "needs-a-look names the guardrail flag")
    check.require("processed: 4" in html or "Announcements processed: 4" in html, "footer reports processed count")
    check.require("NZ$0.4567" in html, "footer reports total cost")
    check.require("Escalations: 1" in html, "footer reports escalation count")
    check.require("12.3s" in html, "footer reports runtime")
    check.require("<style" not in html.lower() and "@font-face" not in html.lower(),
                  "no <style> block and no @font-face — mail clients drop both")

    # --- empty sections render a clear placeholder, not an empty page ---
    empty_path = render_email([], [], stats, [], brief_date=NOW.date(), out_dir=tmp)
    empty_html = empty_path.read_text(encoding="utf-8")
    check.require("No material announcements this run" in empty_html, "empty ranked list has a placeholder")
    check.require("Nothing needs a look this run" in empty_html, "empty needs-look list has a placeholder")

    # --- intraday filename: a datetime with a non-midnight time gets <DATE>T<HH-MM> ---
    intraday_dt = datetime(2026, 7, 14, 18, 2, tzinfo=timezone.utc)
    intraday_path = render_email(ranked, needs_look, stats, enrichment, brief_date=intraday_dt, out_dir=tmp)
    check.equal(intraday_path.name, "2026-07-14T18-02.email.html",
                "a datetime with a non-midnight time gets the intraday <DATE>T<HH-MM> filename")

    # --- run_log.jsonl row shape (CONTRACTS §3) ---
    row = _run_log_row("digest", stats, NOW)
    expected_keys = {"date", "ts", "kind", "processed", "new", "deduped", "material", "needs_look",
                     "escalations", "guardrail_flag_counts", "total_cost_nzd", "runtime_seconds",
                     "prompt_version", "model_primary", "dashboard_url"}
    check.equal(set(row.keys()), expected_keys, "run_log row carries exactly the CONTRACTS §3 keys")
    check.equal(row["kind"], "digest", "row records kind")
    check.equal(row["material"], 2, "row records the material count")
    check.equal(row["guardrail_flag_counts"], {"G2_ungrounded_quote": 1}, "row carries guardrail flag counts")
    check.require(row["ts"].endswith("Z"), "ts is a UTC Zulu timestamp")

    log_path = tmp / "run_log.jsonl"
    append_run_log(row, log_path)
    append_run_log(_run_log_row("intraday", stats, NOW), log_path)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    check.equal(len(lines), 2, "append_run_log appends one JSON line per call (append-only)")
    parsed = [json.loads(l) for l in lines]
    check.equal([p["kind"] for p in parsed], ["digest", "intraday"], "kind is one of digest/intraday, in append order")

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

    check.note("offline check — no API calls, no spend")


if __name__ == "__main__":
    run("email brief + eval_summary.json (CONTRACTS §2, §4)", body)
