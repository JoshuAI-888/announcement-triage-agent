"""check_batch.py — provider Batch API backends + batch_evaluate (offline).

No network, no spend. SDK-shaped fakes drive AnthropicBatch and OpenAICompatBatch
through submit→poll→retrieve→map, and an injected fake backend drives batch_evaluate
end-to-end (custom_id reconciliation, the 50% discount, sentinel on a failed result).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from checks._harness import run
from evals import batch as B
from evals import run_eval as R
from src.fetch import load_config
from src.models import Announcement

CONFIG = load_config()

VALID = json.dumps({"materiality": "material", "confidence": 0.9, "categories": ["guidance_change"],
                    "evidence_quote": "AAPL grounded quote", "rationale": "r",
                    "entities": {"amounts": [], "counterparties": [], "effective_dates": []},
                    "previously_disclosed": False, "needs_human_review": False})


def make_ann(ticker):
    now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    return Announcement(
        announcement_id=(ticker.lower() + "0" * 64)[:64], exchange="EDGAR", ticker=ticker,
        company_name=f"{ticker} Inc.", published_at=now, headline=f"{ticker} h", doc_type="guidance_change",
        native_doc_type="8-K", native_id=f"a-{ticker}", issuer_price_sensitive_flag=None,
        body_text=f"{ticker} grounded quote text", char_count=40, truncated=False,
        source_url="https://sec.gov/x", fetched_at=now,
    )


def body(check):
    reqs = [{"custom_id": "1:aaa", "model": "m", "system": "s", "user": "u", "max_tokens": 100, "temperature": 0.0},
            {"custom_id": "1:bbb", "model": "m", "system": "s", "user": "u", "max_tokens": 100, "temperature": 0.0}]

    # --- AnthropicBatch: submit → poll → results mapping (one success, one error) ---
    class FakeAnthropic:
        def __init__(self):
            self.messages = SimpleNamespace(batches=SimpleNamespace(
                create=lambda requests: SimpleNamespace(id="batch_a"),
                retrieve=lambda bid: SimpleNamespace(processing_status="ended"),
                results=lambda bid: iter([
                    SimpleNamespace(custom_id="1:aaa", result=SimpleNamespace(
                        type="succeeded",
                        message=SimpleNamespace(content=[SimpleNamespace(text=VALID)],
                                                usage=SimpleNamespace(input_tokens=1000, output_tokens=100)))),
                    SimpleNamespace(custom_id="1:bbb", result=SimpleNamespace(type="errored", error="overloaded")),
                ]),
            ))

    a_out = B.AnthropicBatch(FakeAnthropic()).run(reqs, poll_interval=0)
    check.equal(a_out["1:aaa"].input_tokens, 1000, "AnthropicBatch maps a succeeded result's tokens")
    check.require(a_out["1:aaa"].text == VALID, "AnthropicBatch maps a succeeded result's text")
    check.require(a_out["1:bbb"].error is not None and a_out["1:bbb"].text is None, "AnthropicBatch records an errored result")

    # --- OpenAICompatBatch: JSONL upload → poll → download → parse (one 200, one error) ---
    out_jsonl = "\n".join([
        json.dumps({"custom_id": "1:aaa", "response": {"status_code": 200, "body": {
            "choices": [{"message": {"content": VALID}}], "usage": {"prompt_tokens": 900, "completion_tokens": 80}}}}),
        json.dumps({"custom_id": "1:bbb", "response": {"status_code": 429}, "error": {"message": "rate limited"}}),
    ])

    class FakeOpenAI:
        def __init__(self):
            self.files = SimpleNamespace(
                create=lambda file, purpose: SimpleNamespace(id="file_1"),
                content=lambda fid: SimpleNamespace(read=lambda: out_jsonl.encode("utf-8")))
            self.batches = SimpleNamespace(
                create=lambda input_file_id, endpoint, completion_window: SimpleNamespace(id="batch_o"),
                retrieve=lambda bid: SimpleNamespace(status="completed", output_file_id="file_out"))

    o_out = B.OpenAICompatBatch(FakeOpenAI()).run(reqs, poll_interval=0)
    check.equal(o_out["1:aaa"].input_tokens, 900, "OpenAICompatBatch maps prompt_tokens from the JSONL output")
    check.require(o_out["1:aaa"].text == VALID, "OpenAICompatBatch maps content from the JSONL output")
    check.require(o_out["1:bbb"].error is not None, "OpenAICompatBatch records a non-200 result as an error")

    # --- batch_evaluate end-to-end via an injected fake backend ---
    aapl, msft = make_ann("AAPL"), make_ann("MSFT")
    announcements = {a.announcement_id: a for a in (aapl, msft)}
    rows = [{"announcement_id": aapl.announcement_id, "label_materiality": "material",
             "label_categories": "guidance_change", "slice_tag": "clear_material", "difficulty": "easy",
             "label_rationale": "o"},
            {"announcement_id": msft.announcement_id, "label_materiality": "immaterial",
             "label_categories": "admin", "slice_tag": "clear_immaterial", "difficulty": "easy",
             "label_rationale": "o"}]

    class FakeBackend:
        def run(self, requests, **kw):
            out = {}
            for r in requests:
                if r["custom_id"].endswith(aapl.announcement_id):
                    out[r["custom_id"]] = B.BatchResult(r["custom_id"], VALID, 1000, 100)
                else:  # MSFT → a failed result → must become a sentinel
                    out[r["custom_id"]] = B.BatchResult(r["custom_id"], None, 0, 0, error="boom")
            return out

    items = R.batch_evaluate("v1", 1, rows, announcements, CONFIG, "claude", backend=FakeBackend())
    check.equal(len(items), 2, "batch_evaluate yields one item per gold row")
    by_ticker = {it["ticker"]: it for it in items}
    check.equal(by_ticker["AAPL"]["pred_materiality"], "material", "batch result parsed + reconciled by custom_id")
    check.require("EVAL_CLASSIFY_FAILED" in by_ticker["MSFT"]["guardrail_flags"], "a failed batch result becomes a sentinel")

    # 50% discount applied to the batch cost
    p, fx = CONFIG["pricing_usd_per_mtok"], CONFIG["fx_usd_nzd"]
    expected = (1000 / 1e6 * p["primary_input"] + 100 / 1e6 * p["primary_output"]) * fx * R.BATCH_DISCOUNT
    check.require(abs(by_ticker["AAPL"]["cost_nzd"] - expected) < 1e-9, "batch cost is billed at the 50% discount")

    check.note("offline check — no API calls, no spend")


if __name__ == "__main__":
    run("Batch API backends + batch_evaluate", body)
