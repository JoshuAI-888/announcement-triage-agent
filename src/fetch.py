"""fetch.py — poll the reference exchange adapter, dedupe, persist raw payloads.

Increment 2 (SPEC.md §14). Responsibilities, in order:
  1. build the configured adapter and poll for filings published after the watermark
  2. compute the idempotent announcement_id (SPEC.md §5.1) and dedupe against state.db
  3. write one raw JSON per NEW announcement to data/raw/
  4. advance the watermark ONLY after a full successful run (SPEC.md §12)

A ticker whose fetch fails after the adapter's retries is dead-lettered and the
run continues; but any such failure withholds the watermark advance so the next
run retries it.

Run:  python -m src.fetch
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

import yaml

from src.adapters import load_doc_type_map
from src.adapters.edgar import EdgarAdapter
from src.models import Announcement
from src.store import Store, parse_iso

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "state.db"

# Reference adapters available in this build. Increment 2 ships EDGAR only.
ADAPTERS = {"EDGAR": EdgarAdapter}


class FetchResult(NamedTuple):
    """Outcome of one fetch pass. `seen` = new + duplicate."""

    new: int
    duplicate: int
    seen: int
    watermark_advanced: bool
    new_ids: tuple[str, ...] = ()  # announcement_ids written this pass (for incremental normalise)


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def build_adapter(config: dict):
    """A fully configured reference adapter: credentials-free HTTP, doc_type map, truncation.

    OCR is pinned to Claude regardless of run.provider (see EdgarAdapter._claude_ocr),
    so it always gets the "claude" provider's own pricing + fx for cost accounting —
    never the pricing of whichever provider is configured to run the daily classifier.
    """
    ref = config["exchange"]["reference"]
    if ref not in ADAPTERS:
        raise ValueError(f"no adapter implemented for exchange {ref!r} (this build ships EDGAR only)")
    ex = config["exchange"]
    claude_pricing = ((config.get("providers", {}) or {}).get("claude", {}) or {}).get("pricing")
    return ADAPTERS[ref](
        watchlist=config["watchlist"],
        user_agent=ex["user_agent"],
        timeout_seconds=ex["request_timeout_seconds"],
        rate_limit_rps=ex["rate_limit_requests_per_second"],
        doc_type_map=load_doc_type_map(ref),
        truncate_chars=config["thresholds"]["truncate_input_chars"],
        ocr_enabled=config.get("_runtime", {}).get("pdf_ocr_enabled", True),
        pdf_log_path=ROOT / "out" / "pdf_log.jsonl",
        ocr_pricing_usd_per_mtok=claude_pricing,
        fx_usd_nzd=config.get("fx_usd_nzd"),
    )


def fetch(
    config: dict | None = None,
    db_path: str | Path | None = None,
    raw_dir: str | Path | None = None,
) -> FetchResult:
    """Run one incremental fetch pass. Returns the new / duplicate / seen counts.

    `db_path` and `raw_dir` default to the build's own state.db and data/raw;
    they are overridable so a check can exercise a fetch from a clean slate.
    """
    config = config or load_config()
    raw_dir = Path(raw_dir) if raw_dir is not None else RAW_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    exchange = config["exchange"]["reference"]
    adapter = build_adapter(config)
    store = Store(db_path if db_path is not None else DB_PATH)
    try:
        since = store.get_watermark(exchange)
        if since is None:
            lookback = config["exchange"]["bootstrap_lookback_days"]
            since = datetime.now(timezone.utc) - timedelta(days=lookback)
            print(
                f"No watermark for {exchange}; bootstrapping from "
                f"{since.isoformat()} ({lookback}d lookback)."
            )
        else:
            print(f"Watermark for {exchange}: {since.isoformat()}")

        new_count = 0
        dup_count = 0
        seen = 0
        had_failure = False
        max_published = since
        new_ids: list[str] = []

        for ticker in config["watchlist"]:
            try:
                raw_records = adapter.fetch_ticker(ticker, since)
            except Exception as exc:  # dead-letter boundary (SPEC.md §12) — run continues
                store.add_dead_letter(
                    error=f"fetch failed for {ticker}: {exc}",
                    raw_payload={"ticker": ticker, "since": since.isoformat()},
                )
                print(f"WARNING: {ticker} failed after retries; dead-lettered, continuing. ({exc})")
                had_failure = True
                continue

            for raw in raw_records:
                seen += 1
                published_at = parse_iso(raw["published_at"])
                if published_at > max_published:
                    max_published = published_at
                announcement_id = Announcement.compute_id(
                    raw["exchange"],
                    raw["ticker"],
                    published_at,
                    raw["headline"],
                    raw["accession_number"],
                )
                if store.is_processed(announcement_id):
                    dup_count += 1
                    continue
                raw_out = dict(raw)
                raw_out["announcement_id"] = announcement_id
                raw_out["fetched_at"] = datetime.now(timezone.utc).isoformat()
                (raw_dir / f"{announcement_id}.json").write_text(
                    json.dumps(raw_out, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                store.mark_processed(announcement_id, raw["exchange"], raw["ticker"], published_at)
                new_ids.append(announcement_id)
                new_count += 1

        print(
            f"Saw {seen} filing(s) after the watermark: "
            f"{new_count} new, {dup_count} already processed."
        )

        # Advance the watermark ONLY after a full successful run (SPEC.md §12).
        if had_failure:
            print(
                "Watermark NOT advanced: one or more tickers failed "
                "(advance only after a full successful run)."
            )
        else:
            store.set_watermark(exchange, max_published)
            print(f"Watermark advanced to {max_published.isoformat()}.")

        return FetchResult(
            new=new_count,
            duplicate=dup_count,
            seen=seen,
            watermark_advanced=not had_failure,
            new_ids=tuple(new_ids),
        )
    finally:
        store.close()


def main() -> None:
    fetch()


if __name__ == "__main__":
    main()
