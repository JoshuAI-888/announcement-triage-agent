# Migrating the Announcement Triage Agent to Databricks — end‑to‑end runbook

**Audience:** someone who has *never* used Databricks. Every step says exactly where
to click, what to type, and what "done" looks like. Where a product screen may have
moved, the runbook tells you to ask the **Databricks Assistant** (which is powered by
Claude) to confirm the current path — so you are never stuck.

**What you have today (the thing we are moving):** a Python program that, once a day,
pulls SEC EDGAR filings for a watchlist of ~500 tickers, asks Claude whether each
filing is *material* / *needs a look* / *immaterial* (with an evidence quote and
guardrail flags), ranks them, renders an HTML email brief, and stores everything in a
local SQLite file (`state.db`) plus JSON artifacts. It is orchestrated by **GitHub
Actions** and shown through a **Next.js portal on Vercel**. A separate Claude routine
drafts the brief into Gmail.

**What you will have after this runbook:** the exact same behaviour, but running
entirely inside one Databricks workspace — ingestion, storage, the Claude
classification, evaluation, the operator portal, and natural‑language querying — with
governance and audit built in. The picture is the interactive diagram on the portal's
**"On Databricks"** page; this document is the step‑by‑step way to build it.

> **Two ground rules that never change during this migration**
> 1. **`prompts/classify_v3.md` and the gold eval corpus are frozen.** They define
>    classification quality. We *reuse* the prompt text verbatim on Databricks; we do
>    not rewrite it.
> 2. **Email is draft‑only.** Nothing in this migration may send an email. We stage a
>    draft; a human sends it. (On Databricks the "outbox" is a table, not an SMTP call.)

---

## 0. The map: every current file → its Databricks home

Keep this table open the whole time. The left column is what exists in this repo; the
right column is the diagram node you are replacing it with.

| Today (this repo) | Does what | Databricks replacement (diagram node) |
|---|---|---|
| GitHub Actions `daily-brief.yml` + `scripts/ci_gate.py` | Cron; decide digest / intraday / skip | **Lakeflow Jobs · Workflows** (serverless scheduler) |
| `src/fetch.py`, `src/adapters/edgar.py`, `src/market.py` | Pull EDGAR filings + market prices | **Lakeflow Pipelines** (declarative ingest) |
| `data/raw/` (raw filing HTML/PDF on disk) | Raw source blobs | **Unity Catalog Volumes** (governed object storage) |
| `state.db` (SQLite: `processed`, `watermark`, `audit`, dead‑letter, `classification_cache`) + `out/filings/*.json` | Dedup, watermark, append‑only audit, cached verdicts, curated output | **Delta Lake tables** under **Unity Catalog** (bronze → silver → gold) |
| `src/classify.py` + `src/providers.py` + `prompts/classify_v3.md` | Ask Claude for materiality + rationale + quote + flags | **AI Functions / Agent Bricks** calling **Mosaic AI Model Serving** |
| `runtime_config.json` `run.provider`, spend, fallback | Which model, cost caps | **Unity AI Gateway** (routing, spend caps, guardrails) |
| `src/verify.py`, `src/rank.py`, `src/flags.py` | Guardrails, tiering, plain‑English flags | Silver→gold transforms inside the same **Lakeflow Pipeline** |
| `checks/`, `evals/`, `run-eval.yml`, gold corpus | Offline eval harness, run log | **MLflow 3** (tracing, LLM‑judge eval, prompt registry) |
| `out/run_log.jsonl`, `out/pdf_log.jsonl` | Append‑only run/decision logs | **MLflow traces** + **Lakehouse Monitoring** inference tables |
| `runtime_config.json`, cost ledger, portal state, draft queue | Small mutable app state | **Lakebase** (serverless Postgres) |
| `dashboard/` (Next.js portal on Vercel) | Operator UI | **Databricks Apps** (hosts the app in‑workspace) |
| (new capability) | "Show me material filings with confidence < 0.7" | **Genie** (natural‑language SQL over gold tables) |
| GitHub HMAC cookie gate, secrets, audit | AuthN/Z + audit trail | **Unity Catalog** governance + Databricks OAuth |

You will build the right column roughly top‑to‑bottom of the data flow: **ingest →
store → classify → verify/rank → eval → serve → app → govern.**

---

## 1. Accounts, tools, and the two helpers you'll lean on

### 1.1 Create the Databricks workspace (~15 min)
1. Go to <https://www.databricks.com/try-databricks> and sign up. Choose **"Get
   started"** and, when asked, pick a cloud (**AWS**, **Azure**, or **GCP**). If you
   have no preference, pick the one your organisation already pays for; the steps below
   are identical across clouds unless noted.
2. Databricks provisions a **workspace** (a URL like `https://dbc‑xxxx.cloud.databricks.com`).
   Bookmark it. Everything in this runbook happens inside that URL.
3. On first login, confirm **Unity Catalog** is enabled: left sidebar → **Catalog**. If
   you see a catalog browser, you're set. (New workspaces have it on by default. If it's
   missing, in **Settings → Advanced** enable Unity Catalog, or ask the Assistant —
   see §1.3.)

### 1.2 Install the local command‑line tool (so Claude Code can drive it)
On your Mac (this repo's machine):
```bash
brew tap databricks/tap && brew install databricks
databricks configure   # paste your workspace URL, then a Personal Access Token
```
Create the token in the workspace: top‑right avatar → **Settings → Developer → Access
tokens → Generate new token**. Copy it into the `databricks configure` prompt. Verify:
```bash
databricks current-user me   # should print your email
```

### 1.3 Your first helper: the Databricks Assistant (this *is* Claude)
Inside the workspace, every notebook and SQL editor has an **Assistant** panel (a small
chat/sparkle icon, usually top‑right of the cell or a left rail). It is Claude, wired to
your workspace's schema. Use it constantly:
- *"Write the Delta table DDL for a table with these columns…"* → it drafts SQL you can run.
- *"This cell errored with X — fix it."* → it edits in place.
- *"What's the current menu path to create a serving endpoint?"* → it answers for the
  version you actually have, which future‑proofs this runbook against UI changes.

Rule of thumb for this migration: **paste the relevant snippet from this file into the
Assistant and say "adapt this to my workspace and run it."** That's the intended workflow.

### 1.4 Your second helper: Genie (natural language over your tables)
Genie answers plain‑English questions with governed SQL over Unity Catalog tables. You
won't set it up until §9 (it needs the gold tables to exist first), but keep it in mind:
it replaces the "let me write a SQL query" step for both you and, later, the portal.

### 1.5 (Optional) Drive it all from Claude Code
You can keep working in this repo with Claude Code and let it run `databricks …` CLI
commands and edit the migration notebooks. That's the fastest path if you're already
comfortable here. The Assistant (§1.3) is the in‑browser equivalent for people who'd
rather not use a terminal. **Use either; they're both Claude.**

---

## 2. Names and secrets you'll set once (do this before anything else)

### 2.1 Pick your catalog + schema names
Unity Catalog is a three‑level namespace: **`catalog.schema.table`**. We'll use:
- Catalog: **`triage`**
- Schemas: **`bronze`** (raw), **`silver`** (cleaned), **`gold`** (final verdicts), **`ops`** (config, logs, drafts)

Create them (SQL editor: left sidebar → **SQL Editor → New query**, paste, **Run**):
```sql
CREATE CATALOG IF NOT EXISTS triage;
CREATE SCHEMA  IF NOT EXISTS triage.bronze;
CREATE SCHEMA  IF NOT EXISTS triage.silver;
CREATE SCHEMA  IF NOT EXISTS triage.gold;
CREATE SCHEMA  IF NOT EXISTS triage.ops;
```
"Done" looks like: **Catalog** browser shows `triage` with four schemas under it.

### 2.2 Create a Volume for raw filings (replaces `data/raw/`)
```sql
CREATE VOLUME IF NOT EXISTS triage.bronze.raw_filings;
```
Files land at the path `/Volumes/triage/bronze/raw_filings/…`. This is governed storage:
same access controls and audit as tables, unlike loose files on disk.

### 2.3 Store secrets in a secret scope (never in code)
This is the Databricks equivalent of the GitHub Actions secrets in `daily-brief.yml`
(`ANTHROPIC_API_KEY`, `TWELVEDATA_API_KEY`). From your Mac:
```bash
databricks secrets create-scope triage
# The Anthropic key — only needed if you call Claude as an EXTERNAL model (see §6.2).
databricks secrets put-secret triage ANTHROPIC_API_KEY
# Optional market-data key (Twelve Data); omit and price blocks are simply skipped.
databricks secrets put-secret triage TWELVEDATA_API_KEY
# SEC requires a descriptive User-Agent on every EDGAR request (see config.yaml today).
databricks secrets put-secret triage SEC_USER_AGENT   # value e.g. "ATA research - you@example.com"
```
Read them in code as `dbutils.secrets.get("triage", "ANTHROPIC_API_KEY")`. They never
print in logs.

> **You may not even need `ANTHROPIC_API_KEY`.** Databricks can serve Claude natively
> (§6.1); you only need your own Anthropic key if you deliberately route to Anthropic's
> API as an *external* model. Decide in §6.

---

## 3. Bring the repo into Databricks

### 3.1 Connect the Git repo (so your Python is available in the workspace)
1. Left sidebar → **Workspace → Repos → Add Repo**.
2. Paste `https://github.com/JoshuAI-888/announcement-triage-agent` and clone.
3. You now have every `src/*.py` file available to import inside notebooks. **We reuse
   the pure logic** (`src/rank.py`, `src/flags.py`, `src/verify.py`, `src/normalise.py`,
   `src/models.py`, the prompt text in `prompts/classify_v3.md`) unchanged — only the
   *edges* (fetch, storage, model call, orchestration, UI) become Databricks services.

> Why reuse rather than rewrite? `rank.py`/`flags.py`/`verify.py` have no I/O — they're
> deterministic transforms with an eval harness proving their behaviour. Rewriting them
> would throw away that proof. We call them from a Databricks pipeline instead.

---

## 4. INGEST — Lakeflow Pipeline (replaces `fetch.py` + `edgar.py` + `market.py`)

**Goal:** every run, pull new EDGAR filings for the watchlist into a **bronze** Delta
table and drop the raw HTML/PDF into the Volume — with dedup and a watermark, but
*without* the hand‑rolled SQLite bookkeeping.

### 4.1 What "Lakeflow Pipeline" means (no prior knowledge)
A **Lakeflow Pipeline** (formerly Delta Live Tables) is a notebook where you declare
tables as functions. Databricks works out the order, runs them, retries on failure, and
records data‑quality "expectations". You write *what* each table is; it handles *how*.

### 4.2 Create the ingest notebook
1. **Workspace → Create → Notebook**, language **Python**, name `10_ingest_edgar`.
2. Paste this skeleton, then tell the **Assistant**: *"Fill in `fetch_ticker` by porting
   the request/parse logic from `src/adapters/edgar.py` in the connected repo; keep the
   SEC User‑Agent from the secret scope and the 8 req/sec rate limit from `config.yaml`."*
   The Assistant will adapt your existing, tested EDGAR code into this shape:

```python
import dlt   # the Lakeflow/DLT decorators
from datetime import datetime, timedelta, timezone
from pyspark.sql import functions as F

LOOKBACK_DAYS = spark.conf.get("triage.lookback_days", "1")  # set per run by the Job (§8)
UA = dbutils.secrets.get("triage", "SEC_USER_AGENT")

# Bronze: append raw filings seen in the lookback window. `@dlt.expect` is a
# data-quality gate; rows failing it are tracked, not silently dropped.
@dlt.table(name="triage.bronze.filings_raw", comment="Raw EDGAR filings, one row per filing")
@dlt.expect("has_id", "announcement_id IS NOT NULL")
@dlt.expect("has_published_at", "published_at IS NOT NULL")
def filings_raw():
    since = datetime.now(timezone.utc) - timedelta(days=int(LOOKBACK_DAYS))
    rows = fetch_edgar_window(since=since, watchlist=WATCHLIST, user_agent=UA)  # port of edgar.py
    return spark.createDataFrame(rows)   # columns: announcement_id, ticker, form_type, published_at, url, raw_path
```

3. **Dedup + watermark come for free.** Instead of the SQLite `processed` and
   `watermark` tables, make the *silver* table an idempotent MERGE keyed on
   `announcement_id`, so re‑running the same window never double‑classifies. Add:

```python
@dlt.table(name="triage.silver.filings", comment="Deduped, one row per unique filing")
def filings():
    return (
        dlt.read("triage.bronze.filings_raw")
        .withWatermark("published_at", "2 days")
        .dropDuplicates(["announcement_id"])
    )
```
The "last processed" high‑water mark is now just `MAX(published_at)` in silver — no
separate watermark row to keep in sync.

4. **Raw blobs → the Volume.** In `fetch_edgar_window`, write each filing's HTML/PDF to
   `/Volumes/triage/bronze/raw_filings/<announcement_id>.html` and store that path in the
   `raw_path` column. That's the direct replacement for `data/raw/`.

5. **Market prices (optional).** Port `src/market.py` the same way into a small
   `triage.silver.prices` table keyed on ticker+date, gated on the `TWELVEDATA_API_KEY`
   secret existing (best‑effort, exactly as today).

**"Done" for §4:** run the pipeline once (§8 wires the schedule; for now use the
pipeline's **Start** button) and confirm `SELECT count(*) FROM triage.silver.filings`
returns your window's filings, and files exist under the Volume.

---

## 5. STORE — the medallion tables (replaces `state.db` + `out/filings/*.json`)

You've already created bronze/silver above. The remaining SQLite tables map like this —
create them once in the SQL editor:

```sql
-- Append-only audit log (replaces the SQLite `audit` table; the trigger there
-- forbade UPDATE/DELETE — Unity Catalog gives you the same guarantee via table ACLs).
CREATE TABLE IF NOT EXISTS triage.gold.audit (
  announcement_id STRING, prompt_version STRING, model_id STRING,
  materiality STRING, confidence DOUBLE, rationale STRING, evidence_quote STRING,
  doc_type STRING, guardrail_flags ARRAY<STRING>,
  input_tokens BIGINT, output_tokens BIGINT, cost_nzd DOUBLE,
  classified_at TIMESTAMP
);

-- Cache of full verdicts, keyed by (id, prompt_version) — the direct analogue of the
-- SQLite `classification_cache`. A rerun with the same prompt reuses these: 0 LLM calls.
CREATE TABLE IF NOT EXISTS triage.gold.classification_cache (
  announcement_id STRING, prompt_version STRING, result_json STRING,
  model_id STRING, cost_nzd DOUBLE, cached_at TIMESTAMP
);

-- The final, query-ready verdicts the portal + Genie + email read (replaces out/filings/*.json).
CREATE TABLE IF NOT EXISTS triage.gold.verdicts (
  run_id STRING, announcement_id STRING, ticker STRING, form_type STRING,
  published_at TIMESTAMP, url STRING,
  tier STRING, materiality STRING, confidence DOUBLE,
  rationale STRING, evidence_quote STRING, doc_type STRING,
  flags ARRAY<STRING>, rank DOUBLE
);
```
Because these are Delta tables under Unity Catalog, you automatically get column‑level
**lineage** (filing → classification → email) and an **audit** system table — the
"examiner‑ready trail" the governance node in the diagram is about, with no extra code.

---

## 6. CLASSIFY — Mosaic AI Model Serving + AI Functions (replaces `classify.py` + `providers.py`)

This is the heart of it: run the **frozen** `prompts/classify_v3.md` against each new
filing and get back `{materiality, confidence, rationale, evidence_quote, doc_type,
guardrail_flags}` — the same JSON `src/models.py::Classification` defines today.

### 6.1 Make Claude available as an endpoint (the native path — recommended)
1. Left sidebar → **Serving → Create serving endpoint** (or **Machine Learning →
   Serving**). Choose a **Foundation Model** and pick a **Claude** model. Name the
   endpoint `claude-triage`.
   - Databricks exposes Anthropic Claude as a foundation model you can serve without
     managing your own key. This becomes the diagram's **Mosaic AI Model Serving** node.
   - If your workspace/region doesn't list Claude natively, use the **External Model**
     option and point it at Anthropic using the `ANTHROPIC_API_KEY` secret from §2.3.
     Ask the Assistant: *"Create an external model serving endpoint for Anthropic Claude
     using secret `triage/ANTHROPIC_API_KEY`."*
2. Match the model to today's config: `runtime_config.json` uses
   `claude-haiku-4-5-20251001` for bulk classification. Pick the equivalent current
   Claude model for cost parity, and confirm with the Assistant which id is live.

### 6.2 Put the AI Gateway in front (spend caps + fallback + guardrails)
On the endpoint's page, open **AI Gateway** and set:
- **Rate limit / spend cap** — mirrors `thresholds.escalate_*` and your cost discipline.
- **Fallback** — if the primary is unavailable or low‑confidence, escalate to a stronger
  Claude model. This is the config‑driven fallback the current `providers.py` fakes with
  try/except.
- **Guardrails / PII** — enable the safety filters. Central logging is automatic.

This page **is** the diagram's **Unity AI Gateway** node. No code — it's configuration.

### 6.3 Classify with an AI Function, reusing the frozen prompt
Databricks SQL has `ai_query(endpoint, prompt)` — call your endpoint straight from SQL.
The trick that keeps quality identical: **load the prompt text from the repo, don't
retype it.**

In a notebook cell:
```python
# Read the FROZEN prompt verbatim from the connected repo — do not edit it.
with open("/Workspace/Repos/<you>/announcement-triage-agent/prompts/classify_v3.md") as f:
    CLASSIFY_PROMPT = f.read()
spark.conf.set("triage.classify_prompt", CLASSIFY_PROMPT)
```
Then classify only *uncached* filings (the reuse rule from `run_pipeline`):
```sql
-- New filings this window that have no cached verdict for the current prompt version.
CREATE OR REPLACE TEMP VIEW to_classify AS
SELECT s.* FROM triage.silver.filings s
LEFT JOIN triage.gold.classification_cache c
  ON c.announcement_id = s.announcement_id AND c.prompt_version = 'v3'
WHERE c.announcement_id IS NULL;

-- One governed model call per new filing, through the endpoint + AI Gateway.
CREATE OR REPLACE TEMP VIEW fresh_verdicts AS
SELECT announcement_id, ticker, form_type, published_at, url,
       ai_query('claude-triage',
                CONCAT('${triage.classify_prompt}', '\n\nFILING:\n', filing_text)) AS result_json
FROM to_classify;
```
Then parse `result_json` (it's the same JSON schema as today), append to `audit`, write
to `classification_cache`, and you're done. Ask the Assistant: *"Parse `result_json` into
the columns of `triage.gold.audit` and MERGE into `classification_cache`."*

> **PDFs / OCR.** Today `pdf.ocr_enabled` uses `pypdf` then Claude OCR as a fallback.
> On Databricks, use `ai_parse_document()` (Databricks' built‑in document parser) for the
> text layer and fall back to a Claude vision call through the same endpoint for scanned
> PDFs. Same tiered logic, native functions.

> **Agent Bricks alternative.** Instead of hand‑wiring `ai_query`, you can build this as
> an **Agent Bricks** "Information Extraction" agent in the UI and point it at the same
> prompt. Databricks ships a public **SEC document‑intelligence** template that does
> almost exactly this — it's the closest turnkey match. Use whichever you prefer; the AI
> Function path above gives you the most control and mirrors the current code 1:1.

### 6.4 Verify + rank + flags (reuse the tested Python)
In the *same* pipeline, after verdicts exist, call your existing pure functions:
```python
from src.verify import verify           # guardrail checks — unchanged
from src.rank import tier_of, rank_score  # tiering ("material wins") — unchanged
from src.flags import plain_english     # flag labels — unchanged
```
Apply them as a UDF/transform to produce `triage.gold.verdicts`. **Do not reimplement
tiering in SQL** — `tier_of` is the source of truth the portal's `lib/tier.ts` already
mirrors; call the real thing so the email, portal, and Genie all agree.

**"Done" for §6:** `SELECT tier, count(*) FROM triage.gold.verdicts GROUP BY tier`
returns material / needs_look / immaterial counts that match a same‑day run of the old
pipeline (you'll prove this in §11).

---

## 7. EVAL — MLflow 3 (replaces `checks/`, `evals/`, `run_log.jsonl`)

**Goal:** keep the guarantee that a prompt or model change can't quietly regress quality.
Today that's the offline harness in `checks/` scored against the frozen gold corpus.

1. **Tracing.** Wrap the classification call with MLflow tracing so *every* model call is
   an OpenTelemetry span — the structured replacement for `out/run_log.jsonl`. In a
   notebook: `import mlflow; mlflow.set_experiment("/triage/classification")` and enable
   autolog; the serving endpoint's calls appear as traces.
2. **LLM‑judge eval.** Register the gold corpus as an **MLflow evaluation dataset**, then
   use `mlflow.genai.evaluate(...)` with judges (built‑in correctness + a custom
   `make_judge()` for materiality precision/recall). This is the direct analogue of
   `checks/check_eval.py`; ask the Assistant to port the pass/fail thresholds from
   `checks/_harness.py`.
3. **Prompt registry.** Register `classify_v3.md` as a versioned prompt in MLflow so
   "which prompt ran" is tracked per run — replacing the string `prompt_version: "v3"`.
4. **CI gate.** Make the eval a required step in the Job (§8): if precision/recall drop
   below the frozen thresholds, the run **fails** and no brief is produced. Same
   contract as the current `run-eval.yml` gate.

---

## 8. ORCHESTRATE — Lakeflow Jobs (replaces GitHub Actions + `ci_gate.py`)

**Goal:** run the whole thing daily, with retries, on a schedule — and support a manual
"backfill a past window" run, exactly like the portal's *Run now* / *Backfill…* buttons.

1. Left sidebar → **Workflows → Create Job**, name `triage-daily`.
2. Add tasks in order, each pointing at the notebook/pipeline you built:
   `10_ingest` (the Lakeflow Pipeline) → `20_classify` → `30_verify_rank` →
   `40_eval_gate` (MLflow; **fail the job if it fails**) → `50_render_brief` (§9) →
   `60_stage_draft` (§10). Databricks runs them in dependency order with auto‑retry.
3. **Schedule.** In the Job's **Schedule** panel set a cron for the digest window. Today
   the cron fires around 06:00 NZT (17:00/18:00 UTC). Use `0 0 18 * * ?` (adjust for
   NZDT/NZST as the workflow comment notes). **Serverless** compute means it scales to
   zero between runs — no wasted runners, which is exactly the problem the current
   `daily-brief.yml` cron comment describes.
4. **Parameters for backfill.** Add two Job parameters `as_of_date` and `lookback_days`
   (defaults empty / `1`). The ingest notebook already reads `triage.lookback_days`; wire
   `as_of_date` so a backfill run classifies a past window and **does not advance the
   watermark** (mirrors the `--as-of` isolation rule in `src/run.py`). The portal's
   *Backfill…* control will pass these (see §10.3).

The Job's **decide digest/intraday/skip** logic (`scripts/ci_gate.py`) becomes a tiny
first task or a Job condition. Ask the Assistant: *"Port `scripts/ci_gate.py` into a
notebook task that sets a Job task value `action`, and make later tasks conditional on
it."*

---

## 9. RENDER + SERVE — brief, Lakebase, Genie

### 9.1 Render the HTML brief (reuse `render_email.py`)
`src/render_email.py` and `src/brief.py` are pure string builders. Call them from the
`50_render_brief` task against `triage.gold.verdicts`, and write the HTML to the Volume
`/Volumes/triage/bronze/raw_filings/briefs/<run_id>.email.html` (or a dedicated
`briefs` Volume). No rewrite — same brief, new storage location.

### 9.2 Lakebase for small mutable state (replaces `runtime_config.json` + logs the app writes)
The portal needs to *write* things (edit config, queue a draft, record run status).
Delta is append‑optimised, not row‑update‑optimised, so put mutable app state in
**Lakebase** (serverless Postgres, governed by Unity Catalog):
- **Create** a Lakebase instance: left sidebar → **Compute → Lakebase / OLTP → Create**
  (ask the Assistant for the exact current path).
- Tables: `runtime_config` (one JSON row — the analogue of `runtime_config.json`),
  `cost_ledger`, `run_status`, `draft_queue`.
The portal reads/writes these with ordinary Postgres — much closer to a normal web app
than today's "commit `runtime_config.json` to `main` via the GitHub API".

### 9.3 Genie (natural‑language querying) — this is new, and free once tables exist
1. Left sidebar → **Genie → New Genie space**.
2. Add the tables `triage.gold.verdicts` and `triage.gold.audit`.
3. Add a couple of example questions ("show high‑materiality filings with confidence
   below 0.7") so Genie learns the vocabulary.
4. Test it in the Genie chat. It returns governed SQL + a table/chart. You can embed
   this space in the portal (§10) so an analyst never has to write SQL.

---

## 10. APP — Databricks Apps (replaces Vercel)

**Goal:** host the existing Next.js operator portal *inside* the workspace, reading the
gold tables and Lakebase directly instead of the GitHub API.

### 10.1 Reality check on the framework
Databricks Apps officially supports **Python (Streamlit/Dash/Flask/FastAPI)** and
**Node**; **Next.js runs via the Node runtime but is an unofficial path.** Two honest
options — decide with the checklist below:

| Option | Effort | When to choose |
|---|---|---|
| **A. Deploy the existing Next.js app as a Node app** | Low‑medium | You want to keep the current UI (the filings table, filters, the "On Databricks" diagram) as‑is |
| **B. Rebuild the portal as a Databricks‑native Python app (Dash/Streamlit)** | Medium‑high | You want the officially‑supported, longest‑lived path and don't mind re‑skinning |

For a first migration, **do Option A** to prove the end‑to‑end flow, then consider B
later. The diagram itself notes Next.js is "unofficial via the Node runtime" — that
caveat is deliberate.

### 10.2 Deploy (Option A)
1. Left sidebar → **Compute → Apps → Create app** (Node).
2. Point it at the `dashboard/` folder in the connected repo.
3. Replace the app's data layer:
   - The portal currently reads `run_log.jsonl` / `briefs` / `filings` via the **GitHub
     API** (`process.env.GITHUB_TOKEN`, `GITHUB_REPO`). Swap those reads for Databricks
     SQL queries against `triage.gold.*` and Lakebase. Ask Claude Code (in this repo) to
     do the swap: *"In `dashboard/lib/dataSource.ts`, replace the GitHub‑API fetchers
     with Databricks SQL connector queries against `triage.gold.verdicts` and the
     Lakebase `runtime_config` table."*
   - `PORTAL_SESSION_SECRET` HMAC cookie gate → replace with **Databricks OAuth** (Apps
     handle auth for you; the current password gate becomes unnecessary).
4. Attach resources: in the app's config, grant it the serving endpoint, the Genie
   space, and the Lakebase instance as **governed resources** — so the app has no raw
   secrets, just scoped access.

**"Done" for §10:** the portal loads inside the workspace at the app's URL, shows the
latest run from `triage.gold.verdicts`, and the Config page writes to Lakebase.

### 10.3 Wire the buttons
- **Run now / Backfill…** → call the Databricks **Jobs API** to trigger `triage-daily`
  with `as_of_date`/`lookback_days` params (replaces the `workflow_dispatch` call).
- **Draft the email** → write a row to Lakebase `draft_queue`. **A human still sends it.**
  Keep the draft‑only rule: the app must never call an SMTP/Gmail send API.

---

## 11. CUT OVER SAFELY — parallel run, then switch

Do **not** turn off GitHub Actions on day one. Run both for a week and compare.

1. **Parallel week.** Leave `daily-brief.yml` running as today. Each morning, run
   `triage-daily` on Databricks for the same window.
2. **Compare.** For the same date, diff the two `verdicts` sets:
   - Same set of `announcement_id`s ingested?
   - Same `tier` per filing? (Investigate any disagreement — usually an ingest‑window or
     prompt‑loading bug, not a model difference.)
   - Material counts equal to the email's material count? (The frozen tiering rule must
     hold on both sides.)
   Ask Genie: *"List filings where the Databricks tier differs from the GitHub tier for
   2026‑08‑12."* (Load both as tables to compare.)
3. **Eval parity.** Run the MLflow eval (§7) and confirm precision/recall match the
   `evals/eval_summary.json` numbers from the current harness.
4. **Flip.** When a week agrees: point the "source of truth" portal at Databricks,
   disable the GitHub Actions schedule (comment out the `schedule:` block in
   `daily-brief.yml`), and keep the repo as the code home + eval history.
5. **Rollback plan.** Because you didn't delete anything, rollback is just: re‑enable the
   GitHub cron and point the portal back at the GitHub API. Keep this option for 2–3
   weeks.

---

## 12. Cost, governance, and the "why" for each choice

- **Cost.** Serverless Jobs + scale‑to‑zero serving means you pay per run, not for idle
  runners. The AI Gateway spend cap is your hard ceiling — set it to your current daily
  Claude spend plus headroom. The `classification_cache` reuse (unchanged logic) keeps
  reruns at **0** model cost.
- **Governance (the whole right edge of the diagram).** Unity Catalog gives you, with no
  extra code: column‑level lineage (filing → field → verdict → email), an audit system
  table, access control per schema, and a Model Registry. This is the part that's *hard*
  to bolt onto the current GitHub‑Actions‑plus‑SQLite setup and *free* on Databricks —
  it's the strongest single reason to migrate.
- **What you deliberately keep from the repo:** `prompts/classify_v3.md` (frozen),
  `rank.py`/`flags.py`/`verify.py`/`normalise.py`/`models.py` (tested pure logic), the
  gold eval corpus, `render_email.py`/`brief.py`. The migration changes *where code runs
  and where data lives*, not *what makes a filing material*.

---

## 13. One‑screen checklist

- [ ] Workspace created; Unity Catalog on; CLI configured (`databricks current-user me`)
- [ ] Catalog `triage` + schemas bronze/silver/gold/ops + Volume `raw_filings` created
- [ ] Secret scope `triage` holds `SEC_USER_AGENT` (+ optional `ANTHROPIC_API_KEY`, `TWELVEDATA_API_KEY`)
- [ ] Repo cloned into **Repos**
- [ ] Lakeflow Pipeline ingests EDGAR → `bronze.filings_raw` → `silver.filings` (deduped)
- [ ] Gold tables `audit`, `classification_cache`, `verdicts` created
- [ ] `claude-triage` serving endpoint live; **AI Gateway** spend cap + fallback + guardrails set
- [ ] AI Function classifies uncached filings using the **frozen** prompt; reuse cache works (rerun = 0 calls)
- [ ] `verify`/`tier_of`/`flags` reused from `src/` to build `gold.verdicts`
- [ ] MLflow tracing + gold‑corpus eval gate wired; thresholds match `checks/`
- [ ] Job `triage-daily` scheduled (serverless) with `as_of_date`/`lookback_days` params
- [ ] Brief rendered from `render_email.py`; Lakebase holds config + draft_queue; Genie space answers questions
- [ ] Portal deployed as a Databricks App, reading gold + Lakebase, buttons hit the Jobs API, **email stays draft‑only**
- [ ] One‑week parallel run agrees; then flip the schedule off and keep rollback for 2–3 weeks

---

### How to actually *do* this with Claude + Genie (the short version)
1. Open each numbered section, copy its code block into a **Databricks Assistant** cell,
   and say **"adapt this to my workspace and run it."** The Assistant is Claude with your
   schema in context — it fills the gaps this document leaves as `<…>`.
2. For anything that touches the repo's Python (porting `edgar.py`, swapping the portal's
   data layer), use **Claude Code here in the repo** so the edits are version‑controlled.
3. Once the gold tables exist, use **Genie** for every "let me check the data" question
   instead of writing SQL by hand — including the parallel‑run comparison in §11.
4. When a product screen doesn't match this doc, ask the Assistant **"what's the current
   path for X?"** rather than guessing — Databricks' UI moves faster than any runbook.
