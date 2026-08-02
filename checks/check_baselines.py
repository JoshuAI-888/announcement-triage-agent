"""check_baselines.py — B4: the three baselines (SPEC §13.4).

Offline. flag_all and rules make no model call; naive_prompt is driven through a
fake client. Also confirms the baselines land as their own rows in the scorecard.
"""

from __future__ import annotations

import csv
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from checks._harness import run
from evals import run_eval as R
from evals.baselines import BASELINES, flag_all, rules, naive_prompt
from evals.export_candidates import GOLD_COLUMNS
from src.fetch import load_config
from src.models import Announcement

CONFIG = load_config()


class FakeClient:
    def __init__(self):
        self.calls = 0
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, *, model, max_tokens, temperature, system, messages):
        self.calls += 1
        payload = json.dumps({
            "materiality": "material", "confidence": 0.88, "categories": ["guidance_change"],
            "evidence_quote": "raised guidance", "rationale": "naive says material",
            "entities": {"amounts": [], "counterparties": [], "effective_dates": []},
            "previously_disclosed": False, "needs_human_review": False,
        })
        return SimpleNamespace(content=[SimpleNamespace(text=payload)],
                               usage=SimpleNamespace(input_tokens=900, output_tokens=90))


def make_announcement(ticker: str, doc_type: str, body: str) -> Announcement:
    now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    return Announcement(
        announcement_id=(ticker.lower() + "0" * 64)[:64], exchange="EDGAR", ticker=ticker,
        company_name=f"{ticker} Inc.", published_at=now, headline=f"{ticker} update", doc_type=doc_type,
        native_doc_type="8-K", native_id=f"acc-{ticker}", issuer_price_sensitive_flag=None,
        body_text=body, char_count=len(body), truncated=False, source_url="https://sec.gov/x", fetched_at=now,
    )


def body(check):
    guidance = make_announcement("AAPL", "guidance_change", "The company raised full-year guidance to $4.2bn.")
    admin = make_announcement("MSFT", "admin", "Routine filing of an employee benefit plan report for the period.")

    check.equal(set(BASELINES), {"flag_all", "rules", "naive_prompt"}, "BASELINES registry has the three required baselines")

    # --- flag_all: everything material, no model call ---
    fa = flag_all(guidance, CONFIG, client=None)
    check.equal(fa.materiality, "material", "flag_all calls everything material")
    check.equal(flag_all(admin, CONFIG, client=None).materiality, "material", "flag_all flags even admin as material")
    check.require(fa.evidence_quote in guidance.body_text, "flag_all quote is verbatim from the body (G2-fair)")

    # --- rules: deterministic from doc_type + keywords, no model call ---
    check.equal(rules(guidance, CONFIG, client=None).materiality, "material", "rules → material on a material doc_type")
    check.equal(rules(admin, CONFIG, client=None).materiality, "immaterial", "rules → immaterial on admin with no keyword")
    kw = make_announcement("KO", "admin", "The board declared a special dividend of $1.00 per share.")
    check.equal(rules(kw, CONFIG, client=None).materiality, "material", "rules → material when a keyword ('dividend') fires")

    # --- naive_prompt: the v1 prompt through the real classify path ---
    fake = FakeClient()
    np = naive_prompt(guidance, CONFIG, client=fake)
    check.equal(np.prompt_version, "v1", "naive_prompt uses prompt v1")
    check.equal(np.materiality, "material", "naive_prompt returns the model's parsed call")
    check.require(fake.calls >= 1, "naive_prompt actually invokes the model (unlike flag_all/rules)")

    # --- baselines integrate: they appear as their own scorecard rows ---
    anns = {a.announcement_id: a for a in (guidance, admin)}
    rows = []
    for a, mat, slc in ((guidance, "material", "clear_material"), (admin, "immaterial", "clear_immaterial")):
        rows.append({
            "id": a.ticker, "announcement_id": a.announcement_id, "exchange": "EDGAR", "ticker": a.ticker,
            "published_at": a.published_at.isoformat(), "doc_type": a.doc_type, "issuer_price_sensitive_flag": "",
            "label_materiality": mat, "label_categories": a.doc_type, "label_evidence_span": a.body_text[:20],
            "label_rationale": "owner", "slice_tag": slc, "difficulty": "easy",
            "labelled_at": "2026-08-02T12:00:00+00:00", "labeller": "jf", "pass_number": "1",
        })
    tmp = Path(tempfile.mkdtemp(prefix="baseline_check_"))
    gold_csv = tmp / "gold.csv"
    with gold_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=GOLD_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    out_dir = R.run_eval("v1", 1, config=CONFIG, client=FakeClient(), baselines=BASELINES,
                         gold_path=gold_csv, out_root=tmp / "runs", ledger_path=tmp / "runs" / "ledger.json",
                         announcements=anns)
    scorecard = (out_dir / "scorecard.md").read_text()
    for label in ("baseline: rules", "baseline: flag_all", "baseline: naive_prompt"):
        check.require(label in scorecard, f"scorecard carries the '{label}' row (§13.5)")

    check.note("offline check — no API calls, no spend")


if __name__ == "__main__":
    run("B4 baselines (flag_all, rules, naive_prompt)", body)
