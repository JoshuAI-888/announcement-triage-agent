"""theme.py — Milford brand tokens for the Python renderers (CONTRACTS.md §5).

Single source for hex values and radii so `render_email.py` (and any future
Python renderer) never hard-codes a color. Values are copied verbatim from
`milford-core-portal-design/references/brand-language.md` (authoritative) and
mirror `assets/theme/theme.css` — do not adjust one without the other.

Email clients strip `<style>` blocks and ignore `@font-face`, so `render_email.py`
must inline every color as a `style="..."` attribute and fall back to web-safe
font stacks (Georgia/serif for display, Arial/Helvetica for body) — see
`FONT_DISPLAY` / `FONT_BODY` and `inline_style()` below.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THEME_CSS_PATH = ROOT / "assets" / "theme" / "theme.css"

# CONTRACTS.md §5 — exact hexes, do not invent or adjust.
THEME: dict[str, object] = {
    "slate": "#303c42",       # nav, headings, primary text
    "slate_2": "#46545b",     # hover / secondary dark
    "muted": "#77858d",       # metadata, labels
    "cloud": "#eef1f2",       # section / control background
    "paper": "#ffffff",       # cards, tables
    "orange": "#e1690e",      # primary action, focus, master-brand emphasis
    "blue": "#1c99d6",        # data cue (KiwiSaver accent)
    "green": "#4bc864",       # data cue (Funds accent)
    "purple": "#915fb4",      # data cue (Wealth accent)
    "success": "#198754",
    "warning": "#f3a83b",     # use for the eval-stale banner
    "danger": "#c94b42",      # guardrail flags
    "radius_control": 4,      # px — inputs, buttons
    "radius_card": 8,         # px — cards
    "radius_surface": 14,     # px — large contained surfaces
}

# Web-safe fallback stacks — mail clients drop @font-face (CONTRACTS §5).
FONT_DISPLAY = "Georgia, 'Times New Roman', serif"
FONT_BODY = "Arial, Helvetica, sans-serif"


def read_css() -> str:
    """Return the shared `assets/theme/theme.css` token file verbatim."""
    return THEME_CSS_PATH.read_text(encoding="utf-8")


def inline_style(**props: object) -> str:
    """Build an inline `style="..."` value from CSS property=value kwargs.

    Kwargs use underscores in place of hyphens (Python identifiers cannot
    contain hyphens), e.g. `inline_style(font_family=FONT_BODY, color=THEME["slate"])`
    -> `"font-family:Arial, Helvetica, sans-serif; color:#303c42"`. `None` values
    are dropped so callers can pass optional properties without branching.
    """
    parts = [f"{k.replace('_', '-')}:{v}" for k, v in props.items() if v is not None]
    return "; ".join(parts)
