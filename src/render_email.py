"""render_email.py — the Milford-themed HTML email brief (CONTRACTS.md §4).

Mirrors brief.py's three sections (ranked material, needs a look, run footer) but
renders a self-contained, inline-CSS HTML document suitable for a Gmail draft: no
external stylesheet, no @font-face (mail clients drop both), only inline
`style="..."` attributes built from `src.theme.THEME`. Written to
`out/briefs/<DATE>.email.html` for the morning digest, or
`out/briefs/<DATE>T<HH-MM>.email.html` when `brief_date` is a `datetime` carrying
a non-midnight time — the intraday alert path (`src.run --intraday`).
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime
from html import escape
from pathlib import Path

from src.enrich import Enrichment
from src.rank import RankedItem
from src.theme import FONT_BODY, FONT_DISPLAY, THEME

ROOT = Path(__file__).resolve().parent.parent
BRIEFS_DIR = ROOT / "out" / "briefs"


def _filename(brief_date: date_cls | datetime) -> str:
    if isinstance(brief_date, datetime) and (brief_date.hour, brief_date.minute) != (0, 0):
        return f"{brief_date.date().isoformat()}T{brief_date.hour:02d}-{brief_date.minute:02d}.email.html"
    d = brief_date.date() if isinstance(brief_date, datetime) else brief_date
    return f"{d.isoformat()}.email.html"


def _display_date(brief_date: date_cls | datetime) -> str:
    d = brief_date.date() if isinstance(brief_date, datetime) else brief_date
    return d.isoformat()


def _card(inner: str, extra: str = "") -> str:
    style = (f"background:{THEME['paper']}; border:1px solid #dce2e4; "
             f"border-radius:{THEME['radius_card']}px; padding:16px; margin:0 0 12px 0; {extra}")
    return f'<div style="{style}">{inner}</div>'


def _material_block(items: list[RankedItem], enrichment_by_id: dict[str, Enrichment]) -> str:
    if not items:
        return _card(f'<p style="margin:0; color:{THEME["muted"]};">No material announcements this run.</p>')
    rows = []
    for i, it in enumerate(items, start=1):
        c, ann = it.classification, it.announcement
        enr = enrichment_by_id.get(ann.announcement_id)
        filing_url = enr.filing_url if enr else ann.source_url
        news_html = ""
        if enr and enr.news_url:
            news_html = (f' &middot; <a href="{escape(enr.news_url)}" '
                         f'style="color:{THEME["blue"]}; text-decoration:none;">{escape(enr.news_label)}</a>')
        rows.append(_card(
            f'<p style="margin:0 0 4px 0; font-family:{FONT_DISPLAY}; font-size:16px; color:{THEME["slate"]};">'
            f'{i}. {escape(ann.ticker)} &mdash; {escape(ann.headline)}</p>'
            f'<p style="margin:0 0 8px 0; color:{THEME["slate_2"]}; font-size:14px;">{escape(c.rationale)}</p>'
            f'<p style="margin:0 0 8px 0; padding:8px 10px; background:{THEME["cloud"]}; '
            f'border-left:3px solid {THEME["orange"]}; font-size:13px; color:{THEME["slate"]};">'
            f'&ldquo;{escape(c.evidence_quote)}&rdquo;</p>'
            f'<p style="margin:0; font-size:12px; color:{THEME["muted"]};">'
            f'<a href="{escape(filing_url)}" style="color:{THEME["orange"]}; text-decoration:none; '
            f'font-weight:bold;">Filing</a>{news_html} &middot; score {it.score:.3f}</p>'
        ))
    return "".join(rows)


def _needs_look_block(items: list[RankedItem]) -> str:
    if not items:
        return _card(f'<p style="margin:0; color:{THEME["muted"]};">Nothing needs a look this run.</p>')
    rows = []
    for it in items:
        c, ann = it.classification, it.announcement
        why = ", ".join(c.guardrail_flags) if c.guardrail_flags else "abstained (insufficient_info)"
        rows.append(_card(
            f'<p style="margin:0 0 4px 0; color:{THEME["slate"]}; font-weight:bold;">'
            f'{escape(ann.ticker)} &mdash; {escape(ann.headline)}</p>'
            f'<p style="margin:0 0 4px 0; font-size:13px; color:{THEME["danger"]};">flag: {escape(why)}</p>'
            f'<p style="margin:0; font-size:12px;">'
            f'<a href="{escape(ann.source_url)}" style="color:{THEME["orange"]}; text-decoration:none;">Filing</a></p>'
        ))
    return "".join(rows)


def _footer_block(stats: dict) -> str:
    flag_counts = stats.get("guardrail_flag_counts", {})
    flags_str = ", ".join(f"{k}={v}" for k, v in sorted(flag_counts.items())) or "none"
    lines = [
        f"Announcements processed: {stats.get('processed', 0)} "
        f"({stats.get('new', 0)} new, {stats.get('deduped', 0)} deduped)",
        f"Models: primary {stats.get('model_primary', '')}, escalation {stats.get('model_escalation', '')}",
        f"Prompt version: {stats.get('prompt_version', '')}",
        f"Escalations: {stats.get('escalation_count', 0)}",
        f"Guardrail flags: {flags_str}",
        f"Total cost: NZ${stats.get('total_cost_nzd', 0.0):.4f}",
        f"Runtime: {stats.get('runtime_seconds', 0.0):.1f}s",
    ]
    items_html = "".join(f'<li style="margin:0 0 4px 0;">{escape(line)}</li>' for line in lines)
    return f'<ul style="margin:0; padding-left:18px; color:{THEME["muted"]}; font-size:12px;">{items_html}</ul>'


def _section_header(title: str) -> str:
    return (f'<h2 style="font-family:{FONT_DISPLAY}; color:{THEME["slate"]}; '
            f'font-size:18px; margin:24px 0 10px 0;">{escape(title)}</h2>')


def render_email(
    ranked: list[RankedItem],
    needs_look: list[RankedItem],
    stats: dict,
    enrichment: list[Enrichment],
    brief_date: date_cls | datetime | None = None,
    out_dir: Path | None = None,
) -> Path:
    """Render the self-contained, Milford-themed HTML email brief and write it to disk.

    Mirrors brief.py's three sections (material — ranked, needs a look, run
    footer). Every color is inlined via `src.theme.THEME`; fonts fall back to
    web-safe stacks. Pass a `datetime` (not a bare `date`) with a non-midnight
    time in `brief_date` to get the intraday filename
    (`out/briefs/<DATE>T<HH-MM>.email.html`); otherwise the digest filename
    (`out/briefs/<DATE>.email.html`) is used.
    """
    brief_date = brief_date or date_cls.today()
    out_dir = out_dir or BRIEFS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    enrichment_by_id = {e.announcement_id: e for e in enrichment}

    html = f"""<div style="font-family:{FONT_BODY}; background:#f4f6f6; padding:24px;">
  <div style="max-width:640px; margin:0 auto; background:{THEME['paper']}; \
border-radius:{THEME['radius_surface']}px; padding:24px; border:1px solid #dce2e4;">
    <p style="margin:0 0 4px 0; color:{THEME['orange']}; font-size:11px; font-weight:bold; \
letter-spacing:.08em; text-transform:uppercase;">Milford &middot; Announcement Triage</p>
    <h1 style="font-family:{FONT_DISPLAY}; color:{THEME['slate']}; font-size:24px; margin:0 0 16px 0;">\
Announcement brief &mdash; {escape(_display_date(brief_date))}</h1>
    {_section_header("Material — ranked")}
    {_material_block(ranked, enrichment_by_id)}
    {_section_header("Needs a look")}
    {_needs_look_block(needs_look)}
    {_section_header("Run footer")}
    {_footer_block(stats)}
  </div>
</div>"""

    path = out_dir / _filename(brief_date)
    path.write_text(html, encoding="utf-8")
    return path
