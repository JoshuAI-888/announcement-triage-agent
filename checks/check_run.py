"""check_run.py — C1: rank + brief + run CLI (SPEC §10–12).

Offline. Stub client, throwaway sqlite, no-op sleeper — exercises ranking routing
and order, the three-section brief with its self-reporting footer, and the run
orchestrator's execution semantics: idempotency, dead-letter (run continues),
2s/8s retry backoff, dry-run, and watermark discipline. No network, no spend.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from checks._harness import run
from src import run as RUN
from src.brief import render_brief
from src.fetch import load_config
from src.models import Announcement, Classification, Entities
from src.rank import rank
from src.store import Store

CONFIG = load_config()
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def make_ann(ticker, hours_ago=1, body="body", doc_type="guidance_change"):
    return Announcement(
        announcement_id=(ticker.lower() + "0" * 64)[:64], exchange="EDGAR", ticker=ticker,
        company_name=f"{ticker} Inc.", published_at=NOW - timedelta(hours=hours_ago),
        headline=f"{ticker} headline", doc_type=doc_type, native_doc_type="8-K", native_id=f"acc-{ticker}",
        issuer_price_sensitive_flag=None, body_text=body, char_count=len(body), truncated=False,
        source_url=f"https://sec.gov/{ticker}", fetched_at=NOW,
    )


def make_cls(ann, materiality="material", confidence=0.9, flags=None, quote="body"):
    return Classification(
        announcement_id=ann.announcement_id, materiality=materiality, confidence=confidence,
        categories=[ann.doc_type], evidence_quote=quote, rationale=f"{ann.ticker} rationale",
        entities=Entities(), previously_disclosed=False, needs_human_review=bool(flags),
        model_id="m", prompt_version="v1", cost_nzd=0.01, guardrail_flags=flags or [],
    )


def body(check):
    # --- ranking: routing + order + one-sentence reason ---
    aapl, tsla = make_ann("AAPL", 1), make_ann("TSLA", 24)
    msft = make_ann("MSFT", 1)
    googl = make_ann("GOOGL", 1)
    nvda = make_ann("NVDA", 1)
    pairs = [
        (make_cls(aapl, "material", 0.9), aapl),
        (make_cls(tsla, "material", 0.9), tsla),                       # older → lower score
        (make_cls(msft, "immaterial", 0.9), msft),                    # immaterial+clean → excluded
        (make_cls(googl, "insufficient_info", 0.5), googl),           # abstain → needs a look
        (make_cls(nvda, "material", 0.9, flags=["G2_ungrounded_quote"]), nvda),  # flagged → needs a look
    ]
    ranked, needs_look = rank(pairs, CONFIG, now=NOW)
    ranked_tickers = [it.announcement.ticker for it in ranked]
    check.equal(ranked_tickers, ["AAPL", "TSLA"], "ranked list = material & clean, recency orders AAPL over TSLA")
    check.require("MSFT" not in ranked_tickers, "immaterial+clean record is excluded from the ranked list")
    look_tickers = {it.announcement.ticker for it in needs_look}
    check.equal(look_tickers, {"GOOGL", "NVDA"}, "abstention and guardrail-flagged records go to Needs a look")
    check.require(ranked[0].score > ranked[1].score, "score decreases with age (recency decay)")
    check.require(ranked[0].reason.count("=") >= 1 and "score" in ranked[0].reason.lower(),
                  "each ranked item carries a one-sentence 'why' reason")

    # --- brief: three sections + self-reporting footer ---
    tmp = Path(tempfile.mkdtemp(prefix="brief_"))
    stats = {"processed": 5, "new": 4, "deduped": 1, "model_primary": "haiku", "model_escalation": "opus",
             "prompt_version": "v1", "escalation_count": 2, "guardrail_flag_counts": {"G2_ungrounded_quote": 1},
             "total_cost_nzd": 0.1234, "runtime_seconds": 3.4}
    path = render_brief(ranked, needs_look, stats, brief_date=NOW.date(), out_dir=tmp)
    text = path.read_text()
    check.require(path.name == "2026-07-14.md", "brief is written to a dated file")
    check.require("## Material — ranked" in text and "## Needs a look" in text and "## Run footer" in text,
                  "brief has all three sections")
    check.require("> body" in text, "material entry shows the verbatim evidence_quote")
    check.require("G2_ungrounded_quote" in text, "Needs-a-look names the guardrail flag")
    check.require("NZ$0.1234" in text and "processed: 5" in text, "footer reports cost and counts (system reports on itself)")

    # --- run orchestrator: idempotency, dead-letter, retries, dry-run, watermark ---
    class StubClient:
        def __init__(self, mapping):
            self.mapping = mapping
            self.messages = SimpleNamespace(create=self._create)

        def _create(self, *, model, max_tokens, temperature, system, messages):
            import re
            ticker = re.search(r"Ticker: (\w+)", messages[0]["content"]).group(1)
            text = self.mapping[ticker]
            return SimpleNamespace(content=[SimpleNamespace(text=text)],
                                   usage=SimpleNamespace(input_tokens=500, output_tokens=50))

    def good(mat="material"):
        return json.dumps({"materiality": mat, "confidence": 0.9, "categories": ["guidance_change"],
                           "evidence_quote": "grounded quote", "rationale": "r",
                           "entities": {"amounts": [], "counterparties": [], "effective_dates": []},
                           "previously_disclosed": False, "needs_human_review": False})

    recs = [make_ann("AAPL", 1, body="grounded quote here"),
            make_ann("MSFT", 2, body="grounded quote here"),
            make_ann("JPM", 3, body="grounded quote here")]  # JPM → always bad JSON → dead-letter
    client = StubClient({"AAPL": good("material"), "MSFT": good("immaterial"), "JPM": "not json"})

    slept: list[float] = []
    db = Path(tempfile.mkdtemp(prefix="run_")) / "state.db"
    store = Store(db)
    briefs_dir = Path(tempfile.mkdtemp(prefix="briefs_"))
    import src.brief as B
    orig = B.BRIEFS_DIR
    B.BRIEFS_DIR = briefs_dir  # redirect the default brief location for the check
    try:
        res = RUN.run_pipeline(recs, CONFIG, client, store, prompt_version="v1", now=NOW, sleeper=slept.append)
        check.equal(res["stats"]["new"], 2, "two good records classified (AAPL, MSFT)")
        check.equal(res["stats"]["dead_letters"], 1, "the bad-JSON record (JPM) was dead-lettered, run continued")
        check.require(res["brief_path"] is not None and res["brief_path"].exists(), "a dated brief was written")
        check.require(2 in slept and 8 in slept, "retries used 2s then 8s backoff (SPEC §12)")
        check.require(store.is_audited(recs[0].announcement_id), "classified records are audited")
        check.require(not store.is_audited(recs[2].announcement_id), "the dead-lettered record is NOT audited")
        check.require(store.get_watermark("EDGAR") is not None, "watermark advanced after a successful full run")

        # idempotency: a second run skips already-audited records
        res2 = RUN.run_pipeline(recs, CONFIG, client, store, prompt_version="v1", now=NOW, sleeper=slept.append)
        check.equal(res2["stats"]["new"], 0, "re-run classifies nothing new (idempotent)")
        check.require(res2["stats"]["deduped"] >= 2, "re-run skips the already-audited records")

        # dry-run: no brief, no watermark advance
        db2 = Path(tempfile.mkdtemp(prefix="run2_")) / "state.db"
        store2 = Store(db2)
        res3 = RUN.run_pipeline(recs[:2], CONFIG, client, store2, prompt_version="v1", dry_run=True,
                                now=NOW, sleeper=slept.append)
        check.require(res3["brief_path"] is None, "--dry-run writes no brief")
        check.require(store2.get_watermark("EDGAR") is None, "--dry-run does not advance the watermark")
        store2.close()
    finally:
        B.BRIEFS_DIR = orig
        store.close()

    check.note("offline check — no API calls, no spend")


if __name__ == "__main__":
    run("C1 rank + brief + run CLI", body)
