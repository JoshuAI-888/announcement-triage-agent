"""check_providers.py — provider abstraction + eval concurrency.

Offline, no network, no spend. Verifies the OpenAI-compatible client adapter
(usage-field normalisation + the max_tokens/temperature param fallback), the
provider_config resolver, and that concurrent evaluate() gives byte-identical
results to serial (order + values preserved).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace

from checks._harness import run
from src import providers as P
from src.fetch import load_config
from src.models import Announcement
from evals import run_eval as R

CONFIG = load_config()


def _fake_openai(create_fn):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_fn)))


def make_ann(ticker, mat_hint):
    now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    return Announcement(
        announcement_id=(ticker.lower() + "0" * 64)[:64], exchange="EDGAR", ticker=ticker,
        company_name=f"{ticker} Inc.", published_at=now, headline=f"{ticker} h", doc_type="guidance_change",
        native_doc_type="8-K", native_id=f"a-{ticker}", issuer_price_sensitive_flag=None,
        body_text=f"{ticker} grounded quote text", char_count=40, truncated=False,
        source_url="https://sec.gov/x", fetched_at=now,
    )


def body(check):
    # --- OpenAI-compat adapter: normalises usage + returns .content[0].text ---
    os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
    client = P._OpenAICompatClient("OPENAI_API_KEY")

    def ok_create(**kwargs):
        # standard call path uses max_tokens
        assert "max_tokens" in kwargs, "first attempt should use max_tokens"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"materiality":"material"}'))],
            usage=SimpleNamespace(prompt_tokens=321, completion_tokens=44),
        )

    client._client = _fake_openai(ok_create)
    resp = client.messages.create(model="m", max_tokens=100, temperature=0.0, system="sys",
                                  messages=[{"role": "user", "content": "u"}])
    check.equal(resp.content[0].text, '{"materiality":"material"}', "adapter returns text at .content[0].text")
    check.equal(resp.usage.input_tokens, 321, "adapter maps prompt_tokens → input_tokens")
    check.equal(resp.usage.output_tokens, 44, "adapter maps completion_tokens → output_tokens")

    # --- param fallback: a model that rejects max_tokens/temperature still works ---
    calls = {"n": 0}

    def picky_create(**kwargs):
        calls["n"] += 1
        if "max_tokens" in kwargs:
            raise RuntimeError("Unsupported parameter: 'max_tokens' is not supported; use 'max_completion_tokens'")
        if "temperature" in kwargs:
            raise RuntimeError("Unsupported value: 'temperature' does not support 0.0")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    client._client = _fake_openai(picky_create)
    resp2 = client.messages.create(model="m", max_tokens=100, temperature=0.0, system="s",
                                   messages=[{"role": "user", "content": "u"}])
    check.require(resp2.content[0].text == "{}" and calls["n"] == 3, "adapter falls back through max_completion_tokens + no-temperature")

    # --- provider_config resolves claude from the top-level blocks + providers: ---
    pc = P.provider_config("claude", CONFIG)
    check.equal(pc["model"], CONFIG["models"]["primary"], "claude provider resolves to the primary model")
    check.require("pricing" in pc and "input" in pc["pricing"], "claude provider carries input/output pricing")
    check.raises(ValueError, lambda: P.provider_config("bogus", CONFIG), "an unknown provider raises")

    # --- concurrency: concurrent evaluate == serial evaluate (order + values) ---
    tickers = ["AAPL", "MSFT", "AMZN", "GOOGL", "NVDA"]
    anns = {t: make_ann(t, "material") for t in tickers}
    announcements = {a.announcement_id: a for a in anns.values()}
    rows = [{"announcement_id": anns[t].announcement_id, "label_materiality": "material",
             "label_categories": "guidance_change", "slice_tag": "clear_material",
             "difficulty": "easy", "label_rationale": "o"} for t in tickers]

    class StubClient:
        def __init__(self):
            self.messages = SimpleNamespace(create=self._c)

        def _c(self, *, model, max_tokens, temperature, system, messages):
            import re
            tk = re.search(r"Ticker: (\w+)", messages[0]["content"]).group(1)
            payload = json.dumps({"materiality": "material", "confidence": 0.9, "categories": ["guidance_change"],
                                  "evidence_quote": f"{tk} grounded quote text", "rationale": "r",
                                  "entities": {"amounts": [], "counterparties": [], "effective_dates": []},
                                  "previously_disclosed": False, "needs_human_review": False})
            return SimpleNamespace(content=[SimpleNamespace(text=payload)],
                                   usage=SimpleNamespace(input_tokens=100, output_tokens=10))

    serial = R.evaluate("v1", 2, rows, announcements, CONFIG, StubClient(), concurrency=1)
    parallel = R.evaluate("v1", 2, rows, announcements, CONFIG, StubClient(), concurrency=4)
    check.equal(len(serial), 10, "evaluate yields n×runs items")
    check.equal([it["announcement_id"] for it in serial], [it["announcement_id"] for it in parallel],
                "concurrent evaluate preserves item order exactly")
    check.equal([it["pred_materiality"] for it in serial], [it["pred_materiality"] for it in parallel],
                "concurrent evaluate produces identical predictions")

    check.note("offline check — no API calls, no spend")


if __name__ == "__main__":
    run("perf: provider abstraction + eval concurrency", body)
