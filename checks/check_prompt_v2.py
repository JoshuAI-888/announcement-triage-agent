"""check_prompt_v2.py — C2: prompt v2 = v1 + rubric + category defs (SPEC §8).

Offline. The point of v2 is that the materiality rubric is copied VERBATIM from
data/gold/RUBRIC.md — identical wording is what makes the eval valid (SPEC §8:294).
This check re-extracts §§1–6 from the rubric and asserts the exact block appears in
classify_v2.md, byte-for-byte, guarding against paraphrase drift.
"""

from __future__ import annotations

from pathlib import Path

from checks._harness import run

ROOT = Path(__file__).resolve().parent.parent


def body(check):
    v1 = (ROOT / "prompts" / "classify_v1.md").read_text(encoding="utf-8")
    v2 = (ROOT / "prompts" / "classify_v2.md").read_text(encoding="utf-8")
    rubric = (ROOT / "data" / "gold" / "RUBRIC.md").read_text(encoding="utf-8")

    check.require((ROOT / "prompts" / "classify_v2.md").exists(), "prompts/classify_v2.md exists")

    # The exact §§1–6 block (materiality standard + category definitions).
    block = rubric[rubric.index("## 1. Purpose"):rubric.index("## 7. Version")].rstrip()

    check.require(block in v2, "the RUBRIC §§1–6 block appears VERBATIM in classify_v2.md (no paraphrase)")

    # Spot-check the load-bearing sentences are present exactly (not reworded).
    for phrase in [
        "Would a reasonable analyst covering this stock change what they do before the open",
        "insufficient_info",
        "Structured-note pricing supplements",
        "immaterial by form type",
    ]:
        check.require(phrase in v2, f"v2 carries the exact rubric phrase: {phrase[:48]!r}")

    # All 11 category names must be defined in v2 (they live in RUBRIC §4).
    for cat in ["guidance_change", "earnings_result", "m_and_a", "capital_raise", "director_dealing",
                "contract_award", "operational_incident", "governance_change", "index_change",
                "regulatory", "admin"]:
        check.require(cat in v2, f"v2 defines category {cat}")

    # v2 keeps v1's Role and output schema, and is genuinely more than v1.
    check.require("# Role" in v2 and "Return only JSON" in v2, "v2 retains the Role and JSON-only output rule")
    check.require(v2 != v1 and len(v2) > len(v1), "v2 is v1 plus the rubric (strictly larger)")

    # v2 is still the rubric level, NOT v3: no forced-verbatim hard rule, no few-shots yet.
    check.require("Few-shot" not in v2 and "## Example" not in v2, "v2 has no few-shot examples (those are v3)")

    check.note("offline check — no API calls, no spend")


if __name__ == "__main__":
    run("C2 prompt v2 (verbatim rubric copy)", body)
