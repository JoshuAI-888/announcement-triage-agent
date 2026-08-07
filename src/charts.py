"""charts.py — pre-rendered PNG line-chart sparklines (Phase 3, CONTRACTS.md §4).

Gmail (and most mail clients) strip inline `<svg>`, and a data-URI `<img
src="data:...">` is unreliable across clients/proxies, so the 7D/30D/90D
market-strip charts are rendered to real PNG files on disk and referenced by
the email as hosted `<img src="https://.../out/briefs/assets/...">` URLs (see
`src.render_email`'s `assets_base_url` param). This module owns ONLY the
rendering — writing the file and building the public URL is the caller's job.

Best-effort, same spirit as `src.market`: any failure (bad series, matplotlib
error, unwritable path) degrades to `None`/an empty dict rather than breaking
a run — a chart is a nice-to-have, never something a brief's delivery should
depend on.

Uses the Agg backend explicitly (`matplotlib.use("Agg")`) so this module never
needs a display, which matters in CI (headless Ubuntu runner) and any other
non-interactive environment.
"""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (must follow matplotlib.use)

# Style constants — equity-research sparkline, Koyfin-like. Logical size
# ~260x84 px at 2x dpi so the PNG stays crisp on retina displays without
# ballooning file size.
_FIGSIZE = (2.6, 0.84)
_DPI = 200
_GREEN = "#198754"   # THEME["success"]
_RED = "#c94b42"     # THEME["danger"]
_BASELINE_GREY = "#c9d0d3"

_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9]+")

# (label, price-dict series key, price-dict window key)
_WINDOWS = (("7D", "series7", "window_7d"), ("30D", "series30", "window_30d"),
            ("90D", "series90", "window_90d"))


def _safe_ticker(ticker: str) -> str:
    return _SAFE_CHARS_RE.sub("_", ticker or "")


def render_window_chart(series: list[float], up: bool, out_path: Path) -> Path | None:
    """Render one mini line-chart PNG for a single price-window series.

    Green (`up=True`) or red (`up=False`) 2px line, a subtle filled area
    under it, a dashed light-grey baseline at the series' first value, and a
    filled dot on the most recent (last) point. No axes/ticks/frame/labels —
    a pure sparkline. Returns `out_path` on success, `None` on any failure
    (including a series with fewer than 2 points) — NEVER raises.
    """
    if not series or len(series) < 2:
        return None
    try:
        color = _GREEN if up else _RED
        xs = list(range(len(series)))

        fig = plt.figure(figsize=_FIGSIZE, dpi=_DPI)
        ax = fig.add_axes([0, 0, 1, 1])  # fill the whole canvas, no margins

        ax.axhline(series[0], color=_BASELINE_GREY, linewidth=1, linestyle=(0, (3, 2)), zorder=1)
        ax.plot(xs, series, color=color, linewidth=2, zorder=3, solid_capstyle="round")
        ax.fill_between(xs, series, series[0], color=color, alpha=0.12, zorder=2)
        ax.scatter([xs[-1]], [series[-1]], s=16, color=color, zorder=4)

        ax.axis("off")
        pad = (max(series) - min(series)) * 0.15 or 1.0
        ax.set_ylim(min(series) - pad, max(series) + pad)
        ax.set_xlim(-0.5, len(series) - 0.5)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=_DPI, facecolor="white", edgecolor="none",
                    bbox_inches="tight", pad_inches=0)
        plt.close(fig)
        return out_path
    except Exception:
        try:
            plt.close("all")
        except Exception:
            pass
        return None


def render_price_charts(ticker: str, price: dict, run_id: str, assets_dir: Path) -> dict[str, str]:
    """Render the 7D/30D/90D charts for one ticker's price dict.

    Writes `assets_dir/<run_id>-<safe_ticker>-<window>.png` for each window
    that has a usable series (>= 2 points) and renders successfully. Returns
    `{"7D": filename, "30D": filename, "90D": filename}` for exactly the
    windows that succeeded — a window with too short a series, a missing/None
    price dict, or a render failure is simply omitted (never raises).
    """
    out: dict[str, str] = {}
    if not price:
        return out
    try:
        assets_dir.mkdir(parents=True, exist_ok=True)
        safe = _safe_ticker(ticker)
        for label, series_key, window_key in _WINDOWS:
            series = price.get(series_key) or []
            if len(series) < 2:
                continue
            window = price.get(window_key) or {}
            up = (window.get("change") or 0.0) >= 0
            filename = f"{run_id}-{safe}-{label}.png"
            result = render_window_chart(series, up, assets_dir / filename)
            if result is not None:
                out[label] = filename
    except Exception:
        return out
    return out
