"""normalise.py — raw payloads in data/raw/ -> canonical Announcement records.

Increment 3 (SPEC.md §14). The per-source knowledge lives in the adapter; this
module only decides *which* raw payloads to normalise, and enforces that a
failure is loud rather than silent.

Selection matters and is deliberately dull. A 30-day EDGAR window over 20 large
caps is ~3000 filings, 84% of them structured-note pricing supplements from two
issuers. Normalising all of them would cost thousands of requests and would
hand the owner a labelling queue that is mostly one form type from one desk.
`select_raw_payloads` therefore takes the most recent filings **round-robin
across native form types**, so every form the corpus contains is represented
and no single issuer's filing volume dominates.

That rule is about coverage, not importance. It makes no judgement about
whether a filing is material — that is the model's job, scored against the
owner's gold set.

Run:  python -m src.normalise
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from src.fetch import ROOT, RAW_DIR, build_adapter, load_config, parse_iso
from src.models import Announcement


def compute_announcement_id(raw: dict) -> str:
    """The SPEC §5.1 hash for a raw payload, without normalising it first.

    Raw payloads carry `announcement_id` once fetch has written them, but it is
    recomputed here rather than trusted so a hand-edited file cannot smuggle in
    a mismatched id.
    """
    return Announcement.compute_id(
        raw["exchange"],
        raw["ticker"],
        parse_iso(raw["published_at"]),
        raw["headline"],
        raw["accession_number"],
    )

# A normalisation run that loses more than this fraction of its sample is not a
# corpus, it is a bug. Fail loudly rather than quietly returning fewer records.
MAX_FAILURE_RATE = 0.10


def build_normalising_adapter(config: dict, raw_dir: Path | None = None):
    """The reference adapter, plus a text cache so re-normalising costs no requests."""
    adapter = build_adapter(config)
    adapter.text_cache_dir = Path(raw_dir) if raw_dir is not None else RAW_DIR
    return adapter


def load_raw_payloads(raw_dir: Path | None = None) -> list[dict]:
    """Every raw payload on disk, newest first."""
    directory = Path(raw_dir) if raw_dir is not None else RAW_DIR
    payloads = [json.loads(p.read_text(encoding="utf-8")) for p in directory.glob("*.json")]
    payloads.sort(key=lambda r: (r["published_at"], r["accession_number"]), reverse=True)
    return payloads


def select_raw_payloads(payloads: list[dict], limit: int | None) -> list[dict]:
    """Most recent filings, round-robin across native form types. See module docstring."""
    if limit is None or limit >= len(payloads):
        return payloads

    by_form: dict[str, list[dict]] = defaultdict(list)
    for raw in payloads:  # already newest-first
        by_form[raw["form"]].append(raw)

    selected: list[dict] = []
    forms = sorted(by_form)
    depth = 0
    while len(selected) < limit:
        added = False
        for form in forms:
            if depth < len(by_form[form]):
                selected.append(by_form[form][depth])
                added = True
                if len(selected) == limit:
                    break
        if not added:
            break
        depth += 1

    selected.sort(key=lambda r: (r["published_at"], r["accession_number"]), reverse=True)
    return selected


def load_pinned_ids(path: Path | str) -> list[str]:
    """announcement_ids of a previously-exported draw, in their original row order.

    Blank lines and `#` comments are ignored. Order is significant: it is the
    row order those candidates already have, and preserving it is the whole
    point of pinning.
    """
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [s for s in (line.strip() for line in lines) if s and not s.startswith("#")]


def _round_robin(payloads: list[dict], forms: set[str], limit: int, exclude: set[str]) -> list[dict]:
    """Newest-first round-robin across `forms`, skipping anything in `exclude`."""
    by_form: dict[str, list[dict]] = defaultdict(list)
    for raw in payloads:  # already newest-first
        if raw["form"] in forms and compute_announcement_id(raw) not in exclude:
            by_form[raw["form"]].append(raw)

    picked: list[dict] = []
    names = sorted(by_form)
    depth = 0
    while len(picked) < limit:
        added = False
        for form in names:
            if depth < len(by_form[form]):
                picked.append(by_form[form][depth])
                added = True
                if len(picked) == limit:
                    break
        if not added:
            break
        depth += 1
    return picked


def select_with_topup(
    payloads: list[dict],
    pinned_ids: list[str],
    topup_groups: list[dict],
) -> list[dict]:
    """Pinned payloads in pin order, then one round-robin draw per top-up group.

    The pinned block reproduces an earlier draw exactly, so already-exported row
    ids stay valid.

    The top-up is drawn per GROUP rather than as one pool. A single round-robin
    across every form type would cap 8-K at the same depth as S-8 and SD, even
    though 8-K is far more numerous and is where guidance changes, contract
    awards and M&A actually appear — the earlier draw hit exactly that problem.
    Grouping lets the substantive and routine ends of the corpus be sized
    independently, so the owner has enough candidates at BOTH ends.

    Group sizes are a coverage rule. Nothing here decides whether any given
    filing is material — that stays entirely the owner's call.
    """
    by_id = {compute_announcement_id(raw): raw for raw in payloads}

    pinned: list[dict] = []
    missing: list[str] = []
    for announcement_id in pinned_ids:
        raw = by_id.get(announcement_id)
        if raw is None:
            missing.append(announcement_id)
        else:
            pinned.append(raw)
    if missing:
        raise RuntimeError(
            f"{len(missing)} pinned announcement_id(s) are no longer in data/raw/ "
            f"(first: {missing[0]}). The pin file and the corpus have diverged; "
            "re-pinning would renumber already-exported candidate rows."
        )

    taken = set(pinned_ids)
    topup: list[dict] = []
    for group in topup_groups:
        picked = _round_robin(payloads, set(group["forms"]), group["limit"], taken)
        taken.update(compute_announcement_id(raw) for raw in picked)
        topup.extend(picked)
        print(f"  top-up group '{group['name']}': {len(picked)} of {group['limit']} requested")

    topup.sort(key=lambda r: (r["published_at"], r["accession_number"]), reverse=True)
    return pinned + topup


def normalise_one(raw: dict, config: dict | None = None, adapter=None) -> Announcement:
    """One raw payload -> one canonical Announcement. Raises on anything malformed."""
    config = config or load_config()
    adapter = adapter or build_normalising_adapter(config)
    return adapter.normalise(raw)


def normalise_all(
    config: dict | None = None,
    limit: int | None = None,
    raw_dir: Path | None = None,
) -> list[Announcement]:
    """Normalise the selected slice of data/raw/. Loud on failure, never silent."""
    config = config or load_config()
    if limit is None:
        limit = config["normalise"]["sample_limit"]

    adapter = build_normalising_adapter(config, raw_dir=raw_dir)
    payloads = load_raw_payloads(raw_dir)

    settings = config["normalise"]
    pin_file = settings.get("pin_file")
    if pin_file:
        pinned_ids = load_pinned_ids(ROOT / pin_file)
        selected = select_with_topup(
            payloads,
            pinned_ids=pinned_ids,
            topup_groups=settings["topup_groups"],
        )
        print(
            f"Selected {len(pinned_ids)} pinned + {len(selected) - len(pinned_ids)} top-up "
            f"= {len(selected)} of {len(payloads)} raw payload(s)."
        )
    else:
        selected = select_raw_payloads(payloads, limit)
    print(
        f"Normalising {len(selected)} of {len(payloads)} raw payload(s) "
        f"across {len({r['form'] for r in selected})} native form type(s)."
    )

    records: list[Announcement] = []
    failures: list[str] = []
    for raw in selected:
        try:
            records.append(adapter.normalise(raw))
        except Exception as exc:
            failures.append(f"{raw['ticker']} {raw['form']} {raw['accession_number']}: {exc}")

    for failure in failures:
        print(f"WARNING: could not normalise {failure}")
    if selected and len(failures) / len(selected) > MAX_FAILURE_RATE:
        raise RuntimeError(
            f"{len(failures)} of {len(selected)} payloads failed to normalise "
            f"(ceiling is {MAX_FAILURE_RATE:.0%}) — the corpus or the source has changed"
        )

    print(f"Normalised {len(records)} record(s); {len(failures)} failure(s).")
    return records


def main() -> None:
    records = normalise_all()
    forms = sorted({r.native_doc_type.split(" [")[0] for r in records})
    print(f"{len(records)} canonical record(s) across {len(forms)} form type(s): {', '.join(forms)}")


if __name__ == "__main__":
    main()
