"""check_eval.py — B3: eval harness + manifest + scorecard (SPEC §13.2, §13.3, §13.5).

Offline. A fake client and a synthetic 4-item gold set drive the WHOLE harness
(classify → verify → metrics → six artefacts) with no network and no spend. It
asserts metric arithmetic on a controlled set and that every required output file
is written with a reproducible manifest. The real full run is separate (AUTONOMY §6).
"""

from __future__ import annotations

import csv
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from checks._harness import run
from evals import run_eval as R
from evals.report import compute_metrics
from src.fetch import load_config
from src.models import Announcement

CONFIG = load_config()

# ticker → (materiality, confidence, evidence_quote, categories). All tickers are on
# the real watchlist so G4 does not drop them; all confidences ≥ floor and bodies are
# short, so nothing escalates — one primary call per item.
RESPONSES = {
    "AAPL": ("material", 0.90, "raised full-year guidance to $4.2 billion", ["guidance_change"]),
    "MSFT": ("immaterial", 0.90, "routine filing of an employee benefit plan report", ["admin"]),
    "AMZN": ("immaterial", 0.90, "notes a change in a supplier relationship", ["operational_incident"]),
    "GOOGL": ("insufficient_info", 0.70, "a lawsuit was filed; no damages are stated", ["regulatory"]),
}
# gold truth (may disagree with the fake prediction — AMZN is a deliberate miss).
GOLD = {
    "AAPL": ("material", "clear_material", "guidance_change"),
    "MSFT": ("immaterial", "clear_immaterial", "admin"),
    "AMZN": ("material", "hard_positive", "operational_incident"),   # model says immaterial → confident miss
    "GOOGL": ("insufficient_info", "ambiguous", "regulatory"),
}


class FakeClient:
    def __init__(self):
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, *, model, max_tokens, temperature, system, messages):
        content = messages[0]["content"]
        ticker = re.search(r"Ticker: (\w+)", content).group(1)
        mat, conf, quote, cats = RESPONSES[ticker]
        payload = json.dumps({
            "materiality": mat, "confidence": conf, "categories": cats,
            "evidence_quote": quote, "rationale": f"{ticker} rationale",
            "entities": {"amounts": [], "counterparties": [], "effective_dates": []},
            "previously_disclosed": False, "needs_human_review": False,
        })
        return SimpleNamespace(content=[SimpleNamespace(text=payload)],
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=100))


def make_announcement(ticker: str) -> Announcement:
    now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    quote = RESPONSES[ticker][2]
    body = f"{ticker} announcement. {quote}. Additional descriptive text follows here."
    return Announcement(
        announcement_id=(ticker.lower() + "0" * 64)[:64], exchange="EDGAR", ticker=ticker,
        company_name=f"{ticker} Inc.", published_at=now, headline=f"{ticker} update",
        doc_type=GOLD[ticker][2], native_doc_type="8-K", native_id=f"acc-{ticker}",
        issuer_price_sensitive_flag=None, body_text=body, char_count=len(body), truncated=False,
        source_url="https://sec.gov/x", fetched_at=now,
    )


def gold_row(ticker: str, ann: Announcement) -> dict:
    mat, slice_tag, cat = GOLD[ticker]
    return {
        "id": ticker, "announcement_id": ann.announcement_id, "exchange": "EDGAR", "ticker": ticker,
        "published_at": ann.published_at.isoformat(), "doc_type": ann.doc_type,
        "issuer_price_sensitive_flag": "", "label_materiality": mat, "label_categories": cat,
        "label_evidence_span": RESPONSES[ticker][2], "label_rationale": f"owner {ticker}",
        "slice_tag": slice_tag, "difficulty": "medium",
        "labelled_at": "2026-08-02T12:00:00+00:00", "labeller": "jf", "pass_number": "1",
    }


def body(check):
    tickers = list(RESPONSES)
    anns = {t: make_announcement(t) for t in tickers}
    announcements = {a.announcement_id: a for a in anns.values()}
    rows = [gold_row(t, anns[t]) for t in tickers]
    client = FakeClient()

    # --- metric arithmetic on the controlled set, runs=2 ---
    items = R.evaluate("v1", 2, rows, announcements, CONFIG, client)
    check.equal(len(items), 8, "evaluate() yields n×runs items (4×2)")
    m = compute_metrics(items, 2)
    h = m["headline"]
    # material gold = AAPL, AMZN. Pred material = AAPL only. → recall 0.5, precision 1.0
    check.require(abs(h["recall_material"] - 0.5) < 1e-9, "recall(material) = 0.5 (AMZN missed)")
    check.require(abs(h["precision_material"] - 1.0) < 1e-9, "precision(material) = 1.0 (no false positives)")
    check.require(abs(h["grounded_pct"] - 1.0) < 1e-9, "grounded = 1.0 (every quote verbatim → G2 passes)")
    check.require(abs(h["abstention_ambiguous"] - 1.0) < 1e-9, "abstention on ambiguous slice = 1.0 (GOOGL abstains)")
    check.require(abs(h["confidently_wrong"] - 0.25) < 1e-9, "confidently-wrong = 0.25 (AMZN wrong at conf 0.9)")
    check.equal(sum(m["confusion"][g][p] for g in m["confusion"] for p in m["confusion"][g]), 8,
                "confusion matrix sums to all items")
    check.equal(m["n_items"], 4, "n_items is the per-run count")

    # --- full run_eval writes every required artefact with a reproducible manifest ---
    tmp = Path(tempfile.mkdtemp(prefix="eval_check_"))
    gold_csv = tmp / "gold.csv"
    with gold_csv.open("w", newline="", encoding="utf-8") as fh:
        from evals.export_candidates import GOLD_COLUMNS
        w = csv.DictWriter(fh, fieldnames=GOLD_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    out_dir = R.run_eval("v1", 2, config=CONFIG, client=client, baselines={},
                         gold_path=gold_csv, out_root=tmp / "runs", ledger_path=tmp / "runs" / "ledger.json",
                         announcements=announcements)

    for name in ["scorecard.md", "scorecard.pdf", "per_item.csv", "failures.csv",
                 "confusion_matrix.csv", "run_manifest.json"]:
        check.require((out_dir / name).exists(), f"harness wrote {name} (SPEC §13.2)")
    check.require((out_dir / "scorecard.pdf").stat().st_size > 0, "scorecard.pdf is non-empty (matplotlib)")

    manifest = json.loads((out_dir / "run_manifest.json").read_text())
    for key in ["dataset_sha256", "prompt_file_sha256", "model_ids", "temperature", "n_items", "runs", "total_cost_nzd"]:
        check.require(key in manifest, f"manifest carries {key} (reproducibility, §13.2)")
    check.equal(manifest["runs"], 2, "manifest records the run count")
    check.equal(manifest["model_ids"]["primary"], CONFIG["models"]["primary"], "manifest records the primary model id")

    failures = list(csv.DictReader((out_dir / "failures.csv").open()))
    fail_tickers = {f["ticker"] for f in failures}
    check.require("AMZN" in fail_tickers, "failures.csv captures the AMZN disagreement (model vs owner)")
    check.require("AAPL" not in fail_tickers, "failures.csv excludes agreements")

    scorecard = (out_dir / "scorecard.md").read_text()
    check.require("Recall (material)" in scorecard and "| v1 |" in scorecard, "scorecard has the §13.5 table with a v1 row")

    check.note("offline check — no API calls, no spend")


if __name__ == "__main__":
    run("B3 eval harness + manifest + scorecard", body)
