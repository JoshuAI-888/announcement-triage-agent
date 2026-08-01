# PROGRESS.md — autonomous batch log

Maintained per `AUTONOMY.md` §3. Append one block per sub-step, as it happens.

**Batch A started:** 2026-08-01 11:54 UTC
**Reference exchange:** EDGAR (set at build time in `config.yaml`)
**Cumulative API spend, batch A:** NZ$0.00 (no LLM calls occur before B1)

---

## A.0 carried-over state (context, not a sub-step)

A previous, uncommitted session left `src/models.py`, `src/store.py`,
`src/fetch.py` and `src/adapters/edgar.py` in the working tree, switched the
reference exchange from NZX to EDGAR, and amended `SPEC.md` §5.1 to fold
`native_id` into the `announcement_id` hash. None of it was committed, checked
or verified, and `checks/` and `PROGRESS.md` did not exist.

Consequence for the §1 loop: for A1 and A2 the check could not be written
before the implementation existed, because the implementation was already
there. It was written before being run, and against `SPEC.md` rather than
against the code. Where a check passed first time, I re-ran it against the
last committed version of the same file to confirm it discriminates — recorded
per sub-step below.

---

## A.1 skeleton + schemas
status: pass
check: checks/check_skeleton.py
result: 119 assertions — repo skeleton (SPEC §2), every `config.yaml` tunable (SPEC §4), `Announcement`/`Classification`/`Entities` field lists matching SPEC §5 exactly, `compute_id` equals sha256 of `exchange|ticker|iso|headline|native_id`, and fail-loud rejection of missing/unknown/out-of-enum values. Exit 0.
commit: f288583
elapsed: 8m
spend: NZ$0.00
notes: Check discriminates — run against `git show HEAD:src/models.py` (pre-`native_id`) it fails at "Announcement fields match SPEC §5.1 exactly" after 72 passing assertions. `README.md` is listed in SPEC §2 but is increment 10 and owner-written, so the check does not require it. Reference adapter switched to EDGAR: `src/adapters/nzx.py` deleted.

## A.2 store + fetch
status: pass
check: checks/check_fetch.py
result: 44 assertions. Live EDGAR, 20 tickers, 30d lookback, clean slate: run 1 = 3013 new / 0 duplicate, run 2 = **0 new**, run 3 (watermark rolled back, whole window re-delivered) = 3013 seen / **0 new** / 3013 duplicate. Plus SPEC §12 semantics on a throwaway DB: append-only audit enforced by sqlite triggers, one watermark row per exchange, naive datetimes refused, dead-letter capture. Exit 0.
commit: 5f64e27
elapsed: 22m
spend: NZ$0.00
notes: Run 2 alone is a weaker proof than it looks — the watermark filters the feed before dedupe is ever consulted, so it returns 0 without the announcement_id hash doing any work. Added run 3, which rolls the watermark back to the bootstrap point so EDGAR re-delivers all 3013 filings and only the hash can stop them being written twice. That is the property SPEC §12 actually asks for (at-least-once, "re-running any window must be safe"). `fetch()` now returns a `FetchResult(new, duplicate, seen, watermark_advanced)` instead of a bare int so the replay assertion can distinguish the two; it also takes optional `db_path` / `raw_dir` so the check runs from a clean slate rather than against the build's own state.db. No S2: zero dead-letters, no throttling, no auth required — data.sec.gov is key-free and the configured User-Agent carries a contact address as EDGAR requires. The build's own store was then populated by two real runs (3013 new, then 0 new); 3013 raw JSON in data/raw/.

## A.3 normalise + doc_type map + stub adapter
status: pass
check: checks/check_normalise.py
result: 258 assertions. 3013 raw payloads on disk; 120 normalised across 26 native form types, 18 issuers and 8 canonical doc_types. Every required SPEC §5.1 field populated, every announcement_id unique and recomputing to the documented hash, body_text plain and whitespace-normalised, truncation verified exactly against the cached pre-truncation text. Stub adapter satisfies the protocol and returns []. Unknown native type -> admin with one warning naming the form. Exit 0.
commit: 328a70e
elapsed: 41m
spend: NZ$0.00
notes: Two failed attempts before green, both real bugs, neither fixed by touching the check.
  (1) Every XML-backed form (3, 4, 144, SCHEDULE 13G, 13F-HR) normalised to empty text. Cause: `<meta>` and `<link>` are void elements with no end tag, so the HTML extractor's skip-depth counter incremented and never decremented, discarding everything after the first `<meta>`. Plain-HTML EDGAR fragments have no `<head>`, which is why 8-K/10-Q passed and hid it. Fix: skip only tags whose content is genuinely non-visible (script/style/title) and handle self-closing tags separately.
  (2) One truncated BAC 424B2 ended in whitespace because the 60000-char cut landed mid-run. Fix: rstrip after truncating. The check's truncation assertion was wrong too — it demanded `char_count == truncate_input_chars` exactly, which an rstrip legitimately breaks — so it was replaced with a stricter one that compares body_text against the cached pre-truncation text rather than inferring from the length.
  Selection: 3013 filings over 30 days is 84% 424B2 structured-note pricing supplements from two issuers, so normalising everything would cost ~3000 requests and produce a labelling queue that is mostly one form type from one desk. `select_raw_payloads` takes the most recent filings round-robin across native form types (`normalise.sample_limit: 120` in config.yaml). That is a coverage rule and makes no materiality judgement.
  Document text is fetched once per filing and cached as `data/raw/<id>.txt` (gitignored), so re-normalising the corpus costs no further EDGAR requests.
  `config/doc_type_map.yaml` covers all 21 corpus form types explicitly; the `admin` fall-through is reserved for genuinely unseen types.

## A.4 export unlabelled candidates.csv
status: pass
check: checks/check_candidates.py
result: 11 assertions. `data/gold/candidates.csv` holds 120 candidates across 18 issuers and 8 doc_types. Header opens with the SPEC §13.1 gold columns in order. All 9 owner-only columns (4x `label_*`, `slice_tag`, `difficulty`, `labelled_at`, `labeller`, `pass_number`) verified EMPTY on every row — 1080 cells, one distinct value: the empty string. Identifying columns verified against the canonical record they point at. Exit 0.
commit: A4
elapsed: 14m
spend: NZ$0.00
notes: No labels were written, suggested or inferred, and `data/gold/gold.csv` and `data/gold/RUBRIC.md` were not created — both remain absent for the owner to write. Exporter lives at `evals/export_candidates.py`; the export is the eval-set concern of SPEC §13.1, and putting it there leaves `src/` exactly as SPEC §2 specifies. Five source-fact columns (headline, native_doc_type, char_count, truncated, source_url) are appended AFTER the §13.1 set so the owner can read and open each filing while labelling; the file stays a prefix-compatible superset of the gold schema. Rows are ordered by publication time, newest first — no ordering, filtering or emphasis in this file encodes a view about materiality. `issuer_price_sensitive_flag` is empty throughout because EDGAR supplies no such signal (SPEC §5.1), which is an absent source field rather than an unmade judgement.

---

## Batch A complete

All four sub-steps green; `python -m checks.run_all` runs 4 checks / 432 assertions and exits 0.
Cumulative API spend: **NZ$0.00** — Batch A makes no LLM calls; the first is B1.
Elapsed: 1h25m against a 2.5h budget.

**Stopped here, as instructed.** Next in the §7 graph is the HUMAN GATE: the owner
writes `data/gold/RUBRIC.md` and labels `data/gold/gold.csv`. B1 does not start
until that exists.
