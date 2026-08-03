# Announcement Triage Agent — operator dashboard

A Next.js (App Router) app that is the Vercel-deployed piece of the
announcement-triage-agent build: the Milford-themed operator portal that
reads `runtime_config.json`, `evals/eval_summary.json`, `out/run_log.jsonl`
and `out/briefs/*.email.html` off the repo's `main` branch, lets an operator
edit the runtime config, and triggers the two GitHub Actions workflows
(`daily-brief.yml`, `run-eval.yml`). See `../docs/CONTRACTS.md` for the frozen
interfaces this app builds against, and `../DEPLOY.md` for the ops runbook
this app is one piece of.

This app does **not** run the pipeline itself — it is a thin, read-mostly
control surface over a repo whose Python core (`src/`, `evals/`) and CI
(`.github/workflows/`) live one level up.

## What's here

```
dashboard/
  app/
    layout.tsx              root layout — loads the Milford CSS
    page.tsx                "/" -> redirect to /today
    login/page.tsx           portal password gate (built from
                              milford-core-portal-design/assets/templates/login.html)
    (portal)/                everything behind the gate, shared sidebar/topbar shell
      layout.tsx
      today/                 latest run + latest brief's material list
      history/                out/run_log.jsonl table
      trust/                  eval_summary.json scorecard + stale banner
      optimisations/          static reference page
      cadence/                eval cadence explainer + "last verified"
      config/                 the editable runtime_config.json form
      versions/               out/briefs/*.email.html archive (list + viewer)
    api/
      auth/login, auth/logout
      config/                 GET current config, POST validate+commit
      config/revert/          POST revert to the previous committed version
      run-now/                POST -> workflow_dispatch daily-brief.yml
      run-eval/                POST -> workflow_dispatch run-eval.yml
      versions/                GET list, GET [name] raw brief HTML
      eval-summary/            GET eval_summary.json + computed `stale`
      portal-password/         POST change the portal password
      gmail/draft/              STUB — 501, Phase 2
      oauth/google/             STUB — 501, Phase 2
  components/                 Icon, PortalShell (sidebar/topbar), TopbarActions
  lib/
    schema.ts                 JS mirror of src/config_schema.py's RuntimeConfig
                               validator (extra=forbid, enums, ranges, regexes,
                               the no-gold-field scan)
    fingerprint.ts             JS mirror of eval_fingerprint() — byte-identical
                               hash to the Python implementation
    dataSource.ts               the one data-access surface every page/route uses;
                               branches on LOCAL_DEV_MODE (env.ts)
    github.ts                   GitHub Contents/Actions API wrapper (prod)
    localData.ts                 local filesystem reads + mocked "commits" (dev)
    session.ts                   signed session cookie (Web Crypto, Edge-safe)
    portalAuth.ts                salted SHA-256 password hashing
  middleware.ts                 the portal password gate — runs on every route
  public/
    brand/, fonts/, styles/     copied from ../milford-core-portal-design/assets/
                               (milford-system.css, portal.css, unmodified logo/fonts)
    styles/dashboard.css        the small set of additions this app needed on
                               top of the Milford system (warning banner, form
                               layout, brief-preview iframe, mono text)
  portal_auth.json               seeded salted hash of the default password
                               "milfordsec" (CONTRACTS.md §8)
```

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | prod only | Fine-grained PAT, scoped to `contents: write` + `actions: write` on this repo only. Unset -> **LOCAL DEV MODE**. |
| `GITHUB_REPO` | prod only | `"owner/repo"`. Unset -> **LOCAL DEV MODE**. |
| `GITHUB_BRANCH` | no | Defaults to `main`. |
| `PORTAL_SESSION_SECRET` | prod (strongly recommended) | HMAC secret for the signed session cookie. An insecure dev fallback is used (and loudly logged) if unset — never leave it unset in a real deployment. |

Copy `.env.example` to `.env.local` to set these for `next dev`.

## Local dev mode

If `GITHUB_TOKEN`/`GITHUB_REPO` are not set (the default — nothing is
configured in this build environment), the app:

- **reads** `runtime_config.json`, `evals/eval_summary.json`,
  `out/run_log.jsonl`, `out/briefs/*.email.html` and `config.yaml` straight off
  the real repo checkout one directory up from `dashboard/` — read-only, never
  mutated by this app;
- **mocks** every GitHub write. Saving the config, changing the portal
  password (well — password changes write `dashboard/portal_auth.json` for
  real, since that file lives inside `dashboard/` itself and there's nothing
  to mock there), and dispatching `daily-brief.yml` / `run-eval.yml` all log
  what would have happened to the server console instead of calling GitHub.
  Config edits land in `dashboard/.local-data/` (gitignored), layered
  transparently on top of the real `runtime_config.json` so the UI round-trips
  correctly across a `save` -> `revert` cycle without ever touching the repo's
  actual file.

This means `npm run dev` and `npm run build` both work fully offline, with no
token and no network access, while still exercising the real validation and
fingerprint logic against this repo's real committed data.

## Run locally

```bash
cd dashboard
npm install
npm run dev
# -> http://localhost:3000, redirects to /login
# portal password: milfordsec (seeded hash in dashboard/portal_auth.json)
```

`npm run build && npm run start` runs the same thing in production mode.

### Manual validation check

`npm run test:validation` runs `scripts/test-validation.mjs`, a small
standalone script (no test framework) that feeds `lib/schema.ts`'s
`validateRuntimeConfig`:

- a payload with an unknown `run.provider` enum value -> must reject,
- a payload with a malformed `draft.email` -> must reject,
- a payload carrying a `gold_labels` key, a `slice_tag` key, and a value
  pointing at `data/gold/...` -> must all be rejected by the no-gold-field
  scan (Prohibition #1 / S4),
- a valid payload -> must accept.

If you'd rather check by hand: open `/config` in the running app, and in the
browser devtools console run
`fetch('/api/config').then(r=>r.json()).then(({config}) => fetch('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({...config, run: {...config.run, provider: 'gemini'}})}).then(r=>r.json()).then(console.log))`
— expect a 400 with an `errors` array.

## Deploying to Vercel

1. **Add New Project** in Vercel, import this GitHub repo, and set the
   **Root Directory** to `dashboard/` (Vercel auto-detects Next.js once the
   root is set correctly).
2. Set the **Production Branch** to `main`.
3. Add the environment variables above (`GITHUB_TOKEN`, `GITHUB_REPO`,
   `PORTAL_SESSION_SECRET`) under **Project Settings -> Environment
   Variables**, scoped to Production (and Preview if you want previews to
   work against the real repo too).
4. Under **Project Settings -> Deployment Protection**, turn on **Vercel
   Authentication** (or your plan's password-protect option) for the
   production deployment. **The in-app portal password gate is a lightweight
   app-level gate — a single shared password, a signed cookie, no user
   identity or rate limiting beyond what Vercel provides. It protects
   routes, not the deployment infrastructure. Keep Vercel's own Deployment
   Protection on as the outer, harder layer — do not rely on either gate
   alone.** See `../DEPLOY.md` §3 for the full picture (this app is the
   "Vercel app" box in that doc's diagram).
5. No `vercel deploy` step is needed anywhere — once the project is
   connected, every commit to `main` (including this app's own config-save
   commits, and the workflows' `[skip ci]` commits) triggers Vercel's normal
   Git-integration auto-redeploy.

## Design system

Built from `../milford-core-portal-design/` per its `SKILL.md`: the login and
portal shell markup come from `assets/templates/login.html` /
`portal.html`, styling reuses `milford-system.css` + `portal.css` unmodified
(copied into `public/styles/`), and the Milford mark / Glypha / Montserrat /
Font Awesome assets are copied verbatim into `public/brand/` and
`public/fonts/`. `public/styles/dashboard.css` holds only the small set of
additions this app needed (a warning banner using `--brand-warning`, the
config form grid, the brief-preview iframe frame, monospace text for hashes)
— everything else reuses existing tokens and components. Mock/illustrative
data is labelled as such throughout (Optimisations page, empty states).

## Known gaps / Phase 2

- **Gmail draft integration** (`GET /api/gmail/draft`, `GET
  /api/oauth/google`) is explicitly out of scope for this build and returns
  `501 Not Implemented` with a message pointing at CONTRACTS.md §7. Do not
  wire a real Gmail client into these routes without the OAuth flow that's
  meant to arrive with them.
- **"Revert to previous"** only steps back one version: local dev mode keeps
  a single one-step snapshot in `.local-data/`; production walks GitHub's
  commit history for `runtime_config.json` two commits back. There is no
  multi-step undo history in this build.

## CONTRACTS.md ambiguities resolved in this build (documented choices)

- **Where the eval-affecting `providers` block comes from for the JS
  fingerprint.** `eval_fingerprint()` in `src/config_schema.py` reads
  `base_config.get("providers", {})` — i.e. `config.yaml`'s `providers:`
  block, not `runtime_config.json`. `lib/dataSource.ts:getConfigYamlProviders()`
  reads and YAML-parses `config.yaml` (locally, or via the GitHub API) to
  supply exactly that block to `lib/fingerprint.ts`. Getting this source
  wrong would silently break the stale-banner comparison, so it's called out
  here explicitly.
- **Python float vs. JS number in the fingerprint hash.** `config.yaml`'s
  pricing values are YAML float literals (`1.00`, `5.00`, ...), so Python's
  `json.dumps` renders them as `"1.0"`, `"5.0"` — not `"1"`, `"5"`. Plain
  `JSON.stringify` in JS would emit `"1"` and silently produce a different
  hash. `lib/fingerprint.ts` hand-builds the JSON blob for the fixed
  `material` shape (rather than using a generic serializer) specifically to
  replicate this, with a comment explaining why.
- **"Revert to previous" was left unspecified beyond "if feasible."**
  Implemented as: restore the prior committed content, then commit *that* as
  a **new**, version-bumped commit (never a hard reset / force-push) — so
  revert never rewrites history and always keeps `version` monotonically
  increasing for audit purposes (CONTRACTS.md §1: "`version` ... bumped on
  every committed edit — optimistic concurrency + audit").
- **`portal_auth.json`'s read path in production.** CONTRACTS.md §8 says the
  password-change endpoint writes via "the same GitHub-commit path" as config
  edits, but doesn't say whether *reads* should also go through the GitHub
  API vs. the deployed bundle's own filesystem copy. This build reads it the
  same way as every other CONTRACTS §10 file (GitHub API in prod, local file
  in dev) for consistency — a bundled-filesystem read would only reflect a
  password change after the next redeploy finishes, which seemed like a
  worse and more confusing default.
- **Optimistic concurrency on `POST /api/config`.** Not spelled out in
  CONTRACTS.md beyond "`version` ... bumped on every committed edit —
  optimistic concurrency + audit." This build requires the client to submit
  the `version` it loaded; the server 409s with a "config changed since you
  loaded it" message if the committed version has moved on since, rather than
  silently overwriting a concurrent edit.
