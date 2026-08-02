# gold.csv — exact requirements to clear the Batch B blocker

Path: `data/gold/gold.csv`. Owner-written. I cannot create or populate any
`label_*` / `slice_tag` / `difficulty` cell (S4, prohibition #1) — this is the
spec you fill against.

Sources of truth: SPEC §13.1 (columns + stratification), `src/models.py`
`Classification` (enums + max lengths), RUBRIC.md v1 (label semantics),
A4 check note (owner-only columns).

---

## A. File-level requirements

1. **Location/name exact:** `data/gold/gold.csv` (not in a subfolder).
2. **UTF-8, RFC-4180 CSV.** Any cell containing a comma, quote, or newline
   (evidence spans, rationales) must be double-quoted; embedded `"` doubled.
3. **Header = the 16 SPEC §13.1 columns, in this exact order and spelling:**
   ```
   id,announcement_id,exchange,ticker,published_at,doc_type,issuer_price_sensitive_flag,label_materiality,label_categories,label_evidence_span,label_rationale,slice_tag,difficulty,labelled_at,labeller,pass_number
   ```
   (Trailing extra columns like candidates.csv's `headline,…,source_url` are
   tolerated only if you keep these 16 first, in order. Safest: just these 16.)
4. **Every candidate labelled** (full pool, currently 220 rows), + header. *(Owner
   deviation 2026-08-02: was "exactly 60 data rows" — see §B.)*
5. **Every row must be drawn from `data/gold/candidates.csv`.** The harness (B3)
   loads each item by `announcement_id` and runs the live agent on the canonical
   record in the store — so an `id`/`announcement_id` that isn't in the exported
   pool has no record to run against. Copy the 7 identifying columns straight
   through from the candidate row; do not hand-type them.
6. **No empty `label_*` cell on any row.** An unlabelled or partially labelled
   row fails the gate — the whole point of the human gate.

---

## B. Stratification — DROPPED (owner deviation 2026-08-02)

The original design required `slice_tag` counts across exactly 60 rows to be exactly
**15 `clear_material` / 15 `clear_immaterial` / 12 `hard_negative` / 10 `hard_positive`
/ 8 `ambiguous`**. **That is no longer enforced.** The gold set is the full labelled
pool (all 220 candidates), and `evals/validate_gold.py` checks only that every
candidate is labelled — not the per-slice counts.

`slice_tag` is still a **required, enum-valid** per-row field (it drives the §13.3
per-slice breakdowns), but any of the five values is legal in any quantity. The actual
composition of the 220-row set is ~26/42/135/7/10 — dominated by `hard_negative`. See
SPEC §13.1 for the accepted consequences (uneven denominators, ~3.7× eval cost).

---

## C. Column-by-column

### Identifying columns — copy through from candidates.csv, do not author
| column | value |
|---|---|
| `id` | integer id from the candidate row it points at; must be unique in gold.csv |
| `announcement_id` | sha256 from that candidate row, verbatim (this is the join key) |
| `exchange` | `EDGAR` (enum: NZX \| ASX \| EDGAR) |
| `ticker` | copy through |
| `published_at` | copy through (tz-aware ISO-8601) |
| `doc_type` | copy through — canonical `Category` enum |
| `issuer_price_sensitive_flag` | **empty** for every row (EDGAR supplies no such signal) |

### Label columns — you author these; enums are hard constraints
| column | rule |
|---|---|
| `label_materiality` | exactly one of `material` \| `immaterial` \| `insufficient_info`. Never empty. Semantics = RUBRIC §2–§3. |
| `label_categories` | one **or more** of the 11 `Category` enum values: `guidance_change, earnings_result, m_and_a, capital_raise, director_dealing, contract_award, operational_incident, governance_change, index_change, regulatory, admin`. At least one on every row (`admin` for purely procedural). **Multi-value delimiter is unspecified in SPEC — you must pick one and use it on every multi-value cell (see §D.1).** No value outside the enum. |
| `label_evidence_span` | verbatim substring of that record's `body_text`, **≤200 chars** (mirrors `Classification.evidence_quote` max_length=200). For `insufficient_info` where no span settles it, see §D.2. |
| `label_rationale` | one line, **≤200 chars** (mirrors `Classification.rationale`). Why this call, in analyst terms. |

### Provenance columns — you author; keep values consistent
| column | rule |
|---|---|
| `slice_tag` | exactly one of the 5 tags in §B. Drives per-slice scoring. Never empty. |
| `difficulty` | **vocabulary is not defined in SPEC — you must fix a small closed set (e.g. `easy` \| `medium` \| `hard`) and use only those (see §D.3).** |
| `labelled_at` | tz-aware ISO-8601 timestamp (repo rejects naive datetimes elsewhere; match that). |
| `labeller` | your identifier (initials/name), non-empty. |
| `pass_number` | integer (`1`, `2`, …) — which labelling pass produced the row. |

---

## D. Three conventions — DECIDED 2026-08-02, override if you disagree

SPEC is silent on these three. They are encoding/vocabulary decisions, not
materiality judgements, so they have been fixed to unblock labelling rather than
left open. B3 will be built to parse exactly these. Say the word to change any.

1. **`label_categories` multi-value encoding — SEMICOLON, no spaces.**
   e.g. `guidance_change;earnings_result`.
   *Changed from the pipe originally recommended here.* The labelling tool
   already writes and re-parses `;` (`cats.join(";")` / `.split(";")`), and any
   drafts held in it are stored that way. Standardising on pipe would have
   silently failed to re-tick categories on every existing draft, and would have
   made tool output unparseable to a pipe-based B3 loader. Semicolon costs
   nothing and keeps tool, drafts, and loader consistent.
2. **`label_evidence_span` when `insufficient_info` — quote the span the
   ambiguity turns on.** i.e. the sentence whose missing magnitude, counterparty
   or date blocks the call. Leave empty ONLY where literally no span applies.
   Rationale: an abstention with a span is testable (G2 can check groundedness);
   an abstention with an empty span is not.
3. **`difficulty` closed set — `easy` | `medium` | `hard`.** Lowercase, exactly
   these three. Any fourth value fails the gate.

---

## E. Feasibility — CHECKED 2026-08-02, stratification is reachable

Read-only pass over the widened 220-row `candidates.csv` (39 issuers). Grouped by
FORM-TYPE FAMILY only — which slice a row actually lands in is your judgement and
is not derivable from form type, so this is a capacity check, not a pre-labelling:

| §13.1 demand | needs | pool supplies | headroom |
|---|---:|---:|---:|
| `clear_material` + `hard_positive` (real content) | 25 | 89 substantive filings | 3.6x |
| `clear_immaterial` (genuinely routine) | 15 | 73 routine + insider | 4.9x |
| `hard_negative` ("looks material, isn't") | 12 | 37 structured-note supplements | 3.1x |
| `ambiguous` | 8 | not derivable from form type — your call alone | — |

Every slice with a structural proxy clears its target several times over, so the
exact 15/15/12/10/8 split is comfortably reachable. Labelling can proceed.

---

## F. Definition of "cleared"
`data/gold/gold.csv` exists with: every candidate labelled (full pool); the 16
columns in order; every `label_*`, `slice_tag`, `difficulty` non-empty; all enum
values legal; evidence spans verbatim; every `announcement_id` resolvable in the
store; conventions §D fixed. *(Owner deviation 2026-08-02: the exact
15/15/12/10/8 slice quota is no longer part of this definition — see §B.)* On
that, B1 starts.

### Status 2026-08-02 — CLEARED
- `data/gold/gold.csv` — **present, 220 labelled rows, gate PASSED.**
  `.venv/bin/python -m evals.validate_gold` → *"ACCEPTED — full labelled candidate
  pool, all enums legal, evidence spans verbatim, 8 warning(s)"*, exit 0.
- §B stratification — **dropped by owner decision**; full pool used instead.
- §D conventions — **fixed** (semicolon / span-on-abstention / easy|medium|hard).
- Escalation model vs pricing — **reconciled** (`models.escalation: "claude-opus-4-6"`).
- 8 non-blocking warnings — `insufficient_info` rows with empty evidence spans
  (rows 18, 87, 143, 144, 181, 182, 205, 206); allowed by §D.2.
