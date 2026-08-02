"""brief.py — the markdown morning brief (SPEC.md §11). Increment 8.

Three sections: the ranked material list, the "Needs a look" list (abstentions and
guardrail-flagged records, each with the flag named), and a run footer in which the
system reports on itself. Written to out/briefs/YYYY-MM-DD.md. No HTML, no styling.
"""

from __future__ import annotations

from datetime import date as date_cls
from pathlib import Path

from src.rank import RankedItem

ROOT = Path(__file__).resolve().parent.parent
BRIEFS_DIR = ROOT / "out" / "briefs"


def _material_block(items: list[RankedItem]) -> list[str]:
    if not items:
        return ["_No material announcements this run._"]
    lines: list[str] = []
    for i, it in enumerate(items, start=1):
        c, ann = it.classification, it.announcement
        lines += [
            f"{i}. **{ann.ticker}** — {ann.headline}",
            f"   - {c.rationale}",
            f"   - > {c.evidence_quote}",
            f"   - [source]({ann.source_url}) · score {it.score:.3f}",
        ]
    return lines


def _needs_look_block(items: list[RankedItem]) -> list[str]:
    if not items:
        return ["_Nothing needs a look this run._"]
    lines: list[str] = []
    for it in items:
        c, ann = it.classification, it.announcement
        why = ", ".join(c.guardrail_flags) if c.guardrail_flags else "abstained (insufficient_info)"
        lines += [
            f"- **{ann.ticker}** — {ann.headline}",
            f"   - flag: {why}",
            f"   - [source]({ann.source_url})",
        ]
    return lines


def render_brief(
    ranked: list[RankedItem],
    needs_look: list[RankedItem],
    stats: dict,
    brief_date: date_cls | None = None,
    out_dir: Path | None = None,
) -> Path:
    brief_date = brief_date or date_cls.today()
    out_dir = out_dir or BRIEFS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    flag_counts = stats.get("guardrail_flag_counts", {})
    flags_str = ", ".join(f"{k}={v}" for k, v in sorted(flag_counts.items())) or "none"

    lines = [
        f"# Announcement brief — {brief_date.isoformat()}",
        "",
        "## Material — ranked",
        "",
        *_material_block(ranked),
        "",
        "## Needs a look",
        "",
        *_needs_look_block(needs_look),
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
