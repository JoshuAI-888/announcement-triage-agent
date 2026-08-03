# DEPLOY.md — operations runbook (Stream C: CI/CD)

This is the ops runbook for running the announcement-triage-agent in production:
two GitHub Actions schedulers plus one always-on Vercel app. It does not cover
failure modes/taxonomy or general project docs — those are the owner's
(`README.md`, a failure taxonomy). See `docs/CONTRACTS.md` for the frozen
interfaces this runbook assumes.

## 1. The model: two schedulers + one app

```
 ┌────────────────────┐        ┌──────────────────────┐
 │ .github/workflows/ │        │ .github/workflows/    │
 │ daily-brief.yml     │        │ run-eval.yml          │
 │ (cron */15, +manual)│        │ (manual only)         │
 └─────────┬───────────┘        └──────────┬────────────┘
           │ writes                        │ writes
           ▼                                ▼
   out/run_log.jsonl              evals/eval_summary.json
   out/briefs/*.email.html
           │                                │
           └───────────────┬────────────────┘
                            ▼ commit to `main` ([skip ci])
                  ┌───────────────────────┐
                  │  Vercel app (dashboard) │  <- reads main via GitHub API
                  │  connected to this repo │  <- auto-redeploys on new commits
                  │  via Vercel Git integration
                  └───────────────────────┘
```

- **`daily-brief.yml`** ticks every 15 minutes. `scripts/ci_gate.py` (a pure,
  offline decider — see `checks/check_ci_gate.py`) reads `runtime_config.json`'s
  `schedule` block (`poll_time_nzt`, `poll_frequency`, `intraday_alerts`) plus
  `out/run_log.jsonl` and decides **digest** / **intraday** / **skip** for that
  tick. This is why the cron itself is a fixed, frequent `*/15 * * * *` — the
  *actual* cadence the operator sees is entirely config-driven, not baked into
  the cron expression. Changing `poll_time_nzt` or `intraday_alerts` in the
  dashboard takes effect on the next tick, no workflow edit needed.
- **`run-eval.yml`** is manual only (`workflow_dispatch`), the target of the
  dashboard's "Run eval now" button (`POST /api/run-eval`, CONTRACTS §7).
- **No `vercel deploy` step exists in either workflow.** The Vercel project is
  connected to this GitHub repo via Vercel's own Git integration, so every
  commit either workflow makes to `main` triggers Vercel's normal auto-redeploy.
  The dashboard app then reads `runtime_config.json`, `out/run_log.jsonl`,
  `out/briefs/*.email.html`, and `evals/eval_summary.json` live via the GitHub
  API (CONTRACTS §7/§10) — it does not need its own copy of state.db or
  data/raw, so it never needs the `data-state` branch either.

## 2. GitHub secrets to add (repo Settings -> Secrets and variables -> Actions)

| Secret | Used by | Required? |
|---|---|---|
| `ANTHROPIC_API_KEY` | `daily-brief.yml` (`src.run`), `run-eval.yml` (`evals.run_eval`) | **Required** — the Claude provider is the default in `runtime_config.json` |
| `OPENAI_API_KEY` | `run-eval.yml` when `eval.provider = "openai"` | Optional — only if comparing against GPT |
| `GLM_API_KEY` | `run-eval.yml` when `eval.provider = "glm"` | Optional — only if comparing against GLM |
| `VERCEL_TOKEN` + `VERCEL_ORG_ID` + `VERCEL_PROJECT_ID` | not currently used | **Not needed** for the default flow (Vercel's Git integration deploys on its own). Only add these if you later switch to a CLI-driven deploy step (e.g. to deploy a specific commit outside the Git integration, or to a preview environment); none of the workflows in this repo reference them today. |
| a scoped `GITHUB_TOKEN` (fine-grained PAT) | the Vercel app's `POST /api/config` direct-commit-to-`main` function and its `workflow_dispatch` calls for run-now / run-eval (CONTRACTS §7) | **Required by the Vercel app**, not by these workflows — set it as a Vercel *project* env var, not a GitHub secret. Scope: `contents:write` + `actions:write` on this repo only. The workflows themselves push using the default `GITHUB_TOKEN` GitHub injects automatically (already has `contents: write` per the `permissions:` block in each workflow file) — no PAT needed there. |

Nothing here is optional for the daily brief to run at all: without
`ANTHROPIC_API_KEY`, `daily-brief.yml` will fetch/gate correctly but
`python -m src.run` will fail at the classify step every time a digest or
intraday pass is due.

## 3. Connecting Vercel + turning on deployment protection

1. In Vercel, **Add New Project** -> import this GitHub repo. This is what
   creates the Git integration — every push to `main` (including the
   workflows' own `[skip ci]` commits) triggers a production redeploy
   automatically; no action is needed in this repo for that to happen.
2. Set the Vercel project's **Production Branch** to `main` (default).
3. Under **Project Settings -> Git**, confirm the `data-state` branch is
   **not** set as a deploy branch (it never should be — it holds bulky
   binary/state, not the app; the app never reads it, per CONTRACTS §10).
4. Under **Project Settings -> Deployment Protection**, turn ON
   **Vercel Authentication** (or a password-protect option, depending on plan)
   for the production deployment. The in-app portal password gate
   (CONTRACTS §8, default `milfordsec`) is explicitly a **lightweight** gate —
   it protects the *routes*, not the *deployment infrastructure* — so Vercel's
   own deployment protection is the outer, harder layer. Do not treat either
   gate alone as sufficient; keep both on.
5. Add the Vercel project env vars the app itself needs (its `GITHUB_TOKEN`
   PAT from §2, and any OAuth client id/secret for the Phase-2 Gmail draft
   read, CONTRACTS §7) under **Project Settings -> Environment Variables**,
   scoped to Production.

## 4. The `data-state` branch: how it works, and how to bootstrap it

`state.db` (the sqlite audit/watermark store) and `data/raw/` (the fetched raw
corpus) are bulky, high-churn, and binary/near-binary — CONTRACTS §10 keeps
them off `main` entirely, on their own branch, so `main`'s history stays small
and diff-able.

**Lifecycle per run (`daily-brief.yml` and `run-eval.yml` both do the restore
half; only `daily-brief.yml` writes back):**
1. *Restore*: `git checkout origin/data-state -- state.db data/raw` onto the
   fresh `main` checkout (then `git reset` to unstage — these paths stay
   gitignored on `main`), so the run has the prior watermark + raw corpus.
2. *Run*: `python -m src.run` (or `--intraday`) updates `state.db` and may add
   files under `data/raw/` in the working tree.
3. *Write back*: a disposable `git worktree` is pointed at `origin/data-state`
   (or an orphan branch, on the very first run), the freshly updated
   `state.db` + `data/raw/` are copied in, committed, and pushed to
   `data-state` — all in a scratch worktree so the `main` checkout (and its
   pending brief/run_log commit) is never disturbed.

**Bootstrapping `data-state` for the first time:** you don't need to do
anything by hand — if `origin/data-state` doesn't exist yet, both workflows
detect that (`git show-ref --verify --quiet refs/remotes/origin/data-state`
fails), skip the restore step, and `daily-brief.yml`'s write-back step creates
`data-state` as a fresh orphan branch on its first successful digest/intraday
run. If you want to seed it manually instead (e.g. to preload a large raw
corpus you already have locally, ahead of the first scheduled run):

```
git checkout --orphan data-state
git rm -rf . 2>/dev/null || true
cp -r /path/to/local/state.db .
cp -r /path/to/local/data/raw ./data/raw
git add -A
git commit -m "chore: bootstrap data-state branch"
git push origin data-state
git checkout main   # or your prior branch
```

## 5. Triggering a manual run / a manual eval

- **Manual brief/intraday run**: repo -> **Actions** -> `daily-brief` ->
  **Run workflow** (the `workflow_dispatch` trigger). This still goes through
  `scripts/ci_gate.py`, so it will actually run a digest/intraday/skip
  decision based on the *current* time and `runtime_config.json` — it is not
  a forced digest. To force a digest on demand regardless of the schedule,
  either temporarily set `poll_time_nzt` a few minutes in the past in the
  dashboard, or dispatch the workflow and accept whatever the gate decides.
- **From the dashboard**: `POST /api/run-now` dispatches the same
  `daily-brief.yml` workflow (CONTRACTS §7) via the GitHub API, using the
  scoped `GITHUB_TOKEN` PAT from §2/§3.
- **Manual eval**: repo -> **Actions** -> `run-eval` -> **Run workflow**, with
  optional `prompt_version` / `provider` / `runs` / `limit` / `no_baselines`
  inputs (blank prompt_version/provider fall back to
  `runtime_config.json`'s `run.prompt_version` / `eval.provider`). From the
  dashboard: `POST /api/run-eval` dispatches this the same way.

## 6. Eval cadence — NOT daily

Running the full gold-set eval on every commit or every day would be both
wasteful (NZ$10-15+ per full 220-item x 3-run pass, per `PROGRESS.md`) and
noisy (`evals/eval_summary.json` is meant to be a stable, occasionally-updated
trust snapshot, CONTRACTS §2 — "changes only on an eval, low noise"). Run it:

- **On change** — any time `runtime_config.json`'s eval-affecting fields move
  (prompt version, prompt override, provider, model id, pricing — exactly the
  fields folded into `eval_fingerprint()`, CONTRACTS §1). The dashboard's
  stale banner (`GET /api/eval-summary`'s `stale` boolean) is the signal that
  this is due.
- **Monthly** — as a baseline cadence even with no config change, to catch
  silent drift (provider model updates, gold-set corrections landing on
  `main` via a separate process). A scheduled monthly trigger can be added to
  `run-eval.yml`'s `on:` block later (`schedule: - cron: "0 18 1 * *"`) if the
  owner wants it automatic instead of manual; it is manual-only today by
  design (no accidental spend from a stray cron typo).
- **Optional canary** — a small `--limit N` run (e.g. 20-30 items) after a
  prompt/provider tweak, before committing to a full 220-item x 3-run pass, to
  catch a broken prompt/parsing regression cheaply. Use the `limit` input on
  the manual `run-eval` dispatch.

## 7. Known CONTRACTS ambiguities this build resolved with a documented choice

- **`out/run_log.jsonl`'s `date` field has no pinned timezone** (CONTRACTS §3
  shows one example row where `date` and `ts`'s UTC calendar day happen to
  match). Since the whole schedule is defined in NZT (`poll_time_nzt`), and
  "has a digest already run today" is inherently an NZT-calendar-day question,
  `scripts/ci_gate.py:last_digest_date_nzt()` converts each row's `ts` (which
  *is* pinned — ISO-8601 UTC) to Pacific/Auckland itself rather than trusting
  `date`'s timezone. If a future writer of `run_log.jsonl` intends `date` to
  already be an NZT calendar date, this is harmless (they'd agree on all but
  a rare few-hour DST/midnight edge); if `date` is meant as UTC, trusting it
  directly would misfire the gate near local midnight in NZ.
