"""render_email.py — the Milford-themed HTML email brief (CONTRACTS.md §4).

Mirrors brief.py's four sections (ranked material, needs a look, all filings this
run, run footer) but renders a self-contained, inline-CSS HTML document suitable
for a Gmail draft: no external stylesheet, no @font-face (mail clients drop
both), only inline `style="..."` attributes built from `src.theme.THEME`.
Written to `out/briefs/<DATE>.email.html` for the morning digest, or
`out/briefs/<DATE>T<HH-MM>.email.html` when `brief_date` is a `datetime` carrying
a non-midnight time — the intraday alert path (`src.run --intraday`).

Every guardrail flag and abstention is expanded to plain English via
`src.flags` before it reaches this module's output — a raw `G#_...` code or the
literal `insufficient_info` must never appear in the rendered HTML.

The 7-day price sparkline is built from an HTML `<table>` of bottom-aligned
`<div>` bars, NOT inline `<svg>` — Gmail and most mail clients strip `<svg>`.
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime
from html import escape
from pathlib import Path

from src.enrich import Enrichment
from src.flags import MATERIALITY_LABEL, doc_type_label, explain_flag, explain_flags
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


def _native_form(ann) -> str:
    """The bare native form (e.g. "8-K"), stripping the "[items]" audit suffix."""
    return ann.native_doc_type.split(" [")[0]


def _sparkline_html(series7: list[float]) -> str:
    """Mail-safe 7-day sparkline: a `<table>` of bottom-aligned coloured `<div>` bars.

    NOT inline `<svg>` — Gmail and most mail clients strip it. The most recent
    bar (last in the chronological series) is highlighted orange.
    """
    if not series7:
        return ""
    lo, hi = min(series7), max(series7)
    span = (hi - lo) or 1.0
    max_px = 26
    n = len(series7)
    cells = []
    for i, v in enumerate(series7):
        h = max(2, round((v - lo) / span * max_px))
        color = THEME["orange"] if i == n - 1 else THEME["blue"]
        cells.append(
            f'<td style="width:8px; height:{max_px}px; vertical-align:bottom; padding:0 1px 0 0;">'
            f'<div style="width:6px; height:{h}px; background:{color}; border-radius:1px;"></div></td>'
        )
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'style="display:inline-table; border-collapse:collapse; vertical-align:middle;">'
        f'<tr>{"".join(cells)}</tr></table>'
    )


def _price_block_html(price: dict | None) -> str:
    """Last price + change (▲/▼, coloured) + the 7-day sparkline. "" if no snapshot."""
    if not price or price.get("last") is None:
        return ""
    change = price.get("change") or 0.0
    change_pct = price.get("change_pct") or 0.0
    up = change >= 0
    color = THEME["green"] if up else THEME["danger"]
    arrow = "&#9650;" if up else "&#9660;"  # ▲ / ▼
    spark = _sparkline_html(price.get("series7") or [])
    return (
        f'<p style="margin:6px 0 0 0; font-size:13px; color:{THEME["slate"]};">'
        f'{escape(price.get("currency", "USD"))} {price["last"]:.2f}&nbsp; '
        f'<span style="color:{color}; font-weight:bold;">{arrow} {abs(change):.2f} '
        f'({abs(change_pct):.2f}%)</span>'
        f'{"&nbsp;&nbsp;" + spark if spark else ""}'
        f'</p>'
    )


def _company_block_html(ann, company: dict | None) -> str:
    """Industry line + AI business/edge blurb + its caveat footnote. "" if nothing to show."""
    parts = []
    if ann.industry:
        parts.append(
            f'<p style="margin:2px 0 0 0; font-size:12px; color:{THEME["muted"]};">{escape(ann.industry)}</p>'
        )
    if company:
        text = " ".join(t for t in ((company.get("business") or "").strip(), (company.get("edge") or "").strip()) if t)
        if text:
            parts.append(
                f'<p style="margin:4px 0 0 0; font-size:12px; color:{THEME["slate_2"]};">{escape(text)}</p>'
            )
            caveat = (company.get("caveat") or "").strip()
            if caveat:
                parts.append(
                    f'<p style="margin:2px 0 0 0; font-size:10px; color:{THEME["muted"]}; font-style:italic;">'
                    f'{escape(caveat)}</p>'
                )
    return "".join(parts)


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
        company_html = _company_block_html(ann, enr.company if enr else None)
        price_html = _price_block_html(enr.price if enr else None)
        rows.append(_card(
            f'<p style="margin:0 0 2px 0; font-family:{FONT_DISPLAY}; font-size:16px; color:{THEME["slate"]};">'
            f'{i}. {escape(ann.ticker)} &mdash; {escape(ann.headline)}</p>'
            f'<p style="margin:0; font-size:13px; color:{THEME["slate_2"]}; font-weight:bold;">'
            f'{escape(ann.company_name)}</p>'
            f'{company_html}'
            f'{price_html}'
            f'<p style="margin:8px 0 8px 0; color:{THEME["slate_2"]}; font-size:14px;">{escape(c.rationale)}</p>'
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
        explained = explain_flags(c.guardrail_flags) if c.guardrail_flags else [explain_flag("insufficient_info")]
        flags_html = "".join(
            f'<p style="margin:0 0 4px 0; font-size:13px; color:{THEME["danger"]};">'
            f'<strong>{escape(f["label"])}</strong> &mdash; {escape(f["why"])}</p>'
            for f in explained
        )
        rows.append(_card(
            f'<p style="margin:0 0 4px 0; color:{THEME["slate"]}; font-weight:bold;">'
            f'{escape(ann.ticker)} &mdash; {escape(ann.headline)}</p>'
            f'<p style="margin:0 0 4px 0; font-size:11px; color:{THEME["muted"]}; '
            f'text-transform:uppercase; letter-spacing:.04em;">Why flagged</p>'
            f'{flags_html}'
            f'<p style="margin:0; font-size:12px;">'
            f'<a href="{escape(ann.source_url)}" style="color:{THEME["orange"]}; text-decoration:none;">Filing</a></p>'
        ))
    return "".join(rows)


def _materiality_chip_style(materiality: str) -> str:
    color = {
        "material": THEME["success"],
        "immaterial": THEME["muted"],
        "insufficient_info": THEME["warning"],
    }.get(materiality, THEME["muted"])
    return (f'display:inline-block; padding:2px 8px; border-radius:{THEME["radius_control"]}px; '
            f'background:{color}; color:#ffffff; font-size:11px; font-weight:bold; white-space:nowrap;')


def _all_filings_table(items: list[RankedItem]) -> str:
    """One row per classified filing this run (material + immaterial + needs-a-look)."""
    if not items:
        return _card(f'<p style="margin:0; color:{THEME["muted"]};">No filings classified this run.</p>')
    header_cell = (f'style="text-align:left; padding:6px 8px; font-size:11px; color:{THEME["muted"]}; '
                   f'text-transform:uppercase; letter-spacing:.03em; border-bottom:1px solid #dce2e4;"')
    header = (
        f'<tr><th {header_cell}>Company</th><th {header_cell}>Document</th>'
        f'<th {header_cell}>Materiality</th><th {header_cell}>Rationale</th></tr>'
    )

    def _td(content: str, extra_style: str = "") -> str:
        style = f'padding:6px 8px; border-bottom:1px solid {THEME["cloud"]}; font-size:12px; vertical-align:top; {extra_style}'
        return f'<td style="{style}">{content}</td>'

    rows = []
    for it in items:
        c, ann = it.classification, it.announcement
        label = doc_type_label(ann.doc_type, _native_form(ann))
        rationale = c.rationale if len(c.rationale) <= 160 else c.rationale[:157] + "..."
        mlabel = MATERIALITY_LABEL.get(c.materiality, c.materiality)
        chip_style = _materiality_chip_style(c.materiality)
        company_cell = (f'<a href="{escape(ann.source_url)}" style="color:{THEME["orange"]}; '
                        f'text-decoration:none; font-weight:bold;">{escape(ann.ticker)}</a> '
                        f'&mdash; {escape(ann.company_name)}')
        rows.append(
            '<tr>'
            + _td(company_cell)
            + _td(escape(label), f'color:{THEME["slate_2"]};')
            + _td(f'<span style="{chip_style}">{escape(mlabel)}</span>')
            + _td(escape(rationale), f'color:{THEME["slate_2"]};')
            + '</tr>'
        )
    table = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'style="width:100%; border-collapse:collapse; background:{THEME["paper"]};">'
        f'{header}{"".join(rows)}</table>'
    )
    return _card(table)


def _footer_block(stats: dict) -> str:
    flag_counts = stats.get("guardrail_flag_counts", {})
    if flag_counts:
        flags_str = ", ".join(
            f'{explain_flag(code)["label"]} ({n})' for code, n in sorted(flag_counts.items())
        )
    else:
        flags_str = "none"
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
    all_items: list[RankedItem] | None = None,
    brief_date: date_cls | datetime | None = None,
    out_dir: Path | None = None,
) -> Path:
    """Render the self-contained, Milford-themed HTML email brief and write it to disk.

    Mirrors brief.py's four sections (material — ranked, needs a look, all
    filings this run, run footer). Every color is inlined via `src.theme.THEME`;
    fonts fall back to web-safe stacks. Pass a `datetime` (not a bare `date`)
    with a non-midnight time in `brief_date` to get the intraday filename
    (`out/briefs/<DATE>T<HH-MM>.email.html`); otherwise the digest filename
    (`out/briefs/<DATE>.email.html`) is used.

    `all_items` is every classified filing this run (material + immaterial +
    needs-a-look) — it drives the "All filings this run" table. Defaults to
    empty when the caller has nothing to pass (e.g. a check exercising only
    the material/needs-look sections).
    """
    brief_date = brief_date or date_cls.today()
    out_dir = out_dir or BRIEFS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    all_items = all_items or []

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
    {_section_header("All filings this run")}
    {_all_filings_table(all_items)}
    {_section_header("Run footer")}
    {_footer_block(stats)}
  </div>
</div>"""

    path = out_dir / _filename(brief_date)
    path.write_text(html, encoding="utf-8")
    return path
