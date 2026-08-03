// env.ts — environment / mode detection shared across the data layer.
//
// LOCAL DEV MODE (CONTRACTS.md / build brief): when GITHUB_TOKEN is absent (the
// normal case for `npm run dev` / `npm run build` offline), the app:
//   - READS runtime_config.json, evals/eval_summary.json, out/run_log.jsonl,
//     out/briefs/*.email.html and config.yaml straight off the local checkout
//     one directory up from `dashboard/` (this repo), read-only, never mutated;
//   - MOCKS every GitHub write (config commit, portal-password commit,
//     workflow_dispatch): logs what it would have done to the console and
//     records the mock result under dashboard/.local-data/ (gitignored) so the
//     UI can be exercised end-to-end without a token or network access.
//
// In production (GITHUB_TOKEN + GITHUB_REPO set), every read and write goes
// through the GitHub REST API against `main`, per CONTRACTS.md §7/§10 — the
// deployed function's filesystem is not a durable store.
import path from "node:path";

export const GITHUB_TOKEN = process.env.GITHUB_TOKEN || "";
export const GITHUB_REPO = process.env.GITHUB_REPO || ""; // "owner/repo"
export const GITHUB_BRANCH = process.env.GITHUB_BRANCH || "main";

export const LOCAL_DEV_MODE = !GITHUB_TOKEN || !GITHUB_REPO;

// dashboard/ is a child of the repo root in this build; local dev reads climb
// one level. This never runs in prod (LOCAL_DEV_MODE is false there).
export const DASHBOARD_ROOT = process.cwd();
export const REPO_ROOT_LOCAL = path.resolve(DASHBOARD_ROOT, "..");
export const LOCAL_DATA_DIR = path.join(DASHBOARD_ROOT, ".local-data");
