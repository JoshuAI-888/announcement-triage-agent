"""brief.py — the markdown morning brief (SPEC.md §11). Increment 8.

Four sections: the ranked material list, the "Needs a look" list (abstentions and
guardrail-flagged records, each with the flag explained in plain English), the
"All filings this run" table (every classified filing, material + immaterial +
needs-a-look), and a run footer in which the system reports on itself. Written to
out/briefs/YYYY-MM-DD.md. No HTML, no styling.

Every guardrail flag and abstention is expanded to plain English via `src.flags`
before it reaches this module's output — a raw `G#_...` code or the literal
`insufficient_info` must never appear in the rendered markdown.
"""

from __future__ import annotations

from datetime import date as date_cls
from pathlib import Path

from src.enrich import Enrichment
from src.flags import MATERIALITY_LABEL, doc_type_label, explain_flag, explain_flags
from src.rank import RankedItem

ROOT = Path(__file__).resolve().parent.parent
BRIEFS_DIR = ROOT / "out" / "briefs"

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _native_form(ann) -> str:
    """The bare native form (e.g. "8-K"), stripping the "[items]" audit suffix."""
    return ann.native_doc_type.split(" [")[0]


def _text_sparkline(series7: list[float]) -> str:
    """A compact unicode block sparkline — markdown has no bars, so this is the mirror."""
    if not series7:
        return ""
    lo, hi = min(series7), max(series7)
    span = (hi - lo) or 1.0
    top = len(_SPARK_CHARS) - 1
    return "".join(_SPARK_CHARS[min(top, int((v - lo) / span * top))] for v in series7)


def _material_block(items: list[RankedItem], enrichment_by_id: dict[str, Enrichment]) -> list[str]:
    if not items:
        return ["_No material announcements this run._"]
    lines: list[str] = []
    for i, it in enumerate(items, start=1):
        c, ann = it.classification, it.announcement
        enr = enrichment_by_id.get(ann.announcement_id)
        company_line = ann.company_name + (f" ({ann.industry})" if ann.industry else "")
        lines += [
            f"{i}. **{ann.ticker}** — {ann.headline}",
            f"   - {company_line}",
        ]
        if enr and enr.company:
            text = " ".join(
                t for t in ((enr.company.get("business") or "").strip(), (enr.company.get("edge") or "").strip()) if t
            )
            if text:
                lines.append(f"   - _{text}_")
                caveat = (enr.company.get("caveat") or "").strip()
                if caveat:
                    lines.append(f"   - ({caveat})")
        if enr and enr.price:
            p = enr.price
            change = p.get("change") or 0.0
            arrow = "▲" if change >= 0 else "▼"
            spark = _text_sparkline(p.get("series7") or [])
            lines.append(
                f"   - {p.get('currency', 'USD')} {p['last']:.2f} {arrow} {change:+.2f} "
                f"({(p.get('change_pct') or 0.0):+.2f}%)" + (f"  `{spark}`" if spark else "")
            )
        news_link = f" · [news]({enr.news_url})" if enr and enr.news_url else ""
        lines += [
            f"   - {c.rationale}",
            f"   - > {c.evidence_quote}",
            f"   - [source]({ann.source_url}){news_link} · score {it.score:.3f}",
        ]
    return lines


def _needs_look_block(items: list[RankedItem]) -> list[str]:
    if not items:
        return ["_Nothing needs a look this run._"]
    lines: list[str] = []
    for it in items:
        c, ann = it.classification, it.announcement
        explained = explain_flags(c.guardrail_flags) if c.guardrail_flags else [explain_flag("insufficient_info")]
        lines += [
            f"- **{ann.ticker}** — {ann.headline}",
            "   - Why flagged:",
        ]
        for f in explained:
            lines.append(f"     - **{f['label']}** — {f['why']}")
        lines.append(f"   - [source]({ann.source_url})")
    return lines


def _all_filings_table(items: list[RankedItem]) -> list[str]:
    """One row per classified filing this run (material + immaterial + needs-a-look)."""
    if not items:
        return ["_No filings classified this run._"]
    lines = [
        "| Company | Document | Materiality | Rationale |",
        "|---|---|---|---|",
    ]
    for it in items:
        c, ann = it.classification, it.announcement
        label = doc_type_label(ann.doc_type, _native_form(ann))
        rationale = c.rationale if len(c.rationale) <= 160 else c.rationale[:157] + "..."
        rationale = rationale.replace("|", "\\|")
        company = f"[{ann.ticker}]({ann.source_url}) — {ann.company_name}".replace("|", "\\|")
        mlabel = MATERIALITY_LABEL.get(c.materiality, c.materiality)
        lines.append(f"| {company} | {label} | {mlabel} | {rationale} |")
    return lines


def _flags_summary(flag_counts: dict) -> str:
    if not flag_counts:
        return "none"
    return ", ".join(f'{explain_flag(code)["label"]} ({n})' for code, n in sorted(flag_counts.items()))


def render_brief(
    ranked: list[RankedItem],
    needs_look: list[RankedItem],
    stats: dict,
    enrichment: list[Enrichment] | None = None,
    all_items: list[RankedItem] | None = None,
    brief_date: date_cls | None = None,
    out_dir: Path | None = None,
) -> Path:
    brief_date = brief_date or date_cls.today()
    out_dir = out_dir or BRIEFS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    enrichment_by_id = {e.announcement_id: e for e in (enrichment or [])}
    all_items = all_items or []

    flags_str = _flags_summary(stats.get("guardrail_flag_counts", {}))

    lines = [
        f"# Announcement brief — {brief_date.isoformat()}",
        "",
        "## Material — ranked",
        "",
        *_material_block(ranked, enrichment_by_id),
        "",
        "## Needs a look",
        "",
        *_needs_look_block(needs_look),
        "",
        "## All filings this run",
        "",
        *_all_filings_table(all_items),
        "",
        "## Run footer",
        "",
        f"- Announcements processed: {stats.get('processed', 0)} "
        f"({stats.get('new', 0)} new, {stats.get('deduped', 0)} deduped)",
        f"- Models: primary `{stats.get('model_primary', '')}`, escalation `{stats.get('model_escalation', '')}`",
        f"- Prompt version: {stats.get('prompt_version', '')}",
        f"- Escalations: {stats.get('escalation_count', 0)}",
        f"- Guardrail flags: {flags_str}",
        f"- Total cost: NZ${stats.get('total_cost_nzd', 0.0):.4f}",
        f"- Runtime: {stats.get('runtime_seconds', 0.0):.1f}s",
        "",
    ]
    path = out_dir / f"{brief_date.isoformat()}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
