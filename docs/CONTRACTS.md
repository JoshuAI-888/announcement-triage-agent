# CONTRACTS.md — interfaces frozen for the deploy build (Phase 0)

Every stream (Python core, Vercel app, CI/CD) builds against these. Do not change a
shape here without updating this file and the check that guards it. Prohibition #1 / S4
is absolute: **nothing in the configuration or delivery surface may read or write
`data/gold/`.**

---

## 1. `runtime_config.json` — the single source of truth (UI-editable overlay)

- Canonical schema: `config/runtime_config.schema.json` (draft-07), **generated from**
  `src/config_schema.py:RuntimeConfig`. Regenerate on model change:
  ```
  .venv/bin/python -c "import json,pathlib; from src.config_schema import RuntimeConfig; \
    s=RuntimeConfig.model_json_schema(); s['\$schema']='http://json-schema.org/draft-07/schema#'; \
    pathlib.Path('config/runtime_config.schema.json').write_text(json.dumps(s,indent=2)+'\n')"
  ```
- Python validator (authoritative): `src/config_schema.py`
  - `validate(raw) -> RuntimeConfig` — runs `assert_no_gold_fields` then pydantic (extra=forbid).
  - `load_runtime_config()`, `apply_overrides(base_config, rc)`, `eval_fingerprint(rc, base_config)`.
- **It is an OVERLAY on `config.yaml`**, not a replacement. `apply_overrides()` merges the
  editable surface onto the base; everything else in config.yaml is untouched. The merged
  config carries a `_runtime` block (draft email/prompt, news_mode, items_shown, theme,
  schedule, providers) for downstream consumers.
- **Node UI must mirror the validation** (schema + the email/HH:MM regexes + the
  no-gold-field scan). Same rejects, same messages in spirit.
- `version` (int, ≥1) is bumped on **every** committed edit — optimistic concurrency + audit.
- `eval_fingerprint(rc, base)` is a 16-hex hash of the eval-affecting fields (prompt version,
  prompt override, provider, model id, pricing). Trust is **stale** when it differs from the
  fingerprint stored in `evals/eval_summary.json`.

## 2. `evals/eval_summary.json` — committed trust snapshot (Python writes, dashboard reads)

Small, committed, regenerated only by the eval (NOT daily). Written by the eval-summary
writer in `evals/report.py`. Shape:
```json
{
  "generated_at": "2026-08-04T18:00:00Z",
  "eval_config_fingerprint": "a1b2c3d4e5f60718",
  "n_items": 220,
  "runs": 3,
  "scorecard": {
    "v3": {"recall_material": 0.939, "precision_material": 0.408, "grounded_pct": 0.374,
           "confidently_wrong": 0.218, "abstention_ambiguous": 0.30, "cost_per_item_nzd": 0.0186},
    "v2": { "...": 0 }, "v1": { "...": 0 },
    "baseline: rules": { "...": 0 }, "baseline: flag_all": { "...": 0 }
  },
  "ranking": {"precision_at_5": 0.80, "precision_at_10": 0.80},
  "providers": [
    {"model": "claude-haiku-4.5", "recall": 0.939, "precision": 0.408, "grounded": 0.374,
     "confidently_wrong": 0.218, "abstention": 0.30, "cost_per_item_nzd": 0.0186}
  ],
  "caveats": ["Grounding ~37% on Haiku is a MODEL limit, not a prompt limit (GPT 0.94 / GLM 0.83 on the identical v3 prompt)."]
}
```
Metric keys reuse `report.py:SCORECARD_COLUMNS`. The dashboard compares
`eval_config_fingerprint` to the live `runtime_config` fingerprint → shows a **stale banner**
when they differ.

## 3. `out/run_log.jsonl` — committed run history (one JSON object per line, appended per run)

```json
{"date":"2026-08-04","ts":"2026-08-04T18:02:11Z","kind":"digest","processed":37,"new":12,
 "deduped":25,"material":3,"needs_look":2,"escalations":0,
 "guardrail_flag_counts":{"G2_ungrounded_quote":1},"total_cost_nzd":0.42,"runtime_seconds":54.3,
 "prompt_version":"v3","model_primary":"claude-haiku-4-5-20251001","dashboard_url":null}
```
`kind` ∈ {`digest`,`intraday`}. Keys align with `src/brief.py` `stats`. Append-only.

## 4. Brief email HTML — archived rendered versions (drafts history)

- `src/render_email.py` writes `out/briefs/<DATE>.email.html` for the morning digest and
  `out/briefs/<DATE>T<HH-MM>.email.html` for an intraday alert. Self-contained (inline CSS),
  Milford-themed. Committed. The dashboard's "draft versions" list is these files, newest first.
- The existing markdown brief (`src/brief.py` → `out/briefs/<DATE>.md`) is unchanged and stays
  the plain record.

## 5. Milford theme tokens — `assets/theme/theme.css` + `src/theme.py`

Derived from `milford-core-portal-design/` (authoritative; do not invent values). CSS custom
properties, exact hexes from `references/brand-language.md`:

| Variable | Value | Role |
|---|---|---|
| `--brand-slate` | `#303c42` | nav, headings, primary text |
| `--brand-slate-2` | `#46545b` | hover / secondary dark |
| `--brand-muted` | `#77858d` | metadata, labels |
| `--brand-cloud` | `#eef1f2` | section / control background |
| `--brand-paper` | `#ffffff` | cards, tables |
| `--brand-orange` | `#e1690e` | primary action, focus, master-brand emphasis |
| `--brand-blue` | `#1c99d6` | data cue (KiwiSaver accent) |
| `--brand-green` | `#4bc864` | data cue (Funds accent) |
| `--brand-purple` | `#915fb4` | data cue (Wealth accent) |
| `--brand-success` | `#198754` | success |
| `--brand-warning` | `#f3a83b` | warning (use for the eval-stale banner) |
| `--brand-danger` | `#c94b42` | danger / guardrail flags |
| `--radius-control` | `4px` | inputs, buttons |
| `--radius-card` | `8px` | cards |
| `--radius-surface` | `14px` | large contained surfaces |

Fonts: **Glypha Bold** for display headings, **Montserrat** for body/tables/controls
(files in `milford-core-portal-design/assets/fonts/`). Email must inline colors and use a
web-safe fallback stack (Georgia/serif for display, Arial/Helvetica for body) since email
clients drop @font-face. `src/theme.py` exposes a `THEME` dict of these tokens for the
Python renderers. Logo: `assets/brand/milfordasset.svg`, used unmodified.

## 6. `src.run` CLI contract (config-driven)

```
python -m src.run [--from DATE] [--to DATE] [--dry-run] [--config runtime_config.json] [--intraday]
```
- Loads `config.yaml`, then `apply_overrides(base, load_runtime_config())` — so provider,
  watchlist, thresholds, ranking, prompt version all come from `runtime_config.json`.
- Existing semantics unchanged (idempotency, 2s/8s retry, dead-letter, watermark). After a
  successful run: write the markdown brief (existing), the HTML email brief (§4), append a
  `run_log.jsonl` row (§3).
- `--intraday`: material-only pass; emits an HTML brief + run_log row with `kind:"intraday"`
  only if a NEW material item cleared guardrails; never advances past a normal digest.

## 7. Vercel app API contract (`dashboard/`)

All routes behind the portal password gate (§8). JSON in/out.
- `GET  /api/config` → current `runtime_config.json`.
- `POST /api/config` → validate (mirror §1) → bump `version` → **direct-commit** to `main`
  via GitHub API → return the committed config. Reject with 400 + message on any invalid
  field or any gold-field. Recompute nothing about gold — ever.
- `POST /api/run-now`  → `workflow_dispatch` `daily-brief.yml`.
- `POST /api/run-eval` → `workflow_dispatch` `run-eval.yml`.
- `GET  /api/versions` → list last N `out/briefs/*.email.html` (name, date, url).
- `GET  /api/eval-summary` → serve `evals/eval_summary.json` + computed `stale` boolean.
- `GET  /api/gmail/draft` (+ `/api/oauth/google`) → live Gmail draft read (Phase 2).
- Read views (Today / Run history / Trust / Optimisations / Cadence) render from
  `run_log.jsonl` (§3), `eval_summary.json` (§2), and the latest brief (§4).

## 8. Portal password gate (app-level, configurable, default `milfordsec`)

- First visit requires a password before any route/API. Store a **salted SHA-256 hash**
  (never plaintext) in `dashboard/portal_auth.json`, seeded with the hash of `milfordsec`.
- Successful login sets a signed, httpOnly session cookie; middleware gates every route/API.
- Change-password endpoint `POST /api/portal-password` writes a new salted hash via the same
  GitHub-commit path; takes effect on the next deploy (~1 min). This is a **lightweight gate**,
  not production auth — keep Vercel deployment protection available as the outer layer, and do
  not imply it is regulatory-grade (per the design skill's output contract).
- Build the login screen from `milford-core-portal-design/assets/templates/login.html`.

## 9. Design system — build from `milford-core-portal-design/`

Use `scripts/scaffold.py portal <dest>` / `login <dest>` to copy the self-contained
templates + assets (brand, fonts, styles, vendor). Preserve asset-relative paths. Reuse
`milford-system.css` tokens/components before adding any value. Read `SKILL.md` and
`references/brand-language.md` first; `references/portal-architecture.md` for
navigation/tables/responsive. Never redraw the logo or substitute the fonts/icons.

## 10. Persistence model — what lives where (git)

- **`main`**: all source; `runtime_config.json`; `evals/eval_summary.json` (changes only on
  an eval — low noise); `out/run_log.jsonl` and `out/briefs/*.email.html` (un-ignored in
  `.gitignore`; the workflow appends + commits them with `[skip ci]` so the daily commit
  does not re-trigger the cron). The Vercel app reads all of these from `main` and writes
  config edits back to `main`.
- **`data-state` branch** (workflow-managed): `state.db` + `data/raw/` — bulky/binary, high
  churn, restored at the start of each run and committed back after. The app never reads these.
- **Ignored, local/CI-only**: `out/eval_runs/` (full eval artefacts), `out/dashboard/` (the
  built site deployed to Vercel), `dashboard/node_modules`, `.vercel`.

This keeps `main` clean of bulky state while giving the app everything it needs on one branch.
