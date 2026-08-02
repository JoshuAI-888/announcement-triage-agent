"""check_prompt_v3.py — C3: prompt v3 + few-shot contamination guard (SPEC §8).

Offline. v3 = v2 (rubric) + the forced-verbatim-quote hard rule + the explicit
abstention rule + exactly 3 few-shot examples, one an abstention. The critical
guard: every few-shot announcement MUST be drawn from OUTSIDE gold.csv — a
few-shot that appears in the eval set contaminates the result and invalidates it.
"""

from __future__ import annotations

import csv
from pathlib import Path

from checks._harness import run

ROOT = Path(__file__).resolve().parent.parent

# The three few-shot source announcements embedded in prompts/classify_v3.md, by
# announcement_id. Drawn from the raw EDGAR corpus OUTSIDE the 220-row gold pool
# (they are structured-note / 8-K filings not selected into candidates.csv):
#   IONS 8-K  — Phase 3 trial miss           (material example)
#   BAC 424B2 — $250k structured note         (immaterial example)
#   FANG 8-K  — credit-agreement amendment    (abstention example)
FEWSHOT_IDS = {
    "IONS-material": "ce5e4206c1ffdbd785c1de89f43d56034ca7d2db177aac6e910fafc49c1491a6",
    "BAC-immaterial": "4721255bd8494643da2971c887ef001abd89bb364c923aac1986c891fdafbabc",
    "FANG-abstain": "d3dd6160688caff3d6f332bdba95f5e7b07d8c4612b6a18007bc8e9efcd68077",
}


def body(check):
    v2 = (ROOT / "prompts" / "classify_v2.md").read_text(encoding="utf-8")
    v3 = (ROOT / "prompts" / "classify_v3.md").read_text(encoding="utf-8")
    rubric = (ROOT / "data" / "gold" / "RUBRIC.md").read_text(encoding="utf-8")

    check.require((ROOT / "prompts" / "classify_v3.md").exists(), "prompts/classify_v3.md exists")

    # v3 keeps the v2 rubric verbatim.
    block = rubric[rubric.index("## 1. Purpose"):rubric.index("## 7. Version")].rstrip()
    check.require(block in v3, "v3 still carries the RUBRIC §§1–6 block verbatim (inherited from v2)")

    # v3 adds the two hard rules v3 is defined by (SPEC §8).
    check.require("character-for-character" in v3, "v3 has the forced-verbatim-quote hard rule")
    check.require("Abstention is a correct answer" in v3, "v3 has the explicit abstention rule")

    # Exactly 3 few-shots, one of them an abstention.
    check.equal(v3.count("\nOutput:\n"), 3, "v3 has exactly 3 few-shot examples (SPEC §8)")
    check.equal(v3.count('"materiality": "insufficient_info"'), 1, "exactly one few-shot is an abstention")
    check.require('"materiality": "material"' in v3 and '"materiality": "immaterial"' in v3,
                  "the other two few-shots cover material and immaterial")

    # --- CONTAMINATION GUARD: no few-shot announcement appears in gold.csv ---
    gold_ids = {r["announcement_id"] for r in csv.DictReader((ROOT / "data" / "gold" / "gold.csv").open())}
    check.note(f"gold.csv holds {len(gold_ids)} announcement_ids")
    for name, aid in FEWSHOT_IDS.items():
        check.require(aid not in gold_ids, f"few-shot {name} ({aid[:12]}…) is NOT in gold.csv")
    check.require(len(set(FEWSHOT_IDS.values())) == 3, "the three few-shots are distinct announcements")

    # v3 is strictly more than v2.
    check.require(len(v3) > len(v2) and "# Role" in v3 and "Return only JSON" in v3, "v3 extends v2 and keeps Role + schema")

    check.note("offline check — no API calls, no spend")


if __name__ == "__main__":
    run("C3 prompt v3 + few-shot contamination guard", body)
