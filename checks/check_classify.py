"""check_classify.py — B1: bounded LLM classification (SPEC §7, §8).

Offline. A fake client stands in for the anthropic SDK, so this check makes NO
network call and costs nothing — it exercises prompt structure, the escalation
decision, schema parsing, metadata/cost population, and loud failure on bad JSON.
The real ≤5-record smoke against the API is run separately (AUTONOMY §6).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from checks._harness import run
from src import classify as C
from src.models import Announcement, Classification

ROOT = Path(__file__).resolve().parent.parent
CONFIG = C.load_config()

VALID_JSON = json.dumps(
    {
        "materiality": "material",
        "confidence": 0.91,
        "categories": ["guidance_change"],
        "evidence_quote": "raises full-year revenue guidance to $4.2 billion",
        "rationale": "FY guidance raised ~10%, plainly price-moving",
        "entities": {"amounts": ["$4.2 billion"], "counterparties": [], "effective_dates": []},
        "previously_disclosed": False,
        "needs_human_review": False,
    }
)


class FakeClient:
    """Mimics anthropic.Anthropic(): .messages.create(...) -> response.

    `scripts` is a list of (text, input_tokens, output_tokens) returned in order;
    the last is repeated once exhausted. Records every call for assertions.
    """

    def __init__(self, scripts):
        self._scripts = list(scripts)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, *, model, max_tokens, temperature, system, messages):
        self.calls.append(SimpleNamespace(model=model, system=system, messages=messages,
                                          temperature=temperature, max_tokens=max_tokens))
        text, in_tok, out_tok = self._scripts[min(len(self.calls) - 1, len(self._scripts) - 1)]
        return SimpleNamespace(
            content=[SimpleNamespace(text=text)],
            usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
        )


def make_announcement(char_count: int = 1000, body: str = "body text") -> Announcement:
    now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    return Announcement(
        announcement_id="a" * 64,
        exchange="EDGAR",
        ticker="AAPL",
        company_name="Apple Inc.",
        published_at=now,
        headline="Apple raises full-year guidance",
        doc_type="guidance_change",
        native_doc_type="8-K",
        native_id="0000320193-26-000010",
        issuer_price_sensitive_flag=None,
        body_text=body,
        char_count=char_count,
        truncated=False,
        source_url="https://www.sec.gov/x",
        fetched_at=now,
    )


def body(check):
    # --- prompt v1 structure: Role + schema, naive baseline (no rubric, no few-shots) ---
    v1 = (ROOT / "prompts" / "classify_v1.md").read_text(encoding="utf-8")
    check.require((ROOT / "prompts" / "classify_v1.md").exists(), "prompts/classify_v1.md exists")
    check.require("# Role" in v1, "v1 has a Role section")
    check.require("Return only JSON" in v1, "v1 states the JSON-only output rule")
    check.require('"materiality"' in v1 and '"evidence_quote"' in v1, "v1 carries the output schema")
    check.require(
        "reasonable analyst covering this stock" not in v1,
        "v1 does NOT contain the materiality rubric (that is v2) — v1 is the naive baseline",
    )
    check.require(
        "Few-shot" not in v1 and "Example" not in v1,
        "v1 has no few-shot examples (those are v3)",
    )

    thresholds = CONFIG["thresholds"]
    floor = thresholds["escalate_below_confidence"]
    chars = thresholds["escalate_above_chars"]

    # --- escalation decision is a pure function of (confidence, char_count) ---
    check.equal(C._should_escalate(0.95, 100, thresholds), False, "high confidence + short doc → no escalation")
    check.equal(C._should_escalate(floor - 0.01, 100, thresholds), True, "confidence below floor → escalate")
    check.equal(C._should_escalate(floor, 100, thresholds), False, "confidence exactly at floor → no escalation")
    check.equal(C._should_escalate(0.95, chars + 1, thresholds), True, "doc over char threshold → escalate")
    check.equal(C._should_escalate(0.95, chars, thresholds), False, "doc exactly at char threshold → no escalation")

    # --- classify() with a confident, short result: no escalation, metadata populated ---
    ann = make_announcement(char_count=1000)
    client = FakeClient([(VALID_JSON, 5000, 200)])
    result = classify_result = C.classify(ann, config=CONFIG, prompt_version="v1", client=client)
    check.require(isinstance(result, Classification), "classify() returns a Classification")
    check.equal(result.announcement_id, ann.announcement_id, "announcement_id is set by classify(), not the model")
    check.equal(result.materiality, "material", "materiality parsed from the model JSON")
    check.equal(result.categories, ["guidance_change"], "categories parsed from the model JSON")
    check.equal(result.model_id, CONFIG["models"]["primary"], "model_id records the primary model")
    check.equal(result.prompt_version, "v1", "prompt_version recorded")
    check.equal(result.escalated, False, "confident short doc did not escalate")
    check.equal(result.input_tokens, 5000, "input_tokens carried from usage")
    check.equal(result.output_tokens, 200, "output_tokens carried from usage")

    # --- cost is tokens × pricing × fx, in NZD ---
    p = CONFIG["pricing_usd_per_mtok"]
    fx = CONFIG["fx_usd_nzd"]
    expected = (5000 / 1e6 * p["primary_input"] + 200 / 1e6 * p["primary_output"]) * fx
    check.require(abs(result.cost_nzd - expected) < 1e-9, f"cost_nzd = {expected:.6f} NZD (tokens×pricing×fx)")

    # --- temperature 0 and the prompt reached the model ---
    check.equal(client.calls[0].temperature, CONFIG["models"]["temperature"], "temperature passed through to the model")
    check.require("# Role" in client.calls[0].system, "the prompt file is the system message")

    # --- escalation path: weak primary → escalate to the escalation model, cost accrues ---
    weak = json.dumps({**json.loads(VALID_JSON), "confidence": 0.30, "materiality": "insufficient_info"})
    strong = json.dumps({**json.loads(VALID_JSON), "confidence": 0.80, "materiality": "material"})
    esc_client = FakeClient([(weak, 6000, 150), (strong, 4000, 120)])
    esc = C.classify(make_announcement(char_count=1000), config=CONFIG, prompt_version="v1", client=esc_client)
    check.equal(esc.escalated, True, "weak primary confidence triggered escalation")
    check.equal(esc.model_id, CONFIG["models"]["escalation"], "escalated result records the escalation model")
    check.require(len(esc_client.calls) >= 2, "escalation made at least one extra model call")
    check.require(esc_client.calls[1].model == CONFIG["models"]["escalation"], "escalation call used the escalation model")
    check.require(esc.input_tokens >= 6000, "escalation cost accrues on top of the primary call")
    check.equal(esc.materiality, "material", "aggregation: max materiality wins across chunks")

    # --- real models overshoot the 200-char limit; classify clamps, does not crash ---
    long_json = json.dumps({**json.loads(VALID_JSON),
                            "evidence_quote": "x" * 400, "rationale": "y" * 350})
    clamp_client = FakeClient([(long_json, 1000, 100)])
    clamped = C.classify(make_announcement(), config=CONFIG, prompt_version="v1", client=clamp_client)
    check.equal(len(clamped.evidence_quote), 200, "an over-long evidence_quote is clamped to 200 chars")
    check.equal(len(clamped.rationale), 200, "an over-long rationale is clamped to 200 chars")

    # --- bounded: malformed JSON fails loudly, it does not return garbage ---
    bad_client = FakeClient([("this is not json at all", 100, 10)])
    check.raises(
        Exception,
        lambda: C.classify(make_announcement(), config=CONFIG, prompt_version="v1", client=bad_client),
        "unparseable model output raises rather than returning a bad Classification",
    )

    check.note("offline check — no API calls, no spend")


if __name__ == "__main__":
    run("B1 classify + prompt v1", body)
