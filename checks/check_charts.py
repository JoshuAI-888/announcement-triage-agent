"""check_charts.py — pre-rendered PNG line-chart sparklines (Phase 3, CONTRACTS.md §4).

Offline: matplotlib's Agg backend renders to a tempdir, no display, no network.
Covers `render_window_chart` (a real PNG file with the right magic bytes, and
graceful `None` on a too-short series or garbage input) and
`render_price_charts` (the expected 7D/30D/90D window keys for a full price
dict, files actually written to `assets_dir`, and graceful degradation — never
raises — on an empty/garbage price dict).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from checks._harness import run
from src import charts

_PNG_MAGIC = b"\x89PNG"

_PRICE = {
    "last": 245.67, "prev_close": 240.10, "change": 5.57, "change_pct": 2.32,
    "currency": "USD",
    "series7": [230.0, 232.5, 238.0, 236.0, 241.0, 240.10, 245.67],
    "series30": [200.0 + i * 1.5 for i in range(30)],
    "series90": [180.0 + i * 0.8 for i in range(90)],
    "window_7d": {"change": 15.67, "change_pct": 6.82},
    "window_30d": {"change": 45.67, "change_pct": 22.85},
    "window_90d": {"change": -3.5, "change_pct": -1.4},  # a down window too
    "asof": "2026-07-14",
}


def body(check):
    tmp = Path(tempfile.mkdtemp(prefix="charts_"))

    # --- render_window_chart: a real PNG file, right magic bytes ---
    out_path = tmp / "up.png"
    result = charts.render_window_chart([100.0, 101.0, 103.0, 102.5, 105.0], up=True, out_path=out_path)
    check.equal(result, out_path, "render_window_chart returns the out_path on success")
    check.require(out_path.exists(), "the PNG file was actually written")
    with open(out_path, "rb") as fh:
        magic = fh.read(4)
    check.equal(magic, _PNG_MAGIC, "the written file starts with the PNG magic bytes")
    check.require(out_path.stat().st_size > 0, "the PNG file is non-empty")

    down_path = tmp / "down.png"
    down_result = charts.render_window_chart([105.0, 104.0, 101.0, 99.0], up=False, out_path=down_path)
    check.equal(down_result, down_path, "a down-series also renders successfully")
    with open(down_path, "rb") as fh:
        check.equal(fh.read(4), _PNG_MAGIC, "the down-series PNG also starts with the PNG magic bytes")

    # --- < 2 points -> None, never raises ---
    check.equal(charts.render_window_chart([], up=True, out_path=tmp / "empty.png"), None,
               "an empty series returns None")
    check.equal(charts.render_window_chart([1.0], up=True, out_path=tmp / "one.png"), None,
               "a single-point series returns None (need >= 2 points)")
    check.require(not (tmp / "empty.png").exists(), "no file is written for an empty series")
    check.require(not (tmp / "one.png").exists(), "no file is written for a single-point series")

    # --- garbage input -> None, never raises ---
    check.equal(charts.render_window_chart(None, up=True, out_path=tmp / "garbage1.png"), None,
               "a None series returns None instead of raising")
    check.equal(charts.render_window_chart(["a", "b", "c"], up=True, out_path=tmp / "garbage2.png"), None,
               "a non-numeric series returns None instead of raising")
    check.equal(charts.render_window_chart([1.0, 2.0], up=True, out_path=Path("/nonexistent-root-x9z/y.png")),
               None, "an unwritable out_path degrades to None instead of raising")

    # --- render_price_charts: full price dict -> all three window keys, files written ---
    assets_dir = tmp / "assets"
    chart_map = charts.render_price_charts("AAPL", _PRICE, "2026-07-14T00-00-00", assets_dir)
    check.equal(set(chart_map.keys()), {"7D", "30D", "90D"}, "all three window keys are present for a full price dict")
    for label, filename in chart_map.items():
        path = assets_dir / filename
        check.require(path.exists(), f"{label} chart file was written to assets_dir")
        with open(path, "rb") as fh:
            check.equal(fh.read(4), _PNG_MAGIC, f"{label} chart file starts with the PNG magic bytes")
    check.require(chart_map["7D"].startswith("2026-07-14T00-00-00-AAPL-7D"),
                 "filename is <run_id>-<safe_ticker>-<window>.png")

    # --- ticker sanitisation: non-alnum chars become underscores ---
    chart_map2 = charts.render_price_charts("BRK.B", _PRICE, "run123", assets_dir)
    check.require(any(f.startswith("run123-BRK_B-") for f in chart_map2.values()),
                 "ticker with a dot is sanitised to underscore in the filename")

    # --- assets_dir created if missing ---
    fresh_dir = tmp / "brand_new" / "nested"
    check.require(not fresh_dir.exists(), "the nested assets_dir does not exist yet")
    chart_map3 = charts.render_price_charts("MSFT", _PRICE, "run456", fresh_dir)
    check.require(fresh_dir.exists(), "render_price_charts creates assets_dir if missing")
    check.equal(set(chart_map3.keys()), {"7D", "30D", "90D"}, "all three windows render into the freshly created dir")

    # --- a too-short series for one window is simply omitted, others still render ---
    partial_price = dict(_PRICE)
    partial_price["series90"] = [100.0]  # too short
    chart_map4 = charts.render_price_charts("NVDA", partial_price, "run789", assets_dir)
    check.equal(set(chart_map4.keys()), {"7D", "30D"}, "a too-short window series is omitted, others still render")

    # --- empty/None/garbage price dict -> {} , never raises ---
    check.equal(charts.render_price_charts("ZZZ", {}, "runX", assets_dir), {}, "an empty price dict returns {}")
    check.equal(charts.render_price_charts("ZZZ", None, "runX", assets_dir), {}, "a None price dict returns {}")
    check.equal(charts.render_price_charts("ZZZ", {"series7": "not-a-list"}, "runX", assets_dir), {},
               "a garbage series value degrades to {} instead of raising")
    check.equal(charts.render_price_charts("ZZZ", {"junk_key": 123}, "runX", assets_dir), {},
               "a price dict with none of the expected keys returns {}")

    check.note("offline check — matplotlib Agg backend, no network, no display")


if __name__ == "__main__":
    run("pre-rendered PNG line-chart sparklines (src/charts.py, CONTRACTS §4)", body)
