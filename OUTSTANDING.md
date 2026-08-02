# OUTSTANDING — blockers before Batch B can start

Last verified 2026-08-02 (second pass). Of the two preconditions originally
recorded here, **one is cleared and one remains**. Batch B is still not started;
cumulative API spend remains NZ$0.00.

---

## 1. `data/gold/gold.csv` does not exist — human gate not satisfied — **STILL OPEN**

Re-verified: `data/gold/` holds `RUBRIC.md`, `candidates.csv` (220 unlabelled
rows) and `triage.csv` (suggestions only). `gold.csv` is absent.

This is the one blocker that cannot be cleared from this side. Prohibition #1
(`AUTONOMY.md:96`) and stop condition S4 (`AUTONOMY.md:81`) forbid creating,
populating or inferring any `label_*`, `slice_tag` or `difficulty` cell, and the
reason is not procedural: an agent-labelled gold set measures the agent against
its own judgement, which makes every number the evaluation produces meaningless.

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
- [ ] Owner labels 60 rows into `data/gold/gold.csv` per `GOLD_REQUIREMENTS.md`.
- [x] Pool wide enough to support the stratification.
- [x] §D conventions fixed (semicolon / span-on-abstention / `easy|medium|hard`).
- [x] Machine-checkable gate: `python -m evals.validate_gold` (see below).

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
