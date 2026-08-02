"""classify.py — bounded LLM classification step (SPEC.md §7, §8). Increment 4.

One canonical Announcement in, one Classification out. The primary model does the
bulk work; the escalation branch (SPEC §7) is the only place the system decides
about its own process — it fires when the primary is unsure or the document is
long, chunks the body, re-classifies on the escalation model, and aggregates
(max materiality wins, min confidence carried). Every call's tokens, cost (NZD)
and escalation reason are recorded on the Classification for the brief footer and
the eval manifest.

The anthropic client is injectable so the check can run offline with a fake.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from src.fetch import ROOT, load_config  # noqa: F401  (load_config re-exported)
from src.models import Announcement, Classification

load_dotenv(ROOT / ".env")  # make ANTHROPIC_API_KEY available to the anthropic SDK

PROMPTS_DIR = ROOT / "prompts"

# "max materiality wins" during escalation aggregation: material outranks an
# abstention, which outranks immaterial.
MATERIALITY_RANK = {"immaterial": 0, "insufficient_info": 1, "material": 2}

# The fields the model is expected to return (SPEC §5.2). announcement_id is set
# by us, never trusted from the model.
MODEL_FIELDS = [
    "materiality",
    "confidence",
    "categories",
    "evidence_quote",
    "rationale",
    "entities",
    "previously_disclosed",
    "needs_human_review",
]


class ClassifyError(RuntimeError):
    """The model produced output that could not be parsed into a Classification."""


def load_prompt(prompt_version: str) -> str:
    path = PROMPTS_DIR / f"classify_{prompt_version}.md"
    if not path.exists():
        raise FileNotFoundError(f"no prompt file for version {prompt_version!r} at {path}")
    return path.read_text(encoding="utf-8")


def _should_escalate(confidence: float, char_count: int, thresholds: dict) -> bool:
    """SPEC §7: escalate if the primary is unsure OR the document is long."""
    return confidence < thresholds["escalate_below_confidence"] or char_count > thresholds["escalate_above_chars"]


def _render_user(ann: Announcement, body_text: Optional[str] = None) -> str:
    """The announcement as a plain user message. body_text overridable for chunking."""
    body = ann.body_text if body_text is None else body_text
    return (
        f"Ticker: {ann.ticker}\n"
        f"Headline: {ann.headline}\n"
        f"Native form type: {ann.native_doc_type}\n"
        f"Published: {ann.published_at.isoformat()}\n"
        f"\n--- Announcement text ---\n{body}\n"
    )


def _default_client():
    from anthropic import Anthropic

    return Anthropic()


def _call(client, model: str, system: str, user: str, max_tokens: int, temperature: float):
    """One model call. Returns (text, input_tokens, output_tokens)."""
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text, resp.usage.input_tokens, resp.usage.output_tokens


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_classification(text: str, ann: Announcement) -> dict:
    """Extract the JSON object and reduce it to the model-returned fields.

    Raises ClassifyError on anything that is not a JSON object carrying every
    required field — the caller retries once, then dead-letters.
    """
    match = _JSON_RE.search(text)
    if not match:
        raise ClassifyError("no JSON object found in model output")
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ClassifyError(f"model output is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ClassifyError("model output JSON is not an object")
    try:
        data = {key: raw[key] for key in MODEL_FIELDS}
    except KeyError as exc:
        raise ClassifyError(f"model output missing required field {exc}") from exc
    data["announcement_id"] = ann.announcement_id  # authoritative, never from the model
    return data


def _cost_nzd(input_tokens: int, output_tokens: int, price_in: float, price_out: float, fx: float) -> float:
    return (input_tokens / 1e6 * price_in + output_tokens / 1e6 * price_out) * fx


def _classify_once(client, model, system, user, max_tokens, temperature, ann) -> tuple[dict, int, int]:
    """One model call + parse, with a single retry on malformed output (G1 spirit)."""
    last: Optional[ClassifyError] = None
    for _ in range(2):
        text, in_tok, out_tok = _call(client, model, system, user, max_tokens, temperature)
        try:
            return _parse_classification(text, ann), in_tok, out_tok
        except ClassifyError as exc:
            last = exc
    raise last  # type: ignore[misc]


def _escalate(ann, system, config, client) -> tuple[dict, int, int]:
    """Chunk the body, classify each chunk on the escalation model, aggregate."""
    models = config["models"]
    thresholds = config["thresholds"]
    chunk_size = thresholds["escalate_above_chars"]
    body = ann.body_text
    chunks = [body[i : i + chunk_size] for i in range(0, len(body), chunk_size)] or [""]

    results: list[dict] = []
    total_in = total_out = 0
    for chunk in chunks:
        data, in_tok, out_tok = _classify_once(
            client, models["escalation"], system, _render_user(ann, chunk),
            models["max_output_tokens"], models["temperature"], ann,
        )
        results.append(data)
        total_in += in_tok
        total_out += out_tok

    winner = max(results, key=lambda d: MATERIALITY_RANK[d["materiality"]])
    winner = dict(winner)
    winner["confidence"] = min(d["confidence"] for d in results)  # min confidence carried
    return winner, total_in, total_out


def classify(
    ann: Announcement,
    config: dict | None = None,
    prompt_version: str | None = None,
    client=None,
) -> Classification:
    """Classify one Announcement. See module docstring for the escalation branch."""
    config = config or load_config()
    prompt_version = prompt_version or config.get("prompt_version", "v1")
    client = client or _default_client()
    models = config["models"]
    pricing = config["pricing_usd_per_mtok"]
    fx = config["fx_usd_nzd"]
    system = load_prompt(prompt_version)

    t0 = time.monotonic()

    data, in_tok, out_tok = _classify_once(
        client, models["primary"], system, _render_user(ann),
        models["max_output_tokens"], models["temperature"], ann,
    )
    total_in, total_out = in_tok, out_tok
    total_cost = _cost_nzd(in_tok, out_tok, pricing["primary_input"], pricing["primary_output"], fx)
    model_id = models["primary"]
    escalated = False

    thresholds = config["thresholds"]
    if _should_escalate(data["confidence"], ann.char_count, thresholds) \
            and models["escalation"] != models["primary"]:
        reason = ("low confidence" if data["confidence"] < thresholds["escalate_below_confidence"]
                  else "long document")
        print(f"ESCALATE {ann.announcement_id[:12]} {ann.ticker} {ann.native_doc_type}: {reason}")
        data, e_in, e_out = _escalate(ann, system, config, client)
        total_in += e_in
        total_out += e_out
        total_cost += _cost_nzd(e_in, e_out, pricing["escalation_input"], pricing["escalation_output"], fx)
        model_id = models["escalation"]
        escalated = True

    return Classification(
        **data,
        model_id=model_id,
        prompt_version=prompt_version,
        input_tokens=total_in,
        output_tokens=total_out,
        cost_nzd=total_cost,
        latency_ms=int((time.monotonic() - t0) * 1000),
        escalated=escalated,
    )


def main() -> None:  # pragma: no cover — manual smoke entry point
    from src.normalise import normalise_all

    records = normalise_all(limit=5)[:5]
    for ann in records:
        c = classify(ann, prompt_version="v1")
        print(f"{ann.ticker:6} {ann.native_doc_type:10} {c.materiality:18} conf={c.confidence:.2f} "
              f"NZ${c.cost_nzd:.4f} {'ESC' if c.escalated else ''}")


if __name__ == "__main__":
    main()
