# SPEC.md — Announcement Triage Agent (ATA)

**Version:** 1.0
**Status:** Build specification — authoritative for this repository
**Audience:** The implementing agent (Claude Code) and the repo owner

---

## 0. Rules for the implementing agent

Read this section before writing any code. These override any inferred convention.

1. **Implement one increment at a time.** Increments are defined in §13. Do not start an increment that has not been explicitly requested. Do not "helpfully" implement adjacent functionality.
2. **Never create, generate, modify, or delete anything under `data/gold/`.** The gold set is hand-labelled by the repo owner. An agent-generated gold set makes the entire evaluation worthless. If asked to help with the gold set, you may only export *unlabelled* candidate rows.
3. **Never write secrets to disk outside `.env`.** Never print the API key. Never commit `.env`.
4. **After each increment, output the exact shell command** the owner should run to verify the acceptance criterion. Do not claim an increment is complete without one.
5. **Stop and ask** if this spec is ambiguous or if the data does not match the contract. Do not invent a workaround silently.
6. **No frameworks.** Standard library plus the dependencies listed in §3. No FastAPI, no Django, no Celery, no async, no ORM, no Docker. This is a one-day build.
7. **Fail loudly.** No bare `except:`. No silent defaults for missing required fields.
8. Prefer readable and obvious over clever. Every file should be reviewable in under five minutes by someone who did not write it.

---

## 1. Purpose

Triage listed-company announcements into a ranked morning brief for an investment team, and **measure how well it does that** against a hand-labelled ground truth.

### What this is

- A pipeline with one bounded LLM decision step, wrapped in deterministic guardrails
- An evaluation harness that is the primary deliverable
- A reference implementation of a repeatable pattern

### What this is not

- Not an autonomous multi-turn agent
- Not an investment recommendation system. Outputs are **research artifacts requiring human review**. No directional views, no price targets, no ratings. This is enforced in code (guardrail G6), not by policy.
- Not production infrastructure. It uses public data only, on personal equipment, with a personal API key.

### Success criteria

| # | Criterion |
|---|---|
| S1 | A dated brief is produced from live announcements in a single command |
| S2 | An eval scorecard exists with a confusion matrix, three baselines, and cost per item |
| S3 | Guardrail G2 (groundedness) and G6 (no directional language) are demonstrably firing |
| S4 | Three scorecard runs exist across prompt versions v1, v2, v3, showing measured movement |
| S5 | A hand-written failure taxonomy names 3–5 failure modes with fixes |

---

## 2. Repository layout

Create exactly this structure. Do not add directories not listed here.

```
ata/
├── README.md
├── SPEC.md
├── requirements.txt
├── config.yaml
├── .env                       # gitignored
├── .gitignore
├── state.db                   # gitignored, sqlite
├── data/
│   ├── raw/                   # gitignored — one JSON per fetched announcement
│   └── gold/
│       ├── RUBRIC.md          # OWNER-WRITTEN — do not modify
│       ├── candidates.csv     # unlabelled export, agent may write
│       └── gold.csv           # OWNER-WRITTEN — do not modify
├── prompts/
│   ├── classify_v1.md
│   ├── classify_v2.md
│   └── classify_v3.md
├── src/
│   ├── __init__.py
│   ├── models.py              # Pydantic schemas
│   ├── adapters/
│   │   ├── __init__.py        # ExchangeAdapter protocol
│   │   ├── nzx.py             # or asx.py / edgar.py — the reference implementation
│   │   └── stub.py            # one stub proving the interface generalises
│   ├── fetch.py
│   ├── normalise.py
│   ├── classify.py
│   ├── verify.py
│   ├── rank.py
│   ├── brief.py
│   ├── store.py               # sqlite: watermark, dedupe, audit log, dead-letter
│   └── run.py                 # orchestrator / CLI entry point
├── evals/
│   ├── __init__.py
│   ├── run_eval.py
│   ├── baselines.py
│   └── report.py
└── out/                       # gitignored
    ├── briefs/
    └── eval_runs/
```

---

## 3. Dependencies

```
anthropic
pydantic
requests
python-dotenv
pandas
pyyaml
```

Nothing else without asking.

---

## 4. Configuration (`config.yaml`)

All tunable values live here. **No magic numbers in code.**

```yaml
exchange:
  reference: "NZX"              # NZX | ASX | EDGAR — set at build time
  poll_interval_minutes: 10
  request_timeout_seconds: 30
  rate_limit_requests_per_second: 1    # respect the source's published limit
  user_agent: "ATA research prototype - <contact email>"

watchlist:
  - FBU
  - MFT
  - ATM
  # ~20 tickers

models:
  primary: "claude-haiku-4-5-20251001"    # bulk classification
  escalation: "claude-sonnet-5"           # low confidence or long documents
  temperature: 0.0
  max_output_tokens: 1024

pricing_usd_per_mtok:          # VERIFY against the current Anthropic pricing page
  primary_input: null
  primary_output: null
  escalation_input: null
  escalation_output: null
fx_usd_nzd: null               # set manually

thresholds:
  confidence_floor: 0.65        # below this -> coerce to insufficient_info
  escalate_below_confidence: 0.65
  escalate_above_chars: 20000
  truncate_input_chars: 60000   # hard ceiling; log every truncation

ranking:
  materiality_weight:
    material: 1.0
    insufficient_info: 0.4
    immaterial: 0.0
  recency_half_life_hours: 12
  watchlist_weight_default: 1.0

prompt_version: "v3"
```

---

## 5. Data contracts

Define these in `src/models.py` as Pydantic models. These are the contract between every module.

### 5.1 `Announcement` (canonical record)

| Field | Type | Notes |
|---|---|---|
| `announcement_id` | str | **sha256 of `f"{exchange}\|{ticker}\|{published_at.isoformat()}\|{headline}"`**. Primary key. This is what makes the system idempotent |
| `exchange` | Literal["NZX","ASX","EDGAR"] | |
| `ticker` | str | Uppercase |
| `company_name` | str | |
| `published_at` | datetime | Timezone-aware. Store UTC, render NZT |
| `headline` | str | |
| `doc_type` | str | Canonical enum — see §6.2 |
| `native_doc_type` | str | As supplied by the source, kept for audit |
| `issuer_price_sensitive_flag` | bool \| None | `None` where the exchange does not supply one (e.g. EDGAR) |
| `body_text` | str | Plain text, whitespace-normalised |
| `char_count` | int | |
| `truncated` | bool | True if `body_text` was cut at `truncate_input_chars` |
| `source_url` | str | |
| `fetched_at` | datetime | |

### 5.2 `Classification` (agent output — schema is enforced)

```json
{
  "announcement_id": "string",
  "materiality": "material | immaterial | insufficient_info",
  "confidence": 0.87,
  "categories": ["guidance_change"],
  "evidence_quote": "verbatim span copied exactly from body_text, max 200 chars",
  "rationale": "one line, max 200 chars",
  "entities": {
    "amounts": ["$412m"],
    "counterparties": [],
    "effective_dates": ["2026-09-30"]
  },
  "previously_disclosed": false,
  "needs_human_review": false
}
```

Runtime metadata appended by `classify.py`, not by the model:
`model_id`, `prompt_version`, `input_tokens`, `output_tokens`, `cost_nzd`, `latency_ms`, `escalated` (bool), `guardrail_flags` (list[str]).

### 5.3 Category enum (fixed — the model must not invent categories)

```
guidance_change, earnings_result, m_and_a, capital_raise,
director_dealing, contract_award, operational_incident,
governance_change, index_change, regulatory, admin
```

---

## 6. Exchange adapters

### 6.1 Interface

```python
class ExchangeAdapter(Protocol):
    exchange_code: str

    def poll(self, since: datetime) -> list[dict]:
        """Return raw source payloads published after `since`."""

    def normalise(self, raw: dict) -> Announcement:
        """Raw payload -> canonical Announcement."""

    def map_doc_type(self, native_type: str) -> str:
        """Native taxonomy -> canonical enum. Unknown -> 'admin', and log it."""

    def price_sensitive_flag(self, raw: dict) -> bool | None:
        """None where the exchange supplies no such signal."""
```

**Build one reference implementation and one stub.** The stub must satisfy the protocol and return an empty list from `poll()`. Its purpose is to prove the interface generalises, not to work.

### 6.2 Doc type map

Externalise as `config/doc_type_map.yaml`. This file is a visible artefact of the multi-exchange problem — keep it readable.

```yaml
NZX:
  HALFYR: earnings_result
  FLLYR: earnings_result
  GENERAL: operational_incident
ASX:
  "3Y": director_dealing
  "03001": capital_raise
EDGAR:
  "8-K": operational_incident
  "10-Q": earnings_result
```

Unknown native types map to `admin` and emit a warning. Never crash on an unseen type.

---

## 7. Agent flow

```
fetch → dedupe (announcement_id vs state.db) → normalise
  → classify (primary model)
      ↓ if confidence < escalate_below_confidence
        OR char_count > escalate_above_chars
  → escalate: chunk body_text, classify per chunk on escalation model,
              aggregate (max materiality wins, min confidence carried)
  → verify (guardrails G1–G6)
  → rank
  → brief
  → append audit log row
```

The escalation branch is the only place the system makes a decision about its own process. Keep it simple and log every escalation with the reason.

---

## 8. Prompts

Prompt files are **versioned and immutable**. To change a prompt, create the next version file. Never edit `classify_v1.md` after it has produced a scorecard.

Each file contains, in this order:

1. **Role** — classifies listed-company announcements for an institutional research team; does not give investment views
2. **Materiality rubric** — copied verbatim from `data/gold/RUBRIC.md`. The model and the gold set must use identical wording or the eval is measuring nothing
3. **Category definitions** — one line each
4. **Hard rules:**
   - `evidence_quote` must be copied character-for-character from the announcement. Never paraphrase
   - If the text alone does not settle it, return `insufficient_info`. Abstention is a correct answer
   - Never use directional or recommendation language
   - If uncertain about a number, omit it rather than estimate
5. **Few-shot examples** — exactly 3, including one abstention. **These must be drawn from announcements NOT present in `gold.csv`.** Contaminating the eval set with few-shots invalidates the results
6. **Output schema** and "return only JSON, no preamble"

Version progression:

| Version | Adds |
|---|---|
| `v1` | Role + schema only. The naive baseline |
| `v2` | + materiality rubric, + category definitions |
| `v3` | + forced verbatim quote, + explicit abstention instruction, + few-shots |

---

## 9. Guardrails (`verify.py`)

Deterministic. No LLM calls in this module.

| ID | Check | On failure |
|---|---|---|
| **G1** | Output parses as JSON; all enum values valid; required fields present | Retry once; second failure → dead-letter with the raw response |
| **G2** | `evidence_quote` appears verbatim in `body_text` after whitespace normalisation (collapse runs of whitespace, casefold) | Set `needs_human_review=true`, append flag `G2_ungrounded_quote`. **This is the hallucination metric** |
| **G3** | Every string in `entities.amounts` appears in `body_text` | Strip the offending value, append flag `G3_unverified_amount` |
| **G4** | `ticker` is in the configured watchlist | Drop the record, log it |
| **G5** | `confidence < thresholds.confidence_floor` | Coerce `materiality` to `insufficient_info`, append flag `G5_low_confidence` |
| **G6** | Case-insensitive regex denylist over `rationale` and `evidence_quote`: `buy, sell, overweight, underweight, target price, we recommend, undervalued, overvalued, outperform, underperform` | Block the record from the brief, append flag `G6_directional_language`, route to review |

**G2 and G6 are non-negotiable and must be implemented in the first guardrail increment.** G2 is the entire hallucination measurement and requires no LLM judge. G6 is the compliance guardrail.

Every flag raised is written to the audit log, counted in the scorecard, and shown in the brief footer.

---

## 10. Ranking (`rank.py`)

```
score = materiality_weight[materiality]
      * confidence
      * 0.5 ** (hours_since_published / recency_half_life_hours)
      * watchlist_weight[ticker]
```

Transparent and hand-set. No learned model. If asked "why is this third?", the answer must be one sentence.

Records with `materiality == "insufficient_info"` or any guardrail flag go to a **separate "Needs a look" section**. They are never buried and never mixed into the ranked list.

---

## 11. Brief output (`brief.py`)

Markdown, written to `out/briefs/YYYY-MM-DD.md`. Sections:

1. **Material — ranked** — ticker, headline, one-line rationale, the verbatim `evidence_quote`, source link
2. **Needs a look** — abstentions and guardrail-flagged records, with the flag named
3. **Run footer** — announcements processed, new vs deduped, model IDs, prompt version, escalation count, guardrail flag counts, total cost NZD, runtime

The footer is deliberate. The system reports on itself.

---

## 12. Execution semantics (`store.py`, `run.py`)

| Property | Implementation |
|---|---|
| **Idempotency** | `announcement_id` is the primary key in `processed` table. Already present → skip. Re-running any window must be safe |
| **Watermark** | `watermark` table, one row per exchange, `last_processed_at`. Advance **only after a successful full run**, never per item |
| **At-least-once** | Assume the source re-delivers. Never assume exactly-once |
| **Retries** | Two retries, exponential backoff (2s, 8s), on transport and G1 failures only |
| **Dead-letter** | Third failure writes to `dead_letter` table with the error and raw payload. **The run continues.** One bad announcement must never kill the brief |
| **Rate limiting** | Honour `rate_limit_requests_per_second` from config. Sleep between requests |
| **Audit log** | Append-only `audit` table: `announcement_id, decided_at, materiality, confidence, prompt_version, model_id, escalated, guardrail_flags, input_tokens, output_tokens, cost_nzd`. **Never UPDATE, never DELETE** |

### CLI

```bash
python -m src.run                                   # incremental from watermark
python -m src.run --from 2026-07-01 --to 2026-07-28 # backfill / replay
python -m src.run --dry-run                         # fetch + classify, no brief, no watermark advance
```

Replay is a first-class capability, not a debugging hack.

---

## 13. Evaluation specification

### 13.1 Gold set (`data/gold/gold.csv`) — OWNER-WRITTEN

```
id, announcement_id, exchange, ticker, published_at, doc_type,
issuer_price_sensitive_flag,
label_materiality, label_categories, label_evidence_span, label_rationale,
slice_tag, difficulty, labelled_at, labeller, pass_number
```

Target n=60, stratified:

| Slice tag | n | Purpose |
|---|---|---|
| `clear_material` | 15 | Baseline competence |
| `clear_immaterial` | 15 | Over-flagging |
| `hard_negative` | 12 | Looks material, isn't |
| `hard_positive` | 10 | Buried materiality |
| `ambiguous` | 8 | Tests abstention, not accuracy |

The agent may export unlabelled `candidates.csv` with these columns empty. **It may not populate any `label_*` column.**

### 13.2 Harness (`evals/run_eval.py`)

```bash
python -m evals.run_eval --prompt-version v3 --runs 3
```

1. Load `gold.csv`; run the **full agent including guardrails** on each item
2. Repeat `--runs` times to measure stability
3. Run all baselines (§13.4) on the identical set
4. Write `out/eval_runs/<timestamp>_<prompt_version>/` containing:
   - `scorecard.md` — human-readable
   - `scorecard.pdf` — the handover artefact
   - `per_item.csv` — one row per gold item per run
   - `failures.csv` — every disagreement, with model rationale and owner rationale side by side
   - `confusion_matrix.csv`
   - `run_manifest.json` — dataset hash, prompt version + file hash, model IDs, temperature, timestamp, total cost

**A run that cannot be reproduced is not a result.** The manifest is mandatory.

### 13.3 Metrics

| Block | Metric |
|---|---|
| **Headline** | Recall on `material` at precision ≥ 0.60; full 3×3 confusion matrix |
| **Ranking** | Precision@5, Precision@10 |
| **Groundedness** | % of records passing G2 — the hallucination rate |
| **Abstention** | Abstention rate on the `ambiguous` slice; **confidently-wrong rate** (confidence > 0.8 and materiality wrong) across the whole set |
| **Extraction** | Per-field accuracy, **reported unaveraged** |
| **Slices** | Every metric broken by exchange, doc_type, char_count band, difficulty |
| **Cost / latency** | Tokens and NZD per announcement; p50/p95 latency; projected cost per trading day at 7-exchange volume |
| **Stability** | Variance of each headline metric across runs |
| **Ceiling** | Owner's intra-rater self-agreement, read from README. Report as the honest ceiling on any model score |

Recall is weighted above precision: a missed material announcement is a risk event; a false positive costs twenty seconds. Never report bare accuracy — the classes are imbalanced and it flatters.

**No LLM-as-judge anywhere a string comparison will do.**

### 13.4 Baselines (`evals/baselines.py`)

Mandatory. Run on the identical gold set.

| Baseline | Definition |
|---|---|
| `flag_all` | Everything is material. Establishes recall ceiling and the precision cost of pure safety |
| `rules` | Classify from `doc_type` + a keyword list. **The real competitor.** If the LLM does not clearly beat this, the honest finding is a hybrid: rules for the easy majority, model for the remainder |
| `naive_prompt` | `classify_v1` — no rubric, no schema discipline. Isolates how much of the result came from prompt design rather than the model |

### 13.5 Scorecard format

`scorecard.md` opens with this table, one row per prompt version, so movement is visible at a glance:

| Prompt | Recall (material) | Precision | Grounded % | Confidently wrong | Abstention (ambiguous) | Cost/item NZD |
|---|---|---|---|---|---|---|
| v1 | | | | | | |
| v2 | | | | | | |
| v3 | | | | | | |
| baseline: rules | | | | | | |
| baseline: flag_all | | | | | | |

---

## 14. Increment plan

Implement in this order, one at a time, on request. Each requires a passing acceptance check before the next begins.

| # | Increment | Acceptance check | Do NOT implement |
|---|---|---|---|
| 1 | Skeleton, `config.yaml`, `src/models.py` | `python -c "from src.models import Announcement; print('ok')"` | Anything else |
| 2 | `store.py` + `fetch.py` — one adapter, watermark, hash dedupe | Run twice; **second run fetches 0 new records** | Normalisation, classification |
| 3 | `normalise.py` + doc_type map + stub adapter | 50 records in `data/raw/`, no nulls in required fields, `announcement_id` unique | Classification |
| — | **GOLD SET — owner only.** Agent exports `candidates.csv` unlabelled and stops | 60 labelled rows exist | **Any label column** |
| 4 | `classify.py` — LLM call, forced JSON, escalation, cost logging | 5 records classified, valid JSON, cost printed per record | Guardrails, eval |
| 5 | `verify.py` — G1, G2, G6 minimum | Corrupt an `evidence_quote` by hand and confirm G2 fires | G3–G5 if time-pressed |
| 6 | `evals/run_eval.py` + `report.py` | `scorecard.md` exists with a confusion matrix and a run manifest | Baselines |
| 7 | `evals/baselines.py` | Three baseline rows in the scorecard | |
| 8 | `rank.py` + `brief.py` | One dated brief in `out/briefs/` | HTML styling |
| 9 | Prompts v2, v3; re-run eval after each | Three scorecard rows showing movement | |
| 10 | README + failure taxonomy | **Owner-written.** Agent may scaffold headings only | Any content |

**Time gate:** if increment 3 is not passing by hour 2.5 of the build, switch the reference adapter to SEC EDGAR and do not revisit the decision.

---

## 15. Known limitations

Reproduce these verbatim in `README.md`. Stating them is a requirement, not a caveat.

- n=60, single labeller, no adjudication panel — directional only, roughly ±12pp
- Owner intra-rater self-agreement is the ceiling on any reported score
- No temporal holdout; historical announcements may sit within model training data
- Issuer price-sensitive flag is a legal-defensive artefact that over-flags; used only as a pre-label
- Public announcements only — real mix, volume and exchange spread will shift every number
- Polling with a watermark, **not** event-driven
- Ranking weights are hand-set, not tuned
- One reference exchange implemented; cross-exchange generalisation is untested and is an open question, not a claim

---

## 16. Glossary

| Term | Meaning |
|---|---|
| **Gold set** | Hand-labelled ground truth. The thing scores are measured against |
| **Guardrail** | A deterministic, non-AI check on model output |
| **Groundedness** | Whether a quoted span actually appears in the source text |
| **Watermark** | Timestamp of the last successfully processed item |
| **Idempotency** | Running the same input twice yields one result, not two |
| **Dead-letter** | Store for records that failed repeatedly, so one failure cannot stop a run |
| **Slice** | A subset of the gold set sharing a property, scored separately |
| **Baseline** | A simpler alternative the LLM must beat to justify its cost |
