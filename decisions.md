# decisions.md — decision log

A running record of non-obvious decisions, why they were made, and what was
deliberately *not* done. Newest section first. Dates are absolute (NZT).

---

## 2026-08-05 — Descriptive self-explaining brief + market data + delivery routine

### Context / trigger
The brief/portal were terse and used internal jargon. Owner wanted each item to
explain itself (company, industry, competitive edge, price + 7-day trend, plain-
English flags + why), a per-run table of **every** filing with the *why*, and
**clickable source URLs everywhere** — no raw codes.

### Decisions
1. **Portal iframes the brief HTML** (key finding from the Explore agents): the
   dashboard renders no items in React — `today`/`versions` embed the committed
   `out/briefs/*.email.html`. So company profile / price / sparkline / plain-flags
   were built **once in the Python renderer** and appear in both email and portal
   for free. Only one new React page (`/filings`) + the flag-badge relabel were
   native work.
2. **No `C1/C2/C3` exist** — those are internal build-task IDs (AUTONOMY.md). The
   only real codes are **G1–G6**; all are mapped to plain English in a single
   source of truth (`src/flags.py`) mirrored in `dashboard/lib/flags.ts`. A check
   asserts no raw `G#_`/`insufficient_info` literal survives into rendered output.
3. **Market data = Twelve Data** (owner's "keyed free API" choice), config-driven
   (`config.yaml market:` block, `TWELVEDATA_API_KEY`). Best-effort/never-raises:
   no key or API error → price block simply omitted. **Material items only** (0–5/
   day) to bound cost. "Price" = latest close vs prior close (US market shut at
   06:00 NZT) + a **mail-safe HTML bar sparkline** (not inline SVG — Gmail strips it).
4. **Company profile = Claude-generated** (owner's choice): EDGAR **SIC** for
   authoritative industry + one Claude-haiku call for a factual business + edge
   line, labelled "AI-generated context — verify before relying", no advice
   language (G6 still guards). **Pinned to Claude** regardless of `run.provider`.
   Cached per ticker in committed `data/company_profiles.json` (committed back by
   `daily-brief.yml`, so a name is generated/paid for once). Fixed a split bug —
   the profile now asks Claude for labelled `Business:`/`Edge:` lines (the naive
   sentence split broke on "Inc."); fallback splitter is abbreviation-safe.
5. **Per-run all-filings artifact** `out/filings/<date>.json` (un-ignored, committed
   by the workflow) powers a native portal **"This run"** page (sortable, clickable
   sources, plain-English classification + flag chips). The email carries a compact
   version of the same table. `run_pipeline` now returns `all_items`; `publish`
   writes the artifact.
6. **Concurrency:** two Sonnet subagents (Python vs `dashboard/`) on frozen
   contracts (flag vocab + `out/filings` shape) — verified byte-identical between
   `src/flags.py` and `dashboard/lib/flags.ts`, and the JSON writer vs the TS types.
7. **Verified live** with the owner's real key: AAPL $308.65 +1.72% with a 7-day
   series, real Claude profile, plain-English flags, all-filings table, no code
   leaks. A rendered sample was sent to the owner.

### Delivery routine — corrected
8. The morning **brief generation** already runs fully server-side on **GitHub
   Actions** (no device needed) — that requirement was already met. The **Gmail
   draft + message** step I'd set up was a **Claude Code local scheduled task**
   (`~/.claude/scheduled-tasks/…`), which only runs while that app is open and does
   NOT appear in claude.ai routines — an honest limitation surfaced to the owner.
   Chosen fix (owner picked): recreate delivery as a **claude.ai routine** (server-
   side, keeps the Gmail *draft* review, reads the brief from the repo via the
   GitHub connector). Disabled the local Claude Code task to avoid duplicate drafts;
   handed the owner the paste-ready routine prompt + connector steps.

### Not done (deliberate)
- No price/profile on immaterial filings (cost bound) — the all-filings table shows
  industry (free SIC) + classification + why, not price.
- No runtime_config UI toggles for price/profiles (kept in `config.yaml` to avoid
  schema-mirror churn); they degrade gracefully if the key is absent.

## 2026-08-04 / 08-05 — PDF ingestion, OCR, portal, Claude routine, deploy

### Context / trigger
The daily fetch cache had 4 giant "text" files (77 / 62 / 34 / 12 MB). Diagnosis:
they are **ARS filings (annual report to shareholders) delivered as PDFs**, whose
raw `%PDF…` byte stream was being run through the HTML text extractor and stored
as `body_text` — truncating the real signal and bloating the cache. This is the
root cause of the "truncation" the owner asked about.

### PDF handling — decisions
1. **Tiered pipeline, not a blanket skip** (`EdgarAdapter._fetch_pdf_document`):
   skip-by-form → pypdf text extraction → Claude OCR → metadata placeholder.
   *Why:* a blanket "skip all PDFs" throws away real narrative; most event-form
   PDFs have a clean text layer. A blanket "OCR everything" is expensive and
   re-downloads huge redundant files.
2. **Skip-by-form set = `{ARS}`** (`_SKIP_EXTRACTION_FORMS`). *Why:* an ARS is a
   glossy duplicate of the separately-filed 10-K (which files as HTML+XBRL), is
   never itself the event, and is the large-file offender. Kept deliberately
   narrow so nothing material is skipped.
3. **A skipped/failed PDF is never dropped.** It flows through classify/rank on a
   synthesised metadata body carrying the submissions-JSON signal that is
   independent of the document body — form + **8-K item codes** (2.02 results,
   1.01 agreement, 5.02 departures, 8.01 other) + description. With only metadata
   to ground on it stays low-confidence and routes to *Needs a look*. *Why:* "don't
   miss anything important" — surface it for human review rather than silently
   calling it immaterial.
4. **Added `pypdf` (6.14.2)** — the only new dependency (AUTONOMY S6). *Why:* BSD,
   pure-Python, **zero transitive deps**; the leanest option. Rejected
   pymupdf4llm (AGPL — problematic for a deployed/hosted tool), marker/docling
   (ML models, hundreds of MB, GPL/size — overkill for a 15-min CI job).
5. **OCR is PINNED to Claude regardless of `run.provider`** (`_OCR_MODEL =
   claude-haiku-4-5`, `ANTHROPIC_API_KEY`, anthropic SDK directly). *Why:* only
   Claude reads PDFs natively in one call; OpenAI needs a rasterize/Responses-API
   detour and GLM's text model can't. `ANTHROPIC_API_KEY` is always present (the
   core secret), so OCR works even when the daily classifier is openai/glm. This
   also keeps the cross-provider eval symmetry intact — the bulk classifier path
   is unchanged; only the rare scanned PDF is handed to Claude.
6. **OCR is best-effort and never raises.** No key / SDK / API error falls back to
   a placeholder. *Why:* it runs inside the shared document-fetch path; it must
   never take down the pipeline.
7. **`_MAX_PDF_BYTES = 15 MB`** cap before extraction/OCR. *Why:* past a few MB
   both pypdf and base64-for-OCR get slow/expensive and won't summarise faithfully.
8. **`pdf.ocr_enabled` toggle (default ON)**, editable from the portal Config
   page, persisted to `runtime_config.json`. *Why:* the owner wanted the ability
   to turn Claude OCR off and have it stick. **Deliberately excluded from the eval
   fingerprint** (`eval_fingerprint`/`fingerprint_from` unchanged) — the eval runs
   on the frozen gold corpus and OCR only affects rare live image-PDFs, so
   toggling it must not falsely flip the trust banner to stale. Default left ON
   per owner instruction (cost is ~NZ$0.0035/scanned page; rare on EDGAR).
9. **Decision log `out/pdf_log.jsonl`** — one row per PDF decision, un-ignored in
   `.gitignore` and committed by `daily-brief.yml` alongside `run_log.jsonl`; read
   in the portal at **/pdf-log** via `GET /api/pdf-log`. *Why:* the owner wanted
   PDF/OCR handling retrievable in the portal. The normal HTML path logs nothing.

### Data / gold decisions
10. **Purged 185 MB of stale `%PDF`-garbage text caches** (4 files) from
    `data/raw/`; 237 MB → ~52 MB. Only files literally starting with `%PDF-` were
    removed; they are regenerable caches, not source data.
11. **Regenerated the 4 ARS gold rows** — `data/gold/candidates.csv` source-fact
    columns (`char_count`, `truncated`) and `evals/gold_corpus.jsonl` bodies — to
    the clean placeholders. **Owner labels were NOT touched** (Prohibition #1 / S4:
    the agent never writes gold judgements). Patched only the 4 affected lines
    (byte-identical elsewhere). *Consequence:* a future eval would score those 4
    ARS rows slightly differently (cleaner). This does **not** auto-flip the trust
    banner (the corpus isn't in the fingerprint) — a re-eval is **optional/owner
    cadence** and was intentionally NOT run here (avoids ~NZ$10-15 unrequested
    spend; owner controls eval cadence via the portal **Run eval** button).

### Build / process decisions
12. **Concurrent build via two Sonnet subagents on disjoint files** (Python core
    vs `dashboard/`), Opus orchestrating. Codex was initially chosen for the Node
    stream but **swapped to Sonnet per owner instruction**. Contracts (config key,
    log path/shape, prompt file) were frozen before launch so the streams couldn't
    diverge.
13. **Regenerated `config/runtime_config.schema.json`** from the pydantic model so
    all three schema surfaces (pydantic / JSON mirror / `dashboard/lib/schema.ts`)
    agree on `pdf.ocr_enabled`.
14. **New offline check `checks/check_pdf.py`** (80 assertions, no network; OCR &
    byte-fetch monkeypatched). Suite: **17/18 green**; the one red (`check_batch`,
    Batch-API custom_id reconciliation) is pre-existing and unrelated to this work.

### Verification (done, not assumed)
15. **Live OCR test:** built an image-only PDF (no text layer) → pypdf got 0 chars
    → Claude OCR transcribed it accurately (revenue / +15% / Item 2.02 / guidance)
    for **NZ$0.0035**; with the toggle OFF, **zero** API calls were made and it
    routed to `placeholder_ocr_disabled`.
16. **Toggle persistence proven executably:** `pdf.ocr_enabled=false` round-trips
    through the real `validateRuntimeConfig` into the committed value (version
    bumped); stray keys rejected (`extra=forbid`).
17. **Deploy verified via Vercel API + HTTP:** commit `5a8f984` READY in
    production, build clean, **no runtime errors**; `/pdf-log`, `/config` redirect
    to login (gated), `/api/pdf-log` & `/api/system-prompt` return 401 (deployed +
    protected).

### Claude delivery routine
18. **A morning routine already existed** (`morning-announcement-brief`, 06:50 NZT
    daily, enabled) — I **polished it rather than duplicating**: added the /pdf-log
    link and tidied the `run_log.jsonl` path. **Draft-only, never sends** (creates
    a Gmail draft the owner reviews and sends themselves). Reads local repo files;
    does not read/write `data/gold/`.

### Security posture — verified, no change made
19. **Vercel SSO deployment protection is already ENABLED** (`all_except_custom_domains`),
    and the app has its own password gate (default `milfordsec`). The plan's
    "deployment protection on" requirement is satisfied. I did **not** modify any
    deployment-protection / security setting — that is an owner-owned control (and
    a security setting I don't flip unilaterally). To rotate the portal password,
    use the portal's password settings; to change Vercel protection, use the Vercel
    project settings.

### System prompt visibility (owner request)
20. The active classification prompt (`classify_v3`) is now **visible but
    read-only** on the Config page (`GET /api/system-prompt`), with a caption
    noting that editing it is re-eval-gated and not exposed there. *Why:* the owner
    saw it referenced but not shown; editing the classifier prompt must stay behind
    the re-eval gate, so it is shown, not made editable here.
