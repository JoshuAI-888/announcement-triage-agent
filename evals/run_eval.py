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
from src.verify import verify, _normalise_ws
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


GOLD_CORPUS_PATH = ROOT / "evals" / "gold_corpus.jsonl"


def load_announcements(config: dict | None = None) -> dict[str, Announcement]:
    """announcement_id → canonical Announcement.

    Prefers the committed, self-contained gold corpus (evals/gold_corpus.jsonl): the 220
    gold announcements already normalised + truncated. This lets the eval run on a CI
    runner that has NO data/raw (the daily brief fetches fresh filings; the eval needs the
    exact 220 gold records by id). Falls back to normalising the local data/raw corpus."""
    if GOLD_CORPUS_PATH.exists():
        out: dict[str, Announcement] = {}
        for line in GOLD_CORPUS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            ann = Announcement.model_validate_json(line)
            out[ann.announcement_id] = ann
        return out

    from src.normalise import normalise_all

    config = config or load_config()
    return {a.announcement_id: a for a in normalise_all(config=config)}


def _failed_sentinel(ann: Announcement, config: dict, prompt_version: str) -> Classification:
    """A flagged placeholder so a persistent classify failure is visible, not fatal."""
    from src.models import Entities

    return Classification(
        announcement_id=ann.announcement_id, materiality="insufficient_info", confidence=0.0,
        categories=["admin"], evidence_quote="EVAL_CLASSIFY_FAILED", rationale="eval: classify failed",
        entities=Entities(), previously_disclosed=False, needs_human_review=True,
        model_id=config["models"]["primary"], prompt_version=prompt_version, cost_nzd=0.0,
        guardrail_flags=["EVAL_CLASSIFY_FAILED"],
    )


def resilient(predictor: Callable[[Announcement], Classification], config: dict, prompt_version: str):
    """Wrap ANY predictor (agent or baseline) so a persistent failure yields a sentinel.

    A long eval makes ~1k API calls; one persistent failure (a transient hiccup, or
    an exhausted credit balance) must not crash the whole run — the harness, unlike
    run.py, has no dead-letter path. Applies to baselines too (naive_prompt calls
    the model), which is what crashed the first v3 run.
    """
    def _wrapped(ann: Announcement) -> Classification:
        try:
            return predictor(ann)
        except Exception as exc:
            print(f"EVAL: prediction failed for {ann.ticker} {ann.announcement_id[:10]}: {exc}")
            return _failed_sentinel(ann, config, prompt_version)

    return _wrapped


def run_agent(ann: Announcement, config: dict, prompt_version: str, client) -> Classification:
    """The full agent for one item: classify (with transient-error retries) then verify."""
    import time as _time

    from src.run import _classify_with_retries

    try:
        c = _classify_with_retries(ann, config, client, prompt_version, _time.sleep)
    except Exception as exc:
        print(f"EVAL: classify failed for {ann.ticker} {ann.announcement_id[:10]} after retries: {exc}")
        c = _failed_sentinel(ann, config, prompt_version)
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
        # Grounded% is a MEASUREMENT (the G2 rule applied to the quote), not a flag
        # lookup — so it is computed identically for the agent and every baseline,
        # even baselines that never run verify.
        "grounded": _normalise_ws(pred.evidence_quote) in _normalise_ws(ann.body_text),
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
    concurrency: int = 1,
) -> list[dict]:
    """Run one system (the agent, or a baseline) over the gold set `runs` times.

    The classify calls are I/O-bound; `concurrency` > 1 runs them in a thread pool
    (ThreadPoolExecutor.map preserves order, so item ordering is unchanged). The
    per-item work is pure + the SDK clients are thread-safe, so this is safe.
    """
    tasks = [(run_idx, row) for run_idx in range(1, runs + 1) for row in gold_rows]

    def _work(task):
        run_idx, row = task
        ann = announcements[row["announcement_id"]]
        pred = predictor(ann) if predictor else run_agent(ann, config, prompt_version, client)
        return build_item(run_idx, row, ann, pred)

    if concurrency and concurrency > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            return list(pool.map(_work, tasks))
    return [_work(task) for task in tasks]


BATCH_DISCOUNT = 0.5  # provider Batch APIs bill at ~50% of the live rate


def _batch_pred(res, ann, cfg, prompt_version):
    """Turn one raw batch completion into a verified Classification (or a sentinel)."""
    from src.classify import _cost_nzd, _parse_classification
    from src.models import Classification

    if res is None or res.error or not res.text:
        return _failed_sentinel(ann, cfg, prompt_version)
    try:
        data = _parse_classification(res.text, ann)
        pricing, fx = cfg["pricing_usd_per_mtok"], cfg["fx_usd_nzd"]
        cost = _cost_nzd(res.input_tokens, res.output_tokens,
                         pricing["primary_input"], pricing["primary_output"], fx) * BATCH_DISCOUNT
        c = Classification(**data, model_id=cfg["models"]["primary"], prompt_version=prompt_version,
                           input_tokens=res.input_tokens, output_tokens=res.output_tokens,
                           cost_nzd=cost, escalated=False)
    except Exception:
        return _failed_sentinel(ann, cfg, prompt_version)
    v = verify(c, ann, cfg)
    return v if v is not None else c


def batch_evaluate(prompt_version, runs, gold_rows, announcements, cfg, provider,
                   backend=None, extra_body=None) -> list[dict]:
    """Evaluate one prompt version via the provider Batch API (async, ~50% cheaper).

    Builds one request per (run, item), submits as a single batch, polls to
    completion, then parses + verifies each result exactly as the live path does.
    """
    from src.classify import _render_user, load_prompt
    from evals.batch import build_backend

    system = load_prompt(prompt_version)
    models = cfg["models"]
    # custom_id must be 6–64 chars: Anthropic caps at 64 (a "run:sha256" id is 66),
    # GLM/Zhipu requires a minimum of 6. `req-000000` satisfies both. `plan` maps
    # each id back to its (run, row).
    plan: list[tuple[int, dict]] = []
    requests = []
    for run_idx in range(1, runs + 1):
        for row in gold_rows:
            ann = announcements[row["announcement_id"]]
            requests.append({
                "custom_id": f"req-{len(requests):06d}", "model": models["primary"], "system": system,
                "user": _render_user(ann), "max_tokens": models["max_output_tokens"],
                "temperature": models["temperature"], "extra_body": extra_body,
            })
            plan.append((run_idx, row))

    backend = backend or build_backend(provider, cfg)
    results = backend.run(requests)

    items = []
    for idx, (run_idx, row) in enumerate(plan):
        ann = announcements[row["announcement_id"]]
        items.append(build_item(run_idx, row, ann, _batch_pred(results.get(str(idx)), ann, cfg, prompt_version)))
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
    provider: str = "claude",
    concurrency: int = 1,
    batch: bool = False,
) -> Path:
    """Full harness run for one prompt version + provider. Returns the run directory.

    `provider` selects the classifier (claude / openai / glm); the effective config
    swaps in that provider's model id + pricing, and non-Claude providers run with
    escalation off (they have no escalation model). Scorecard rows are labelled by
    provider so v3 (claude) / v3 (openai) / v3 (glm) sit side by side.
    """
    import copy

    from src.providers import build_client, provider_config

    base = config or load_config()
    pconf = provider_config(provider, base)
    cfg = copy.deepcopy(base)
    cfg["models"]["primary"] = pconf["model"]
    cfg["pricing_usd_per_mtok"]["primary_input"] = pconf["pricing"]["input"]
    cfg["pricing_usd_per_mtok"]["primary_output"] = pconf["pricing"]["output"]
    if provider != "claude":
        cfg["thresholds"]["escalate_above_chars"] = 10 ** 12
        cfg["thresholds"]["escalate_below_confidence"] = 0.0

    # A "custom" eval must classify with the operator's override prompt, not a file.
    # Load it from runtime_config.json into the config the harness passes to classify().
    if prompt_version == "custom":
        try:
            from src.config_schema import load_runtime_config
            override = load_runtime_config().run.classification_prompt_override
        except Exception:
            override = None
        cfg.setdefault("_runtime", {})["classification_prompt_override"] = override

    if client is None:
        client = build_client(provider, base)
    baselines = baselines or {}
    label = prompt_version if provider == "claude" else f"{prompt_version} ({provider})"

    gold_rows = load_gold(gold_path)
    if limit:
        gold_rows = gold_rows[:limit]
    if announcements is None:
        announcements = load_announcements(cfg)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = out_root / f"{timestamp}_{prompt_version}_{provider}"
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    if batch:
        items = batch_evaluate(prompt_version, runs, gold_rows, announcements, cfg, provider,
                               extra_body=pconf.get("extra_body"))
    else:
        items = evaluate(prompt_version, runs, gold_rows, announcements, cfg, client, concurrency=concurrency)
    metrics = report.compute_metrics(items, runs)

    for blabel, fn in baselines.items():
        predictor = resilient(lambda ann, fn=fn: fn(ann, cfg, client), cfg, prompt_version)
        b_items = evaluate(prompt_version, 1, gold_rows, announcements, cfg, client,
                           predictor=predictor, concurrency=concurrency)
        b_metrics = report.compute_metrics(b_items, 1)
        blabel_full = f"baseline: {blabel}" if provider == "claude" else f"baseline: {blabel} ({provider})"
        report.update_ledger(ledger_path, blabel_full, b_metrics["headline"], b_metrics["stability"],
                             {"n": b_metrics["n_items"], "runs": 1})

    detail = {"label": label, **metrics}
    ledger = report.update_ledger(ledger_path, label, metrics["headline"], metrics["stability"],
                                  {"n": metrics["n_items"], "runs": runs,
                                   "model": cfg["models"]["primary"], "provider": provider})

    # The committed trust snapshot the dashboard reads (CONTRACTS §2). Written into the
    # run dir here (so a check calling run_eval() never clobbers the canonical file);
    # main() promotes it to evals/eval_summary.json on the real CLI path.
    from src.config_schema import fingerprint_from
    fp = fingerprint_from(prompt_version, cfg.get("_runtime", {}).get("classification_prompt_override"),
                          provider, base)
    report.write_eval_summary(ledger, detail, fp, out_dir / "eval_summary.json")

    report.write_per_item_csv(items, out_dir / "per_item.csv")
    report.write_failures_csv(items, out_dir / "failures.csv")
    report.write_confusion_csv(metrics["confusion"], out_dir / "confusion_matrix.csv")
    report.render_scorecard_md(ledger, detail, out_dir / "scorecard.md")
    report.render_scorecard_pdf(ledger, out_dir / "scorecard.pdf")
    report.write_manifest(
        {
            "prompt_version": prompt_version,
            "provider": provider,
            "prompt_file_sha256": hashlib.sha256(load_prompt(prompt_version, cfg).encode()).hexdigest(),
            "dataset": (str(gold_path.relative_to(ROOT)) if gold_path.is_relative_to(ROOT) else str(gold_path)),
            "dataset_sha256": _dataset_hash(gold_path),
            "n_items": metrics["n_items"],
            "runs": runs,
            "model_ids": {"primary": cfg["models"]["primary"],
                          "escalation": cfg["models"]["escalation"] if provider == "claude" else None},
            "temperature": cfg["models"]["temperature"],
            "escalate_below_confidence": cfg["thresholds"]["escalate_below_confidence"],
            "escalate_above_chars": cfg["thresholds"]["escalate_above_chars"],
            "total_cost_nzd": metrics["cost_latency"]["total_cost_nzd"],
            "execution": "batch" if batch else "concurrent",
            "batch_discount": BATCH_DISCOUNT if batch else None,
            "concurrency": None if batch else concurrency,
            "timestamp": timestamp,
            "wall_seconds": round(time.monotonic() - started, 1),
            "baselines": list(baselines),
        },
        out_dir / "run_manifest.json",
    )
    return out_dir


def eval_config(config: dict, no_escalation: bool) -> dict:
    """Optionally disable escalation for eval runs (owner cost deviation 2026-08-02).

    Keeps every long filing on the primary model instead of chunking onto the
    escalation model — ~10× cheaper, at the cost of not exercising the Opus
    escalation path. The raised thresholds are written into run_manifest.json, so
    the deviation is visible and reproducible.
    """
    if not no_escalation:
        return config
    import copy

    c = copy.deepcopy(config)
    c["thresholds"]["escalate_above_chars"] = 10 ** 12
    c["thresholds"]["escalate_below_confidence"] = 0.0
    return c


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prompt-version", required=True)
    parser.add_argument("--runs", type=int, default=1,
                        help="repeat count for the stability metric; 1 is enough at temperature 0")
    parser.add_argument("--limit", type=int, default=None, help="evaluate only the first N gold rows (cost control)")
    parser.add_argument("--provider", default="claude", help="claude | openai | glm (see config.yaml providers:)")
    parser.add_argument("--concurrency", type=int, default=None, help="parallel classify calls (default: config eval.concurrency)")
    parser.add_argument("--batch", action="store_true", help="use the provider Batch API (~50%% cheaper, async)")
    parser.add_argument("--no-baselines", action="store_true")
    parser.add_argument("--no-escalation", action="store_true",
                        help="keep long filings on the primary model (cost deviation; recorded in the manifest)")
    args = parser.parse_args()

    baselines = {}
    if not args.no_baselines:
        try:
            from evals.baselines import BASELINES

            baselines = BASELINES
        except Exception as exc:  # baselines land in B4
            print(f"(baselines not available yet: {exc})")

    raw_config = load_config()
    config = eval_config(raw_config, args.no_escalation)
    concurrency = args.concurrency if args.concurrency is not None else (raw_config.get("eval") or {}).get("concurrency", 1)
    if args.no_escalation:
        print("NOTE: escalation disabled for this eval (owner cost deviation) — primary model only.")
    mode = "batch" if args.batch else f"concurrent x{concurrency}"
    print(f"provider={args.provider}  runs={args.runs}  execution={mode}")
    out_dir = run_eval(args.prompt_version, args.runs, limit=args.limit, baselines=baselines, config=config,
                       provider=args.provider, concurrency=concurrency, batch=args.batch)
    print(f"\nWrote {out_dir.relative_to(ROOT)}")

    # Promote this run's trust snapshot to the canonical committed path (CONTRACTS §2) so
    # the dashboard's Trust panel + stale banner refresh. run-eval.yml commits this file.
    import shutil

    canonical = ROOT / "evals" / "eval_summary.json"
    shutil.copyfile(out_dir / "eval_summary.json", canonical)
    print(f"Updated {canonical.relative_to(ROOT)}")
    print((out_dir / "scorecard.md").read_text())


if __name__ == "__main__":
    main()
