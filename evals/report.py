"""report.py — metrics + scorecard rendering for the eval harness (SPEC §13.3, §13.5).

Pure computation and file writing; no model calls. `compute_metrics` turns per-item
results into the headline numbers and the detail blocks; the render_* helpers write
the six artefacts the harness is required to produce (SPEC §13.2). The scorecard
carries one row per prompt version so movement across v1→v2→v3 is visible.

No LLM-as-judge anywhere — every comparison here is a string/label comparison.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

MATERIALITY = ["material", "immaterial", "insufficient_info"]

# Column order for the §13.5 scorecard table.
SCORECARD_COLUMNS = [
    ("recall_material", "Recall (material)"),
    ("precision_material", "Precision"),
    ("grounded_pct", "Grounded %"),
    ("confidently_wrong", "Confidently wrong"),
    ("abstention_ambiguous", "Abstention (ambiguous)"),
    ("cost_per_item_nzd", "Cost/item NZD"),
]


def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def _run_metrics(items: list[dict]) -> dict:
    """Headline scalars for a single run's worth of per-item rows."""
    tp = sum(1 for it in items if it["gold_materiality"] == "material" and it["pred_materiality"] == "material")
    fn = sum(1 for it in items if it["gold_materiality"] == "material" and it["pred_materiality"] != "material")
    fp = sum(1 for it in items if it["gold_materiality"] != "material" and it["pred_materiality"] == "material")
    amb = [it for it in items if it["slice_tag"] == "ambiguous"]
    return {
        "recall_material": _safe_div(tp, tp + fn),
        "precision_material": _safe_div(tp, tp + fp),
        "grounded_pct": _safe_div(sum(1 for it in items if it["grounded"]), len(items)),
        "confidently_wrong": _safe_div(
            sum(1 for it in items if it["confidence"] > 0.8 and it["pred_materiality"] != it["gold_materiality"]),
            len(items),
        ),
        "abstention_ambiguous": _safe_div(
            sum(1 for it in amb if it["pred_materiality"] == "insufficient_info"), len(amb)
        ),
        "cost_per_item_nzd": _safe_div(sum(it["cost_nzd"] for it in items), len(items)),
    }


def _precision_at_k(items: list[dict], k: int) -> float:
    """Rank predicted records by (predicted material, confidence) and score the top k."""
    ranked = sorted(items, key=lambda it: (it["pred_materiality"] == "material", it["confidence"]), reverse=True)
    top = ranked[:k]
    return _safe_div(sum(1 for it in top if it["gold_materiality"] == "material"), len(top))


def compute_metrics(items: list[dict], runs: int) -> dict:
    """Aggregate per-item rows (all runs concatenated) into headline + detail metrics."""
    by_run: dict[int, list[dict]] = defaultdict(list)
    for it in items:
        by_run[it["run"]].append(it)

    per_run = [_run_metrics(rows) for rows in by_run.values()]
    headline, stability = {}, {}
    for key, _ in SCORECARD_COLUMNS:
        vals = [m[key] for m in per_run]
        headline[key] = statistics.mean(vals) if vals else 0.0
        stability[key] = statistics.pstdev(vals) if len(vals) > 1 else 0.0

    confusion = {g: {p: 0 for p in MATERIALITY} for g in MATERIALITY}
    for it in items:
        confusion[it["gold_materiality"]][it["pred_materiality"]] += 1

    p_at_5 = statistics.mean([_precision_at_k(rows, 5) for rows in by_run.values()])
    p_at_10 = statistics.mean([_precision_at_k(rows, 10) for rows in by_run.values()])

    extraction = {
        "materiality_accuracy": _safe_div(
            sum(1 for it in items if it["pred_materiality"] == it["gold_materiality"]), len(items)
        ),
        "category_exact_match": _safe_div(
            sum(1 for it in items if set(it["pred_categories"]) == set(it["gold_categories"])), len(items)
        ),
        "evidence_grounded": _safe_div(sum(1 for it in items if it["grounded"]), len(items)),
    }

    slices: dict[str, dict[str, float]] = {}
    for dim in ("slice_tag", "difficulty", "doc_type", "char_band"):
        buckets: dict[str, list[dict]] = defaultdict(list)
        for it in items:
            buckets[str(it.get(dim, ""))].append(it)
        slices[dim] = {
            key: _safe_div(sum(1 for it in rows if it["pred_materiality"] == it["gold_materiality"]), len(rows))
            for key, rows in sorted(buckets.items())
        }

    latencies = [it["latency_ms"] for it in items if it.get("latency_ms") is not None]
    costs = [it["cost_nzd"] for it in items]
    cost_latency = {
        "total_cost_nzd": sum(costs),
        "cost_per_item_nzd": _safe_div(sum(costs), len(items)),
        "latency_p50_ms": statistics.median(latencies) if latencies else 0,
        "latency_p95_ms": (sorted(latencies)[int(0.95 * (len(latencies) - 1))] if latencies else 0),
        "escalation_rate": _safe_div(sum(1 for it in items if it.get("escalated")), len(items)),
    }

    return {
        "headline": headline,
        "stability": stability,
        "confusion": confusion,
        "ranking": {"precision_at_5": p_at_5, "precision_at_10": p_at_10},
        "extraction": extraction,
        "slices": slices,
        "cost_latency": cost_latency,
        "n_items": len(next(iter(by_run.values()))) if by_run else 0,
        "runs": runs,
    }


# --- ledger: accumulates one headline row per label so the scorecard shows movement ---

def update_ledger(ledger_path: Path, label: str, headline: dict, stability: dict, meta: dict) -> dict:
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {"rows": {}}
    ledger["rows"][label] = {"headline": headline, "stability": stability, "meta": meta}
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, indent=2))
    return ledger


LEDGER_ROW_ORDER = ["v1", "v2", "v3", "baseline: rules", "baseline: flag_all", "baseline: naive_prompt"]

# The v3 finding (PROGRESS.md): grounding is a MODEL limit, not a prompt limit —
# Haiku 0.374 vs GPT 0.94 / GLM 0.83 on the identical forced-verbatim v3 prompt.
# Carried into every eval_summary.json so the dashboard always shows it (§2).
HAIKU_GROUNDING_CAVEAT = (
    "Grounding ~37% on Haiku is a MODEL limit, not a prompt limit "
    "(GPT 0.94 / GLM 0.83 on the identical v3 prompt)."
)


def write_eval_summary(ledger: dict, detail: dict, fingerprint: str, out_path: Path) -> dict:
    """Write `evals/eval_summary.json` in the CONTRACTS.md §2 shape. Returns it too.

    `ledger` is the accumulated `{"rows": {label: {"headline", "stability", "meta"}}}`
    from `update_ledger` — one row per prompt version / baseline / provider variant.
    `detail` is the CURRENT run's `compute_metrics()` output; its `ranking`,
    `n_items` and `runs` populate the top-level fields of the same name. `fingerprint`
    should be `config_schema.eval_fingerprint()` for the configuration this eval ran
    under — the dashboard compares it to the LIVE runtime_config fingerprint and
    shows a stale banner when they differ (§1).

    `providers` is built from ledger rows whose `meta` carries a `"model"` key (the
    caller records the model id there when it evaluates a named provider/model);
    rows without it are prompt-version-only scorecard entries and do not appear in
    `providers`.
    """
    scorecard = {
        label: {key: row["headline"][key] for key, _ in SCORECARD_COLUMNS}
        for label, row in ledger["rows"].items()
    }
    providers = [
        {
            "model": row["meta"]["model"],
            "recall": row["headline"]["recall_material"],
            "precision": row["headline"]["precision_material"],
            "grounded": row["headline"]["grounded_pct"],
            "confidently_wrong": row["headline"]["confidently_wrong"],
            "abstention": row["headline"]["abstention_ambiguous"],
            "cost_per_item_nzd": row["headline"]["cost_per_item_nzd"],
        }
        for row in ledger["rows"].values()
        if row.get("meta", {}).get("model")
    ]
    summary = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "eval_config_fingerprint": fingerprint,
        "n_items": detail.get("n_items", 0),
        "runs": detail.get("runs", 0),
        "scorecard": scorecard,
        "ranking": dict(detail.get("ranking", {"precision_at_5": 0.0, "precision_at_10": 0.0})),
        "providers": providers,
        "caveats": [HAIKU_GROUNDING_CAVEAT],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def _fmt(key: str, value: float) -> str:
    return f"{value:.4f}" if key == "cost_per_item_nzd" else f"{value:.3f}"


def _ordered_labels(ledger: dict) -> list[str]:
    labels = [lbl for lbl in LEDGER_ROW_ORDER if lbl in ledger["rows"]]
    labels += [lbl for lbl in ledger["rows"] if lbl not in LEDGER_ROW_ORDER]
    return labels


def render_scorecard_md(ledger: dict, detail: dict, out_path: Path) -> None:
    lines = ["# Scorecard", "", "_One row per prompt version + baselines (SPEC §13.5). "
             "Recall is weighted above precision; bare accuracy is never reported._", ""]
    header = "| Prompt | " + " | ".join(title for _, title in SCORECARD_COLUMNS) + " |"
    sep = "|" + "---|" * (len(SCORECARD_COLUMNS) + 1)
    lines += [header, sep]
    for lbl in _ordered_labels(ledger):
        row = ledger["rows"][lbl]["headline"]
        lines.append(f"| {lbl} | " + " | ".join(_fmt(key, row[key]) for key, _ in SCORECARD_COLUMNS) + " |")
    lines.append("")

    h, st = detail["headline"], detail["stability"]
    lines += [f"## Detail — this run ({detail['label']}, n={detail['n_items']}, runs={detail['runs']})", ""]
    lines.append(f"- Recall(material)@precision≥0.60: **{h['recall_material']:.3f}** "
                 f"(precision {h['precision_material']:.3f}"
                 f"{'' if h['precision_material'] >= 0.60 else ' — BELOW the 0.60 floor'})")
    lines.append(f"- Grounded (G2 pass, hallucination-free): **{h['grounded_pct']:.3f}**")
    lines.append(f"- Confidently wrong (conf>0.8 & wrong): **{h['confidently_wrong']:.3f}**")
    lines.append(f"- Abstention on the ambiguous slice: **{h['abstention_ambiguous']:.3f}**")
    lines.append(f"- Ranking: P@5 **{detail['ranking']['precision_at_5']:.3f}**, "
                 f"P@10 **{detail['ranking']['precision_at_10']:.3f}**")
    lines.append(f"- Cost/item **NZ${h['cost_per_item_nzd']:.4f}**, total **NZ${detail['cost_latency']['total_cost_nzd']:.4f}**, "
                 f"escalation rate {detail['cost_latency']['escalation_rate']:.2f}, "
                 f"latency p50 {detail['cost_latency']['latency_p50_ms']}ms / p95 {detail['cost_latency']['latency_p95_ms']}ms")
    lines.append(f"- Stability (σ across {detail['runs']} runs): recall {st['recall_material']:.3f}, "
                 f"precision {st['precision_material']:.3f}")
    lines.append("")

    lines += ["### Confusion (gold ↓ × predicted →)", "", "| gold \\ pred | " + " | ".join(MATERIALITY) + " |",
              "|" + "---|" * (len(MATERIALITY) + 1)]
    for g in MATERIALITY:
        lines.append(f"| {g} | " + " | ".join(str(detail['confusion'][g][p]) for p in MATERIALITY) + " |")
    lines.append("")

    lines += ["### Extraction (unaveraged)", ""]
    for k, v in detail["extraction"].items():
        lines.append(f"- {k}: {v:.3f}")
    lines.append("")

    lines += ["### Materiality accuracy by slice", ""]
    for dim, buckets in detail["slices"].items():
        lines.append(f"- **{dim}**: " + ", ".join(f"{k} {v:.2f}" for k, v in buckets.items()))
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def render_scorecard_pdf(ledger: dict, out_path: Path) -> None:
    """The §13.5 table as a one-page PDF (matplotlib). The handover artefact."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = _ordered_labels(ledger)
    col_titles = ["Prompt"] + [title for _, title in SCORECARD_COLUMNS]
    table_rows = [[lbl] + [_fmt(key, ledger["rows"][lbl]["headline"][key]) for key, _ in SCORECARD_COLUMNS]
                  for lbl in labels]

    fig, ax = plt.subplots(figsize=(11, 1.4 + 0.5 * (len(table_rows) + 1)))
    ax.axis("off")
    ax.set_title("Announcement Triage Agent — scorecard (SPEC §13.5)", fontsize=13, pad=16)
    tbl = ax.table(cellText=table_rows, colLabels=col_titles, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.6)
    for c in range(len(col_titles)):
        tbl[0, c].set_facecolor("#1f2937")
        tbl[0, c].set_text_props(color="white", fontweight="bold")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def write_per_item_csv(items: list[dict], out_path: Path) -> None:
    cols = ["run", "announcement_id", "ticker", "slice_tag", "difficulty", "doc_type", "char_band",
            "gold_materiality", "pred_materiality", "correct", "confidence", "grounded",
            "guardrail_flags", "gold_categories", "pred_categories", "cost_nzd", "latency_ms", "escalated"]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for it in items:
            row = dict(it)
            row["guardrail_flags"] = ";".join(it.get("guardrail_flags", []))
            row["gold_categories"] = ";".join(it.get("gold_categories", []))
            row["pred_categories"] = ";".join(it.get("pred_categories", []))
            w.writerow(row)


def write_failures_csv(items: list[dict], out_path: Path) -> None:
    """Every disagreement, model rationale beside owner rationale (SPEC §13.2)."""
    cols = ["run", "announcement_id", "ticker", "slice_tag", "gold_materiality", "pred_materiality",
            "confidence", "model_rationale", "owner_rationale", "guardrail_flags"]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for it in items:
            if it["pred_materiality"] != it["gold_materiality"]:
                w.writerow({
                    "run": it["run"], "announcement_id": it["announcement_id"], "ticker": it["ticker"],
                    "slice_tag": it["slice_tag"], "gold_materiality": it["gold_materiality"],
                    "pred_materiality": it["pred_materiality"], "confidence": it["confidence"],
                    "model_rationale": it.get("rationale", ""), "owner_rationale": it.get("gold_rationale", ""),
                    "guardrail_flags": ";".join(it.get("guardrail_flags", [])),
                })


def write_confusion_csv(confusion: dict, out_path: Path) -> None:
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["gold\\pred"] + MATERIALITY)
        for g in MATERIALITY:
            w.writerow([g] + [confusion[g][p] for p in MATERIALITY])


def write_manifest(manifest: dict, out_path: Path) -> None:
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
