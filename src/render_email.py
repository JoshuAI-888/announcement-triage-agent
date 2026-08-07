"""render_email.py — the Milford-themed HTML email brief (CONTRACTS.md §4).

Mirrors brief.py's four sections (ranked material, needs a look, all filings this
run, run footer) but renders a self-contained, inline-CSS HTML document suitable
for a Gmail draft: no external stylesheet, no @font-face (mail clients drop
both), only inline `style="..."` attributes built from `src.theme.THEME`.
Written to `out/briefs/<run_id>.email.html` for every run kind (digest,
intraday, backfill) — `run_id` is the UTC execution time to the second, so
reruns on the same day never clobber a previous brief.

Every guardrail flag and abstention is expanded to plain English via
`src.flags` before it reaches this module's output — a raw `G#_...` code or the
literal `insufficient_info` must never appear in the rendered HTML.

The 7/30/90-day price charts (Phase 3) are pre-rendered PNGs (`src.charts`)
hosted at a public URL (`assets_base_url`, e.g. the repo's raw.githubusercontent.com
path — Gmail proxies external images fine, and Gmail/most mail clients strip
inline `<svg>` and data-URI `<img>` is unreliable across clients) and embedded
as ordinary `<img src="https://...">` tags. When `assets_base_url` is unset, or
a given window's chart failed to render, that window falls back to the original
mail-safe `<table>`-of-bars sparkline (`_sparkline_html`) — never inline `<svg>`
either way.
"""

from __future__ import annotations

from collections import Counter
from datetime import date as date_cls
from datetime import datetime
from html import escape
from pathlib import Path

from src import charts
from src.enrich import Enrichment
from src.flags import KIND_LABEL, MATERIALITY_LABEL, doc_type_label, explain_flag, explain_flags
from src.rank import RankedItem
from src.theme import FONT_BODY, FONT_DISPLAY, THEME

ROOT = Path(__file__).resolve().parent.parent
BRIEFS_DIR = ROOT / "out" / "briefs"
ASSETS_DIR = BRIEFS_DIR / "assets"


def _filename(run_id: str) -> str:
    return f"{run_id}.email.html"


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


# Materiality -> frozen semantic color (CONTRACTS.md §5 — material=green,
# needs-more-info=warning, immaterial=muted). Used by the material card's header
# pill (_materiality_pill_style) and the summary tiles.
_MATERIALITY_COLOR: dict[str, str] = {
    "material": THEME["success"],
    "immaterial": THEME["muted"],
    "insufficient_info": THEME["warning"],
}


def _sparkline_html(series: list[float]) -> str:
    """Mail-safe sparkline: a `<table>` of bottom-aligned coloured `<div>` bars.

    NOT inline `<svg>` — Gmail and most mail clients strip it. The most recent
    bar (last in the chronological series) is highlighted orange. Works for any
    window length (7/30/90) — bar width narrows as the series grows so a
    90-point chart still fits a narrow column alongside its 7D/30D siblings.
    """
    if not series:
        return ""
    lo, hi = min(series), max(series)
    span = (hi - lo) or 1.0
    max_px = 26
    n = len(series)
    if n <= 10:
        bar_w, gap = 6, 1
    elif n <= 40:
        bar_w, gap = 3, 1
    else:
        bar_w, gap = 1, 0
    pad = f"0 {gap}px 0 0" if gap else "0"
    cells = []
    for i, v in enumerate(series):
        h = max(2, round((v - lo) / span * max_px))
        color = THEME["orange"] if i == n - 1 else THEME["blue"]
        cells.append(
            f'<td style="width:{bar_w}px; height:{max_px}px; vertical-align:bottom; padding:{pad};">'
            f'<div style="width:{bar_w}px; height:{h}px; background:{color}; border-radius:1px;"></div></td>'
        )
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'style="display:inline-table; border-collapse:collapse; vertical-align:middle;">'
        f'<tr>{"".join(cells)}</tr></table>'
    )


def _market_window_cell_html(
    label: str,
    series: list[float],
    window: dict | None,
    *,
    img_filename: str | None = None,
    assets_base_url: str = "",
    ticker: str = "",
) -> str:
    """One market-strip period cell: period label, chart, %change.

    Phase 3: when `assets_base_url` is set AND this window has a rendered PNG
    (`img_filename`, from `charts.render_price_charts`), the chart is a hosted
    `<img>` pointing at the repo's committed `out/briefs/assets/<file>.png`
    (served via `assets_base_url`, e.g. raw.githubusercontent.com). Otherwise
    (no `assets_base_url`, or this window's chart failed to render) it falls
    back to the original mail-safe `<table>`-of-bars sparkline.
    """
    if not series:
        return ""
    chg_pct = (window or {}).get("change_pct")
    chg_html = ""
    if chg_pct is not None:
        up = chg_pct >= 0
        color = THEME["green"] if up else THEME["danger"]
        sign = "+" if up else "&minus;"
        chg_html = (f'<div style="margin-top:2px; font-size:11px; font-weight:bold; '
                    f'color:{color};">{sign}{abs(chg_pct):.1f}%</div>')
    if assets_base_url and img_filename:
        src = f"{assets_base_url.rstrip('/')}/out/briefs/assets/{img_filename}"
        alt = escape(f"{ticker} {label} price".strip())
        chart_html = (f'<img src="{escape(src)}" width="130" height="42" alt="{alt}" '
                      f'style="display:block; margin:0 auto; border:0;" />')
    else:
        chart_html = _sparkline_html(series)
    return (
        f'<td style="text-align:center; vertical-align:bottom; padding:0 8px;">'
        f'<div style="font-size:10px; font-weight:bold; letter-spacing:.05em; text-transform:uppercase; '
        f'color:{THEME["muted"]};">{escape(label)}</div>'
        f'<div style="margin-top:2px;">{chart_html}</div>'
        f'{chg_html}'
        f'</td>'
    )


def _price_block_html(
    price: dict | None,
    *,
    ticker: str = "",
    run_id: str = "",
    assets_base_url: str = "",
    assets_dir: Path | None = None,
) -> str:
    """Market strip: last price + daily change + asof (left); 7/30/90-day
    charts with their own per-window %change (right). "" if no snapshot.

    When `assets_base_url` is truthy, renders the three window charts to PNG
    (`src.charts.render_price_charts`) and threads the resulting filenames into
    `_market_window_cell_html`, which decides per-window whether the hosted
    `<img>` or the bar-sparkline fallback is used.
    """
    if not price or price.get("last") is None:
        return ""
    change = price.get("change") or 0.0
    change_pct = price.get("change_pct") or 0.0
    up = change >= 0
    color = THEME["green"] if up else THEME["danger"]
    arrow = "&#9650;" if up else "&#9660;"  # ▲ / ▼
    asof = price.get("asof")
    asof_html = (f'<div style="margin-top:3px; font-size:10px; color:{THEME["muted"]};">as of {escape(asof)}</div>'
                 if asof else "")
    price_col = (
        f'<div style="font-size:20px; font-weight:bold; color:{THEME["slate"]};">'
        f'{price["last"]:.2f} <span style="font-size:11px; font-weight:bold; color:{THEME["muted"]};">'
        f'{escape(price.get("currency", "USD"))}</span></div>'
        f'<div style="margin-top:4px; font-size:12.5px; font-weight:bold; color:{color};">'
        f'{arrow} {abs(change):.2f} ({abs(change_pct):.2f}%)</div>'
        f'{asof_html}'
    )

    chart_map: dict[str, str] = {}
    if assets_base_url:
        chart_map = charts.render_price_charts(ticker, price, run_id, assets_dir or ASSETS_DIR)

    windows = (
        ("7D", price.get("series7") or [], price.get("window_7d")),
        ("30D", price.get("series30") or [], price.get("window_30d")),
        ("90D", price.get("series90") or [], price.get("window_90d")),
    )
    chart_cells = "".join(
        _market_window_cell_html(lbl, series, win, img_filename=chart_map.get(lbl),
                                 assets_base_url=assets_base_url, ticker=ticker)
        for lbl, series, win in windows if series
    )
    charts_html = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
        f'<tr>{chart_cells}</tr></table>'
        if chart_cells else ""
    )

    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" '
        f'style="border-collapse:collapse; margin:10px 0 0 0;"><tr>'
        f'<td style="vertical-align:bottom; padding:8px 12px 8px 0; border-top:1px solid {THEME["cloud"]}; '
        f'border-bottom:1px solid {THEME["cloud"]};">{price_col}</td>'
        f'<td style="vertical-align:bottom; text-align:right; padding:8px 0; border-top:1px solid {THEME["cloud"]}; '
        f'border-bottom:1px solid {THEME["cloud"]};">{charts_html}</td>'
        f'</tr></table>'
    )


def _company_block_html(ann, company: dict | None) -> str:
    """AI business/edge blurb + its caveat footnote. "" if nothing to show.

    Industry now renders in the card's identity header (`_card_header_html`)
    alongside ticker/company name, so this block carries only the AI-generated
    company context.
    """
    if not company:
        return ""
    text = " ".join(t for t in ((company.get("business") or "").strip(), (company.get("edge") or "").strip()) if t)
    if not text:
        return ""
    parts = [f'<p style="margin:8px 0 0 0; font-size:12px; color:{THEME["slate_2"]};">{escape(text)}</p>']
    caveat = (company.get("caveat") or "").strip()
    if caveat:
        parts.append(
            f'<p style="margin:2px 0 0 0; font-size:10px; color:{THEME["muted"]}; font-style:italic;">'
            f'{escape(caveat)}</p>'
        )
    return "".join(parts)


def _materiality_pill_style(materiality: str) -> str:
    """The header's rounded MATERIAL chip — frozen color contract (material=green)."""
    color = _MATERIALITY_COLOR.get(materiality, THEME["muted"])
    return (f'display:inline-block; padding:3px 9px; border-radius:999px; font-size:10.5px; '
            f'font-weight:bold; letter-spacing:.03em; white-space:nowrap; background:{color}; color:#ffffff;')


def _form_badge_text(ann) -> str:
    """"{native form} · {friendly label}", e.g. "8-K · Material event report".

    Built from `_native_form(ann)` + `doc_type_label`; the trailing "(<form>)"
    that `doc_type_label` appends is stripped since the native form is already
    the badge's prefix (avoids "8-K · Material event report (8-K)").
    """
    native = _native_form(ann)
    label = doc_type_label(ann.doc_type, native)
    suffix = f" ({native})"
    if label.upper().endswith(suffix.upper()):
        label = label[: -len(suffix)]
    return f"{native} · {label}" if label else native


def _form_badge_style() -> str:
    """A light-blue-tinted pill, distinct from the green materiality chip and
    never reusing orange (brand-action-only, per the frozen color contract).
    The tint is derived from THEME["blue"] at render time rather than a new
    invented hex, so the theme stays the single source of truth for hues.
    """
    blue = str(THEME["blue"])
    r, g, b = int(blue[1:3], 16), int(blue[3:5], 16), int(blue[5:7], 16)
    return (f'display:inline-block; padding:3px 9px; border-radius:999px; font-size:10.5px; '
            f'font-weight:bold; letter-spacing:.03em; white-space:nowrap; '
            f'background:rgba({r}, {g}, {b}, 0.12); color:{blue}; '
            f'border:1px solid rgba({r}, {g}, {b}, 0.35);')


def _filed_time_text(ann) -> str:
    """Plain "Filed HH:MM UTC" from `published_at` — simple and robust, no
    timezone conversion (`published_at` is stored UTC per SPEC.md §5.1)."""
    return f"Filed {ann.published_at.strftime('%H:%M')} UTC"


def _card_header_html(ann, rank: int, materiality: str) -> str:
    """Identity header row: ticker (large) / company / industry on the left;
    the MATERIAL chip, native form-type badge, and "Filed HH:MM · #rank" on
    the right, stacked."""
    ticker = escape(ann.ticker)
    company = escape(ann.company_name)
    industry_html = (
        f'<p style="margin:2px 0 0 0; font-size:11px; color:{THEME["muted"]}; '
        f'text-transform:uppercase; letter-spacing:.04em;">{escape(ann.industry)}</p>'
        if ann.industry else ""
    )
    identity_html = (
        f'<p style="margin:0; font-family:{FONT_DISPLAY}; font-size:20px; font-weight:bold; '
        f'color:{THEME["slate"]}; line-height:1.1;">{ticker}</p>'
        f'<p style="margin:3px 0 0 0; font-size:12.5px; color:{THEME["slate_2"]}; font-weight:bold;">{company}</p>'
        f'{industry_html}'
    )

    mat_label = escape(MATERIALITY_LABEL.get(materiality, materiality).upper())
    mat_chip = f'<span style="{_materiality_pill_style(materiality)}">{mat_label}</span>'
    form_chip = f'<span style="{_form_badge_style()}">{escape(_form_badge_text(ann))}</span>'
    time_html = (f'<span style="font-size:10.5px; color:{THEME["muted"]};">'
                 f'{escape(_filed_time_text(ann))} &middot; #{rank}</span>')
    badges_html = (
        f'<p style="margin:0 0 6px 0; text-align:right;">{mat_chip}</p>'
        f'<p style="margin:0 0 6px 0; text-align:right;">{form_chip}</p>'
        f'<p style="margin:0; text-align:right;">{time_html}</p>'
    )

    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;">'
        f'<tr>'
        f'<td style="vertical-align:top;">{identity_html}</td>'
        f'<td style="vertical-align:top; text-align:right; white-space:nowrap; padding-left:10px;">{badges_html}</td>'
        f'</tr></table>'
    )


def _analysis_body_html(c) -> str:
    """"Why it matters" (rationale) then "Evidence" (the verbatim pull-quote)."""
    return (
        f'<p style="margin:10px 0 3px 0; font-size:10px; font-weight:bold; letter-spacing:.06em; '
        f'text-transform:uppercase; color:{THEME["muted"]};">Why it matters</p>'
        f'<p style="margin:0 0 10px 0; font-size:13.5px; color:{THEME["slate"]}; line-height:1.5;">'
        f'{escape(c.rationale)}</p>'
        f'<p style="margin:0 0 3px 0; font-size:10px; font-weight:bold; letter-spacing:.06em; '
        f'text-transform:uppercase; color:{THEME["muted"]};">Evidence</p>'
        f'<p style="margin:0; padding:9px 12px; background:{THEME["cloud"]}; '
        f'border-left:3px solid {THEME["orange"]}; font-size:12.5px; color:{THEME["slate_2"]}; '
        f'font-style:italic;">&ldquo;{escape(c.evidence_quote)}&rdquo;</p>'
    )


def _action_footer_html(filing_url: str, news_html: str, score: float) -> str:
    """Quiet footer row: Filing link (orange) · news link (blue), score on the right."""
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" '
        f'style="border-collapse:collapse; margin-top:10px; padding-top:8px; border-top:1px solid {THEME["cloud"]};">'
        f'<tr>'
        f'<td style="font-size:12px;">'
        f'<a href="{escape(filing_url)}" style="color:{THEME["orange"]}; text-decoration:none; '
        f'font-weight:bold;">Filing</a>{news_html}</td>'
        f'<td style="text-align:right; font-size:10.5px; color:{THEME["muted"]};">score '
        f'<strong style="color:{THEME["slate_2"]};">{score:.3f}</strong></td>'
        f'</tr></table>'
    )


def _material_block(
    items: list[RankedItem],
    enrichment_by_id: dict[str, Enrichment],
    *,
    run_id: str = "",
    assets_base_url: str = "",
    assets_dir: Path | None = None,
) -> str:
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
        market_html = _price_block_html(enr.price if enr else None, ticker=ann.ticker, run_id=run_id,
                                        assets_base_url=assets_base_url, assets_dir=assets_dir)
        rows.append(_card(
            _card_header_html(ann, i, c.materiality)
            + f'<p style="margin:8px 0 0 0; font-size:13px; color:{THEME["slate_2"]};">{escape(ann.headline)}</p>'
            + market_html
            + company_html
            + _analysis_body_html(c)
            + _action_footer_html(filing_url, news_html, it.score)
        ))
    return "".join(rows)


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


def _heading_suffix(kind: str, window: dict | None) -> str:
    kind_label = KIND_LABEL.get(kind, kind)
    suffix = f" &mdash; {escape(kind_label)}"
    if kind == "backfill" and window and window.get("since"):
        since_d = str(window["since"])[:10]
        until_d = (str(window.get("until") or "") or "")[:10] or "now"
        suffix += f" (window: {escape(since_d)} to {escape(until_d)})"
    return suffix


def _immaterial_count(ranked: list, needs_look: list, all_items: list) -> int:
    """Immaterial-and-clean = everything classified this run minus the two shown tiers.

    rank() puts material items in `ranked` and flagged/abstained items in `needs_look`;
    the remainder of `all_items` (immaterial with no guardrail flag) is what neither tier
    shows. Never negative.
    """
    return max(0, len(all_items) - len(ranked) - len(needs_look))


def _tile_html(count: int, label: str, color: str, total: int) -> str:
    pct = f"{(100 * count / total):.0f}%" if total else "0%"
    return (
        f'<td style="width:33%; padding:0 6px; vertical-align:top;">'
        f'<div style="border:1px solid #dce2e4; border-top:3px solid {color}; '
        f'border-radius:{THEME["radius_control"]}px; padding:12px 14px; background:{THEME["paper"]};">'
        f'<div style="font-size:26px; font-weight:bold; color:{THEME["slate"]}; line-height:1;">{count}</div>'
        f'<div style="font-size:11px; color:{THEME["muted"]}; text-transform:uppercase; '
        f'letter-spacing:.06em; margin-top:6px;">{escape(label)}</div>'
        f'<div style="font-size:11px; color:{color}; font-weight:bold; margin-top:2px;">{pct} of run</div>'
        f'</div></td>'
    )


def _needs_reason_counts(needs_look: list) -> Counter:
    """Plain-English reason label -> count across the needs-a-look tier.

    A guardrail-flagged item contributes each of its flags' labels; a bare abstention
    (no flags, insufficient_info) contributes the insufficient_info label. This is the
    same partition rank() uses for the needs-a-look tier, always expanded to plain
    English (never a raw G#_ code or the literal "insufficient_info").
    """
    reason: Counter = Counter()
    for it in needs_look:
        flags = it.classification.guardrail_flags
        if flags:
            for f in explain_flags(flags):
                reason[f["label"]] += 1
        else:
            reason[explain_flag("insufficient_info")["label"]] += 1
    return reason


def _summary_tiles_block(ranked: list, needs_look: list, all_items: list) -> str:
    """Three tier tiles (material / needs a look / immaterial) + a needs-reason breakdown.

    This is the at-a-glance summary that replaces the long inline needs-a-look and
    all-filings lists in the email (those move to the portal). Always visible; the
    counts are the authoritative run tiers, so "Material 23" here matches the material
    cards below exactly.
    """
    n_mat, n_needs = len(ranked), len(needs_look)
    n_imm = _immaterial_count(ranked, needs_look, all_items)
    total = n_mat + n_needs + n_imm

    tiles = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'style="width:100%; border-collapse:separate; border-spacing:0; margin:0 0 14px 0;"><tr>'
        f'{_tile_html(n_mat, "Material", THEME["success"], total)}'
        f'{_tile_html(n_needs, "Needs a look", THEME["warning"], total)}'
        f'{_tile_html(n_imm, "Immaterial", THEME["muted"], total)}'
        f'</tr></table>'
    )

    reason = _needs_reason_counts(needs_look)
    if reason:
        rows = "".join(
            f'<tr><td style="padding:3px 0; font-size:12px; color:{THEME["slate_2"]};">{escape(lbl)}</td>'
            f'<td style="padding:3px 0; font-size:12px; color:{THEME["slate"]}; font-weight:bold; '
            f'text-align:right;">{n} '
            f'<span style="color:{THEME["muted"]}; font-weight:normal;">'
            f'({(100 * n / n_needs):.0f}%)</span></td></tr>'
            for lbl, n in reason.most_common()
        )
        breakdown = (
            f'<div style="border:1px solid #f0d7bf; background:#fff8f1; '
            f'border-radius:{THEME["radius_control"]}px; padding:12px 14px; margin:0 0 8px 0;">'
            f'<div style="font-size:12px; font-weight:bold; color:{THEME["orange"]}; '
            f'text-transform:uppercase; letter-spacing:.05em; margin-bottom:6px;">'
            f'Why {n_needs} need a look</div>'
            f'<table role="presentation" style="width:100%; border-collapse:collapse;">{rows}</table>'
            f'</div>'
        )
    else:
        breakdown = ""
    return tiles + breakdown


def _portal_pointer(ranked: list, needs_look: list, all_items: list, portal_url: str) -> str:
    """Closing pointer to the portal for the full needs-a-look + immaterial detail.

    The email carries the material cards in full and summarises the rest; the browsable,
    sortable, searchable lists live on the portal. When `portal_url` is set the counts
    link to /filings; otherwise the same text renders unlinked (still informative).
    """
    n_needs = len(needs_look)
    n_imm = _immaterial_count(ranked, needs_look, all_items)
    base = portal_url.rstrip("/")
    if base:
        target = f'<a href="{escape(base)}/filings" style="color:{THEME["orange"]}; ' \
                 f'text-decoration:none; font-weight:bold;">the portal &#8599;</a>'
    else:
        target = "the portal"
    return _card(
        f'<p style="margin:0; font-size:13px; color:{THEME["slate_2"]};">'
        f'<strong>{n_needs}</strong> filings need a look and <strong>{n_imm}</strong> were '
        f'immaterial. Every filing this run &mdash; material, needs-a-look and immaterial &mdash; '
        f'is browsable, sortable and searchable on {target}.</p>',
        extra=f"background:{THEME['cloud']};",
    )


def _portal_top_link(portal_url: str) -> str:
    """A header link to the portal dashboard. Empty when `portal_url` is unset, so the
    email never carries a dead link; when set it points at the portal root."""
    base = portal_url.rstrip("/")
    if not base:
        return ""
    return (
        f'<p style="margin:0 0 16px 0;">'
        f'<a href="{escape(base)}" style="display:inline-block; color:{THEME["orange"]}; '
        f'text-decoration:none; font-weight:bold; font-size:12px;">'
        f'Open the portal dashboard &#8599;</a></p>'
    )


def render_email(
    ranked: list[RankedItem],
    needs_look: list[RankedItem],
    stats: dict,
    enrichment: list[Enrichment],
    all_items: list[RankedItem] | None = None,
    brief_date: date_cls | datetime | None = None,
    *,
    run_id: str,
    kind: str = "digest",
    window: dict | None = None,
    out_dir: Path | None = None,
    assets_base_url: str = "",
    assets_dir: Path | None = None,
    portal_url: str = "",
) -> Path:
    """Render the self-contained, Milford-themed HTML email brief and write it to disk.

    Mirrors brief.py's four sections (material — ranked, needs a look, all
    filings this run, run footer). Every color is inlined via `src.theme.THEME`;
    fonts fall back to web-safe stacks. Written to `out/briefs/<run_id>.email.html`
    for EVERY run kind (digest/intraday/backfill) — `run_id` is the UTC execution
    time to the second (see `src.run.compute_run_id`), so reruns never clobber
    each other. `kind` drives the heading label (KIND_LABEL — "Daily digest" /
    "Intraday" / "Backfill"); a backfill's heading also shows the covered window.

    `all_items` is every classified filing this run (material + immaterial +
    needs-a-look) — it drives the "All filings this run" table. Defaults to
    empty when the caller has nothing to pass (e.g. a check exercising only
    the material/needs-look sections).

    `assets_base_url` (Phase 3) — when truthy, each MATERIAL item's 7D/30D/90D
    market-strip charts are rendered to PNG (`src.charts`) into `assets_dir`
    (default `out/briefs/assets/`) and embedded as hosted `<img>` tags pointing
    at `{assets_base_url}/out/briefs/assets/<file>.png` (e.g. this repo's
    raw.githubusercontent.com path — see CONTRACTS.md §4). When falsy, or when
    a given window's PNG failed to render, that window falls back to the
    original mail-safe bar-table sparkline. Never affects anything else in the
    brief.
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
letter-spacing:.08em; text-transform:uppercase;">Milford &middot; SEC Announcement Triage</p>
    <h1 style="font-family:{FONT_DISPLAY}; color:{THEME['slate']}; font-size:24px; margin:0 0 16px 0;">\
SEC announcement brief{_heading_suffix(kind, window)} &mdash; {escape(_display_date(brief_date))}</h1>
    {_portal_top_link(portal_url)}
    {_summary_tiles_block(ranked, needs_look, all_items)}
    {_section_header("Material — ranked")}
    {_material_block(ranked, enrichment_by_id, run_id=run_id, assets_base_url=assets_base_url, assets_dir=assets_dir)}
    {_section_header("Needs a look & immaterial")}
    {_portal_pointer(ranked, needs_look, all_items, portal_url)}
    {_section_header("Run footer")}
    {_footer_block(stats)}
  </div>
</div>"""

    path = out_dir / _filename(run_id)
    path.write_text(html, encoding="utf-8")
    return path
