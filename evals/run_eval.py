"""run_eval.py — the evaluation harness (SPEC §13.2). Increment 6.

Loads the gold set, runs the FULL agent (classify → verify) on each item `--runs`
times, runs the baselines (§13.4) on the identical set, and writes the reproducible
run directory: scorecard.md/.pdf, per_item.csv, failures.csv, confusion_matrix.csv,
and run_manifest.json. A run that cannot be reproduced is not a result — the
manifest (dataset hash, prompt hash, model ids, temperature, cost) is mandatory.

    python -m evals.run_eval --prompt-version v1 --runs 3
    python -m evals.run_eval --prompt-version v3 --runs 3 --limit 30   # cost-bounded subset

`evaluate()` takes injected gold rows / announcements / client so the check can
exercise the whole pipeline offline with a fake model. No full 60/220-item run is
ever part of a build check (AUTONOMY §6).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from src.classify import classify, load_prompt
from src.fetch import load_config
from src.models import Announcement, Classification
from src.verify import verify
from evals import report
from evals.validate_gold import GOLD_PATH

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "out" / "eval_runs"
LEDGER_PATH = EVAL_DIR / "ledger.json"

CATEGORY_DELIMITER = ";"


def char_band(n: int) -> str:
    if n < 2000:
        return "<2k"
    if n < 20000:
        return "2k-20k"
    if n < 60000:
        return "20k-60k"
    return ">=60k"


def load_gold(path: Path = GOLD_PATH) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_announcements(config: dict | None = None) -> dict[str, Announcement]:
    """announcement_id → canonical Announcement, from the normalised corpus."""
    from src.normalise import normalise_all

    config = config or load_config()
    return {a.announcement_id: a for a in normalise_all(config=config)}


def run_agent(ann: Announcement, config: dict, prompt_version: str, client) -> Classification:
    """The full agent for one item: classify then verify (guardrails)."""
    c = classify(ann, config=config, prompt_version=prompt_version, client=client)
    v = verify(c, ann, config)
    if v is None:  # G4 drop — shouldn't happen for gold (all watchlisted); keep + flag
        c.guardrail_flags = [*c.guardrail_flags, "G4_off_watchlist"]
        return c
    return v


def build_item(run_idx: int, gold_row: dict, ann: Announcement, pred: Classification) -> dict:
    gold_mat = gold_row["label_materiality"].strip()
    gold_cats = [c for c in gold_row["label_categories"].split(CATEGORY_DELIMITER) if c]
    return {
        "run": run_idx,
        "announcement_id": ann.announcement_id,
        "ticker": ann.ticker,
        "slice_tag": gold_row.get("slice_tag", "").strip(),
        "difficulty": gold_row.get("difficulty", "").strip(),
        "doc_type": ann.doc_type,
        "char_band": char_band(ann.char_count),
        "gold_materiality": gold_mat,
        "pred_materiality": pred.materiality,
        "correct": pred.materiality == gold_mat,
        "confidence": pred.confidence,
        "grounded": "G2_ungrounded_quote" not in pred.guardrail_flags,
        "guardrail_flags": pred.guardrail_flags,
        "gold_categories": gold_cats,
        "pred_categories": pred.categories,
        "cost_nzd": pred.cost_nzd or 0.0,
        "latency_ms": pred.latency_ms,
        "escalated": bool(pred.escalated),
        "rationale": pred.rationale,
        "gold_rationale": gold_row.get("label_rationale", ""),
    }


def evaluate(
    prompt_version: str,
    runs: int,
    gold_rows: list[dict],
    announcements: dict[str, Announcement],
    config: dict,
    client,
    predictor: Optional[Callable[[Announcement], Classification]] = None,
) -> list[dict]:
    """Run one system (the agent, or a baseline) over the gold set `runs` times."""
    items: list[dict] = []
    for run_idx in range(1, runs + 1):
        for row in gold_rows:
            ann = announcements[row["announcement_id"]]
            pred = predictor(ann) if predictor else run_agent(ann, config, prompt_version, client)
            items.append(build_item(run_idx, row, ann, pred))
    return items


def _dataset_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_eval(
    prompt_version: str,
    runs: int,
    limit: Optional[int] = None,
    config: dict | None = None,
    client=None,
    baselines: Optional[dict[str, Callable[[Announcement], Classification]]] = None,
    gold_path: Path = GOLD_PATH,
    out_root: Path = EVAL_DIR,
    ledger_path: Path = LEDGER_PATH,
    announcements: Optional[dict[str, Announcement]] = None,
) -> Path:
    """Full harness run for one prompt version. Returns the run directory."""
    config = config or load_config()
    if client is None:
        from anthropic import Anthropic

        client = Anthropic()
    baselines = baselines or {}

    gold_rows = load_gold(gold_path)
    if limit:
        gold_rows = gold_rows[:limit]
    if announcements is None:
        announcements = load_announcements(config)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = out_root / f"{timestamp}_{prompt_version}"
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    items = evaluate(prompt_version, runs, gold_rows, announcements, config, client)
    metrics = report.compute_metrics(items, runs)

    # Baselines on the identical set (§13.4), each measured once. Baseline callables
    # take (ann, config, client); bind them to a 1-arg predictor for evaluate().
    for label, fn in baselines.items():
        predictor = lambda ann, fn=fn: fn(ann, config, client)
        b_items = evaluate(prompt_version, 1, gold_rows, announcements, config, client, predictor=predictor)
        b_metrics = report.compute_metrics(b_items, 1)
        report.update_ledger(ledger_path, f"baseline: {label}",
                             b_metrics["headline"], b_metrics["stability"],
                             {"n": b_metrics["n_items"], "runs": 1})

    detail = {"label": prompt_version, **metrics}
    ledger = report.update_ledger(ledger_path, prompt_version, metrics["headline"], metrics["stability"],
                                  {"n": metrics["n_items"], "runs": runs})

    # Artefacts (SPEC §13.2).
    report.write_per_item_csv(items, out_dir / "per_item.csv")
    report.write_failures_csv(items, out_dir / "failures.csv")
    report.write_confusion_csv(metrics["confusion"], out_dir / "confusion_matrix.csv")
    report.render_scorecard_md(ledger, detail, out_dir / "scorecard.md")
    report.render_scorecard_pdf(ledger, out_dir / "scorecard.pdf")
    report.write_manifest(
        {
            "prompt_version": prompt_version,
            "prompt_file_sha256": hashlib.sha256(load_prompt(prompt_version).encode()).hexdigest(),
            "dataset": (str(gold_path.relative_to(ROOT)) if gold_path.is_relative_to(ROOT) else str(gold_path)),
            "dataset_sha256": _dataset_hash(gold_path),
            "n_items": metrics["n_items"],
            "runs": runs,
            "model_ids": {"primary": config["models"]["primary"], "escalation": config["models"]["escalation"]},
            "temperature": config["models"]["temperature"],
            "escalate_below_confidence": config["thresholds"]["escalate_below_confidence"],
            "escalate_above_chars": config["thresholds"]["escalate_above_chars"],
            "total_cost_nzd": metrics["cost_latency"]["total_cost_nzd"],
            "timestamp": timestamp,
            "wall_seconds": round(time.monotonic() - started, 1),
            "baselines": list(baselines),
        },
        out_dir / "run_manifest.json",
    )
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prompt-version", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None, help="evaluate only the first N gold rows (cost control)")
    parser.add_argument("--no-baselines", action="store_true")
    args = parser.parse_args()

    baselines = {}
    if not args.no_baselines:
        try:
            from evals.baselines import BASELINES

            baselines = BASELINES
        except Exception as exc:  # baselines land in B4
            print(f"(baselines not available yet: {exc})")

    out_dir = run_eval(args.prompt_version, args.runs, limit=args.limit, baselines=baselines)
    print(f"\nWrote {out_dir.relative_to(ROOT)}")
    print((out_dir / "scorecard.md").read_text())


if __name__ == "__main__":
    main()
