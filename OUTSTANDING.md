# OUTSTANDING — blockers before Batch B can start

Last updated 2026-08-02 (third pass). **Both preconditions are now cleared. The
human gate is satisfied; Batch B can start.** Cumulative API spend remains NZ$0.00
(no LLM call yet — the first is B1).

---

## 1. `data/gold/gold.csv` — human gate — **CLEARED**

The owner labelled all 220 candidates and, by explicit decision (see below),
**dropped the stratified n=60 in favour of the full labelled pool**. The gate now
passes:

```
.venv/bin/python -m evals.validate_gold
→ gold.csv ACCEPTED — full labelled candidate pool, all enums legal,
  evidence spans verbatim, 8 warning(s). The §F gate is cleared.   (exit 0)
```

### Owner deviation 2026-08-02 — stratification dropped
Originally `data/gold/gold.csv` was to be a stratified n=60 (15/15/12/10/8). The
owner instead labelled the whole 220-row pool and chose to use it as-is. SPEC §13.1,
`GOLD_REQUIREMENTS.md` §B/§F and `evals/validate_gold.py` were updated to match: the
gate requires every candidate to be labelled and no longer enforces per-slice counts;
`slice_tag` is retained as a descriptive, enum-validated field for §13.3 breakdowns.
Accepted consequences: composition ~26/42/135/7/10 (~61% `hard_negative`,
`hard_positive` ~3%), uneven per-slice denominators, and **~3.7× eval cost** vs n=60 —
a live risk against the NZ$3.00 batch cap (S7); see the plan's Open Decision 5.

Note: the agent did **not** create or infer any label — prohibition #1 / S4 held
throughout. The labels are the owner's; only the gate definition changed, on the
owner's instruction.

### Sub-blocker: pool composition — **CLEARED**
The original 120-row pool could not fill the §13.1 stratification (short 9 on
`clear_material`, 8 on `clear_immaterial`, 9 on `hard_positive`). Resolved by the
widened draw: watchlist 20 → 40 tickers, watermark rolled back 90d,
`candidates.csv` now **220 unlabelled rows across 39 issuers**, rows 1–120
byte-identical to the earlier draw via `config/candidate_pin.txt`. Feasibility
re-checked in `GOLD_REQUIREMENTS.md` §E: every slice with a structural proxy
clears its target 3–5x. The 15/15/12/10/8 split is reachable.

### Independent re-verification of the pool (read-only, this pass)
- 220 rows; `id` unique and contiguous 1–220; `announcement_id` unique.
- All 220 `announcement_id`s resolve in `state.db` (10818 rows) — every gold row
  drawn from this pool will have a canonical record for B3 to run against.
- All 9 owner-only columns empty on every row: **1980 cells, zero populated.**
- `issuer_price_sensitive_flag` empty throughout, as EDGAR supplies no such signal.

**To clear:**
- [x] Owner labelled the pool into `data/gold/gold.csv` (220 rows).
- [x] Gate passes: `.venv/bin/python -m evals.validate_gold` → exit 0.
- [x] §D conventions fixed (semicolon / span-on-abstention / `easy|medium|hard`).
- [x] Stratification decision made (full pool; see deviation above).

---

## 2. `pricing_usd_per_mtok` and `fx_usd_nzd` are null — **CLEARED**

Populated in `config.yaml:69-77` and verified this pass:

```yaml
pricing_usd_per_mtok:          # verified 2026-08-02
  primary_input: 1.00          # claude-haiku-4-5
  primary_output: 5.00
  escalation_input: 5.00       # claude-opus-4-6
  escalation_output: 25.00
fx_usd_nzd: 1.6976             # XE mid-market spot; sources spread ~2% on the day
```

Cost accounting for §6 and the NZ$3.00 S7 cap is therefore live before B1's first
LLM call. Related fix, same pass: escalation model moved `claude-sonnet-5` →
`claude-opus-4-6`, because Sonnet 5 and everything from Opus 4.7 onward rejects
the `temperature: 0.0` that SPEC §4 mandates with a 400.

---

## New this pass: the §F gate is now executable

`GOLD_REQUIREMENTS.md` §F defined "cleared" in prose. It is now one command:

```bash
python -m evals.validate_gold
```

Validates only — it writes nothing, to `data/gold/` or anywhere else. Enforces
§A.3 header order, §A.4 row count, §A.5 pool membership and copy-through of the
identifying columns, §A.6 no-empty-label, §B exact slice counts, the `Materiality`
and `Category` enums, the 200-char `evidence_quote`/`rationale` limits, verbatim
evidence spans against `body_text`, tz-aware `labelled_at`, and the three §D
conventions. Reports every bad row in one pass rather than stopping at the first.

Exercised against 16 synthetic fixtures (built in a scratch dir, not in the repo):
a well-formed file exits 0, and each of 14 seeded defect classes — wrong enum
case, pipe delimiter, off-enum category, non-verbatim span, over-length span,
empty label, bad difficulty, naive timestamp, skewed slice counts, unknown
`announcement_id`, re-typed identifying column, populated price-sensitive flag,
duplicate row, short file — is caught with the row number and the rule it broke.
The §D.2 abstention carve-out warns rather than rejects, since no validator can
tell from outside whether a span genuinely applies.

Deliberately **not** registered in `checks/run_all.py`: it fails until the gold
set exists, and a permanently-red `run_all` teaches people to ignore it.
`python -m checks.run_all` remains 4 checks / 432 assertions / exit 0.

---

## New this pass: a labelling workbench

`GOLD_REQUIREMENTS.md` §D.1 referred to "the labelling tool"; there wasn't one in
the repo. There is now:

```bash
python -m evals.label_gold
```

Stdlib only (no dependency outside SPEC §3). Serves a local page on
`127.0.0.1:8765`: filing body on the left, label form on the right.

**It contains no materiality judgement.** No default, no pre-selection, no
suggestion, no import from `triage.csv`, no heuristic that ticks a box. Every
`label_*`, `slice_tag` and `difficulty` value in the output comes from the
owner's input and nowhere else. What it automates is the half that causes most
gate failures:

- the 7 identifying columns are copied through from `candidates.csv`, so they
  cannot drift from the canonical record
- the evidence span is captured from a text selection over the real `body_text`,
  so it is **verbatim by construction**, and re-verified server-side on save
- categories encode with the §D.1 semicolon; `labelled_at` is stamped tz-aware
- slice quotas count against 15/15/12/10/8 **live**, so an over-full
  `hard_negative` shows up at row 20, not row 60
- a row counts as complete only if it would survive the gate — a non-verbatim or
  over-length span makes it incomplete, not merely warned about
- drafts save to `out/gold_drafts.json` after every change; stop and resume freely

`gold.csv` is written only on pressing "Write gold.csv", from completed rows only.

Exercised end-to-end: 60 synthetic drafts → `compose_gold` → `validate_gold`
returns ACCEPTED. Completeness probes confirmed a non-verbatim span, an
over-length span and an empty category list each block completion, while an
abstention with no span is allowed per §D.2.

---

## Also worth doing (not blocking)
- `data/gold/triage.csv` carries a `proposed_label` column and sits inside
  `data/gold/`. Nothing reads it, but a future glob over that directory could
  mistake proposals for labels. Recommend moving it to `out/` or `evals/`.
  Not moved here: S4 forbids modifying anything under `data/gold/`.
- `GOLD_REQUIREMENTS.md` §D.1 justifies the semicolon delimiter by reference to
  "the labelling tool". No such tool exists in this repo (searched all sources +
  full git history). The decision stands on its own merits; the justification
  points at something outside the tree.
- 4 ARS rows truncate at 60000 chars per SPEC §5.1 (JAZZ is 43MB → first ~0.1%
  of the document). If any lands in the gold set, the label would rest on a
  fragment. Say the word and they come out of the pool.

---

## Once the gold set lands
Run `python -m evals.validate_gold`; on exit 0, B1→B4 per AUTONOMY.md §1 — test
≤5 records during the build, make G2/G6 fire on synthetic fixtures (B2), then run
the full 60-item eval once at the end and report per §9.
