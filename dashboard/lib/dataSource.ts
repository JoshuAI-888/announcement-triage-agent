// dataSource.ts — the single data-access surface every page and API route
// uses. Branches on LOCAL_DEV_MODE (lib/env.ts) so the rest of the app never
// has to know whether it's talking to the local filesystem or the GitHub API.
//
// Reads (CONTRACTS.md §10): runtime_config.json, evals/eval_summary.json,
// out/run_log.jsonl, out/briefs/*.email.html, config.yaml (for the eval
// fingerprint's providers block) — all live off `main`.
//
// Writes (§7): runtime_config.json (config save/revert) and
// dashboard/portal_auth.json (password change) direct-commit to `main`;
// run-now/run-eval trigger workflow_dispatch. All mocked in local dev mode.

import { parse as parseYaml } from "yaml";
import { GITHUB_BRANCH, GITHUB_REPO, LOCAL_DEV_MODE } from "./env";
import { evalFingerprint } from "./fingerprint";
import * as gh from "./github";
import * as local from "./localData";
import { validateRuntimeConfig } from "./schema";
import type {
  BriefVersion,
  EvalSummary,
  FilingsRun,
  PdfLogRow,
  PortalAuth,
  ProvidersBlock,
  RunLogRow,
  RunStatusResult,
  RuntimeConfig,
  SystemPromptResult,
  WorkflowRunView,
} from "./types";
import { defaultPortalAuth } from "./portalAuth";

export const mode: "local-dev" | "github" = LOCAL_DEV_MODE ? "local-dev" : "github";

const RUNTIME_CONFIG_PATH = "runtime_config.json";
const EVAL_SUMMARY_PATH = "evals/eval_summary.json";
const RUN_LOG_PATH = "out/run_log.jsonl";
const PDF_LOG_PATH = "out/pdf_log.jsonl";
const BRIEFS_DIR = "out/briefs";
const FILINGS_DIR = "out/filings";
const CONFIG_YAML_PATH = "config.yaml";
const PORTAL_AUTH_PATH = "dashboard/portal_auth.json";
const PROMPTS_DIR = "prompts";

const BRIEF_NAME_RE = /^\d{4}-\d{2}-\d{2}(T\d{2}-\d{2}(-\d{2})?)?\.email\.html$/;

export interface ConfigResult {
  config: RuntimeConfig;
  editable: boolean; // false only if we truly have nothing to show
}

// --- runtime_config.json ---

export async function getRuntimeConfig(): Promise<ConfigResult> {
  if (LOCAL_DEV_MODE) {
    const override = await local.readOverride("runtime_config.override.json");
    const raw = override ?? (await local.readRepoFile(RUNTIME_CONFIG_PATH));
    if (!raw) throw new Error("runtime_config.json not found in the local repo checkout");
    const parsed = JSON.parse(raw);
    const result = validateRuntimeConfig(parsed);
    if (!result.ok || !result.value) {
      throw new Error(`Local runtime_config.json failed validation: ${result.errors.join("; ")}`);
    }
    return { config: result.value, editable: true };
  }
  const file = await gh.getFile(RUNTIME_CONFIG_PATH);
  if (!file) throw new Error(`runtime_config.json not found on ${GITHUB_BRANCH} of ${GITHUB_REPO}`);
  const parsed = JSON.parse(file.content);
  const result = validateRuntimeConfig(parsed);
  if (!result.ok || !result.value) {
    throw new Error(`runtime_config.json on main failed validation: ${result.errors.join("; ")}`);
  }
  return { config: result.value, editable: true };
}

export type SaveResult =
  | { ok: true; config: RuntimeConfig; mocked: boolean }
  | { ok: false; status: number; errors: string[] };

export async function saveRuntimeConfig(rawPayload: unknown, expectedVersion: number): Promise<SaveResult> {
  const validated = validateRuntimeConfig(rawPayload);
  if (!validated.ok || !validated.value) {
    return { ok: false, status: 400, errors: validated.errors };
  }

  if (LOCAL_DEV_MODE) {
    const override = await local.readOverride("runtime_config.override.json");
    const baseline = await local.readRepoFile(RUNTIME_CONFIG_PATH);
    const currentRaw = override ?? baseline;
    if (!currentRaw) return { ok: false, status: 500, errors: ["runtime_config.json not found in the local repo checkout"] };
    const current = JSON.parse(currentRaw) as RuntimeConfig;
    if (current.version !== expectedVersion) {
      return {
        ok: false,
        status: 409,
        errors: [`version conflict: expected to edit version ${expectedVersion}, current is ${current.version}. Refresh and retry.`],
      };
    }
    const finalConfig: RuntimeConfig = { ...validated.value, version: current.version + 1 };
    // Snapshot whatever was current before this edit, so revert has exactly one step to go back to.
    await local.writeOverride("runtime_config.override.prev.json", currentRaw);
    await local.writeOverride("runtime_config.override.json", JSON.stringify(finalConfig, null, 2) + "\n");
    local.mockCommitLog(RUNTIME_CONFIG_PATH, `dashboard: update runtime_config.json to version ${finalConfig.version}`);
    return { ok: true, config: finalConfig, mocked: true };
  }

  const file = await gh.getFile(RUNTIME_CONFIG_PATH);
  if (!file) return { ok: false, status: 500, errors: ["runtime_config.json not found on main"] };
  const current = JSON.parse(file.content) as RuntimeConfig;
  if (current.version !== expectedVersion) {
    return {
      ok: false,
      status: 409,
      errors: [`version conflict: expected to edit version ${expectedVersion}, current is ${current.version}. Refresh and retry.`],
    };
  }
  const finalConfig: RuntimeConfig = { ...validated.value, version: current.version + 1 };
  await gh.commitFile(
    RUNTIME_CONFIG_PATH,
    JSON.stringify(finalConfig, null, 2) + "\n",
    `dashboard: update runtime_config.json to version ${finalConfig.version}`,
    file.sha
  );
  return { ok: true, config: finalConfig, mocked: false };
}

export type RevertResult =
  | { ok: true; config: RuntimeConfig; mocked: boolean }
  | { ok: false; status: number; error: string };

export async function revertRuntimeConfig(): Promise<RevertResult> {
  if (LOCAL_DEV_MODE) {
    const override = await local.readOverride("runtime_config.override.json");
    if (!override) {
      return { ok: false, status: 409, error: "No local edits to revert — the dashboard is already showing the repo baseline." };
    }
    const prev = await local.readOverride("runtime_config.override.prev.json");
    const restoredRaw = prev ?? (await local.readRepoFile(RUNTIME_CONFIG_PATH));
    if (!restoredRaw) return { ok: false, status: 500, error: "no previous version available to revert to" };
    const restored = JSON.parse(restoredRaw) as RuntimeConfig;
    const current = JSON.parse(override) as RuntimeConfig;
    const validated = validateRuntimeConfig(restored);
    if (!validated.ok || !validated.value) {
      return { ok: false, status: 500, error: `previous version no longer validates: ${validated.errors.join("; ")}` };
    }
    const finalConfig: RuntimeConfig = { ...validated.value, version: current.version + 1 };
    await local.writeOverride("runtime_config.override.json", JSON.stringify(finalConfig, null, 2) + "\n");
    await local.deleteOverride("runtime_config.override.prev.json");
    local.mockCommitLog(RUNTIME_CONFIG_PATH, `dashboard: revert runtime_config.json to version ${finalConfig.version}`);
    return { ok: true, config: finalConfig, mocked: true };
  }

  const shas = await gh.listCommitsForPath(RUNTIME_CONFIG_PATH, 2);
  if (shas.length < 2) {
    return { ok: false, status: 409, error: "No previous commit of runtime_config.json exists to revert to." };
  }
  const [latestSha, prevSha] = shas;
  const [prevFile, currentFile] = await Promise.all([
    gh.getFile(RUNTIME_CONFIG_PATH, prevSha),
    gh.getFile(RUNTIME_CONFIG_PATH),
  ]);
  if (!prevFile || !currentFile) return { ok: false, status: 500, error: "could not read previous or current version" };
  const restored = JSON.parse(prevFile.content);
  const current = JSON.parse(currentFile.content) as RuntimeConfig;
  const validated = validateRuntimeConfig(restored);
  if (!validated.ok || !validated.value) {
    return { ok: false, status: 500, error: `previous version no longer validates: ${validated.errors.join("; ")}` };
  }
  const finalConfig: RuntimeConfig = { ...validated.value, version: current.version + 1 };
  await gh.commitFile(
    RUNTIME_CONFIG_PATH,
    JSON.stringify(finalConfig, null, 2) + "\n",
    `dashboard: revert runtime_config.json to version ${finalConfig.version} (restoring commit ${latestSha !== prevSha ? prevSha.slice(0, 7) : ""})`,
    currentFile.sha
  );
  return { ok: true, config: finalConfig, mocked: false };
}

// --- config.yaml providers block (for the eval fingerprint) ---

export async function getConfigYamlProviders(): Promise<ProvidersBlock> {
  const raw = LOCAL_DEV_MODE ? await local.readRepoFile(CONFIG_YAML_PATH) : (await gh.getFile(CONFIG_YAML_PATH))?.content ?? null;
  if (!raw) return {};
  const parsed = parseYaml(raw) as { providers?: ProvidersBlock };
  return parsed.providers ?? {};
}

// --- prompts/classify_<version>.md (active classification system prompt) ---

/**
 * Resolve the classification system prompt that is ACTUALLY active for the
 * live runtime_config: if run.prompt_version is "custom", that's
 * run.classification_prompt_override verbatim; otherwise it's the committed
 * file prompts/classify_<version>.md, read the same way as every other
 * committed artifact. Read-only — there is no write path here, editing a
 * built-in prompt file is out of scope for the dashboard.
 */
export async function getActiveSystemPrompt(): Promise<SystemPromptResult> {
  const { config } = await getRuntimeConfig();
  const version = config.run.prompt_version;
  if (version === "custom") {
    return {
      version,
      source: "custom",
      text: config.run.classification_prompt_override ?? "",
    };
  }
  const filePath = `${PROMPTS_DIR}/classify_${version}.md`;
  const raw = LOCAL_DEV_MODE ? await local.readRepoFile(filePath) : (await gh.getFile(filePath))?.content ?? null;
  return {
    version,
    source: "file",
    text: raw ?? `(${filePath} not found in this checkout)`,
  };
}

// --- evals/eval_summary.json ---

export async function getEvalSummary(): Promise<EvalSummary | null> {
  const raw = LOCAL_DEV_MODE ? await local.readRepoFile(EVAL_SUMMARY_PATH) : (await gh.getFile(EVAL_SUMMARY_PATH))?.content ?? null;
  if (!raw) return null;
  return JSON.parse(raw) as EvalSummary;
}

// --- out/run_log.jsonl ---

export async function getRunLog(): Promise<RunLogRow[]> {
  const raw = LOCAL_DEV_MODE ? await local.readRepoFile(RUN_LOG_PATH) : (await gh.getFile(RUN_LOG_PATH))?.content ?? null;
  if (!raw) return [];
  const rows: RunLogRow[] = [];
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      rows.push(JSON.parse(trimmed) as RunLogRow);
    } catch {
      // Skip a malformed line rather than fail the whole view.
      continue;
    }
  }
  rows.sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0)); // newest first
  return rows;
}

// --- out/pdf_log.jsonl ---

export async function getPdfLog(limit = 200): Promise<PdfLogRow[]> {
  const raw = LOCAL_DEV_MODE ? await local.readRepoFile(PDF_LOG_PATH) : (await gh.getFile(PDF_LOG_PATH))?.content ?? null;
  if (!raw) return [];
  const rows: PdfLogRow[] = [];
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed && typeof parsed === "object") rows.push(parsed as PdfLogRow);
    } catch {
      // Skip a malformed line rather than fail the whole view.
      continue;
    }
  }
  rows.sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0)); // newest first
  return rows.slice(0, limit);
}

// --- out/filings/<date>.json / <date>T<HH-MM>.json ---

const FILINGS_NAME_RE = /^\d{4}-\d{2}-\d{2}(T\d{2}-\d{2}(-\d{2})?)?\.json$/;

/** Latest classification run (digest or intraday), picked by filename. null if none exist yet. */
export async function getLatestFilings(): Promise<FilingsRun | null> {
  let names: string[];
  if (LOCAL_DEV_MODE) {
    names = (await local.listRepoDir(FILINGS_DIR)).filter((n) => FILINGS_NAME_RE.test(n));
  } else {
    names = (await gh.listDir(FILINGS_DIR)).filter((e) => e.type === "file" && FILINGS_NAME_RE.test(e.name)).map((e) => e.name);
  }
  if (names.length === 0) return null;
  names.sort((a, b) => (a < b ? 1 : a > b ? -1 : 0)); // newest first (ISO-ish names sort lexicographically)
  const latest = names[0];
  const raw = LOCAL_DEV_MODE ? await local.readRepoFile(`${FILINGS_DIR}/${latest}`) : (await gh.getFile(`${FILINGS_DIR}/${latest}`))?.content ?? null;
  if (!raw) return null;
  try {
    return JSON.parse(raw) as FilingsRun;
  } catch {
    return null;
  }
}

// --- out/briefs/*.email.html ---

/**
 * Resolve a brief filename's date + kind. Prefers a join against run_log.jsonl
 * by run_id (the filename minus ".email.html") — this is the source of truth
 * once Stream A's runs carry an explicit, never-name-inferred `kind`. Falls
 * back to the old "does the name contain T?" heuristic when no run_log row
 * matches (older archived briefs from before this migration, or a run_log
 * row missing `run_id`) — that fallback cannot represent "backfill" via
 * filename alone, which is fine: backfill only exists in new-format data.
 */
function briefMeta(name: string, kindByRunId: Map<string, RunLogRow["kind"]>): { date: string; kind: "digest" | "intraday" | "backfill" } {
  const runId = name.replace(/\.email\.html$/, "");
  const date = runId.split("T")[0];
  const joined = kindByRunId.get(runId);
  if (joined) return { date, kind: joined };
  const isIntraday = name.includes("T");
  return { date, kind: isIntraday ? "intraday" : "digest" };
}

export async function listBriefVersions(limit = 20): Promise<BriefVersion[]> {
  let names: string[];
  if (LOCAL_DEV_MODE) {
    names = (await local.listRepoDir(BRIEFS_DIR)).filter((n) => BRIEF_NAME_RE.test(n));
  } else {
    names = (await gh.listDir(BRIEFS_DIR)).filter((e) => e.type === "file" && BRIEF_NAME_RE.test(e.name)).map((e) => e.name);
  }
  names.sort((a, b) => (a < b ? 1 : a > b ? -1 : 0)); // newest first (ISO-ish names sort lexicographically)
  const runLog = await getRunLog();
  const kindByRunId = new Map<string, RunLogRow["kind"]>(
    runLog.filter((r): r is RunLogRow & { run_id: string } => Boolean(r.run_id)).map((r) => [r.run_id, r.kind])
  );
  return names
    .slice(0, limit)
    .map((name) => ({ name, url: `/api/versions/${encodeURIComponent(name)}`, ...briefMeta(name, kindByRunId) }));
}

export async function getBriefHtml(name: string): Promise<string | null> {
  if (!BRIEF_NAME_RE.test(name)) return null; // reject path traversal / bogus names
  if (LOCAL_DEV_MODE) return local.readRepoFile(`${BRIEFS_DIR}/${name}`);
  return (await gh.getFile(`${BRIEFS_DIR}/${name}`))?.content ?? null;
}

// --- dashboard/portal_auth.json ---

export async function getPortalAuth(): Promise<PortalAuth> {
  const raw = LOCAL_DEV_MODE ? await local.readPortalAuthLocal() : (await gh.getFile(PORTAL_AUTH_PATH))?.content ?? null;
  if (!raw) return defaultPortalAuth();
  return JSON.parse(raw) as PortalAuth;
}

export async function savePortalAuth(auth: PortalAuth): Promise<{ mocked: boolean }> {
  const content = JSON.stringify(auth, null, 2) + "\n";
  if (LOCAL_DEV_MODE) {
    // portal_auth.json lives inside dashboard/, so local dev writes it for real
    // (this is not "outside dashboard/", and there is nothing to mock here —
    // the mock only applies to the GitHub-commit path production uses).
    await local.writePortalAuthLocal(content);
    // eslint-disable-next-line no-console
    console.log("[LOCAL DEV MODE] Wrote dashboard/portal_auth.json locally. In production this is a GitHub commit instead.");
    return { mocked: true };
  }
  const file = await gh.getFile(PORTAL_AUTH_PATH);
  await gh.commitFile(PORTAL_AUTH_PATH, content, "dashboard: rotate portal password hash", file?.sha);
  return { mocked: false };
}

// --- workflow_dispatch (run-now / run-eval) ---

export interface RunNowInputs {
  as_of?: string;
  lookback_days?: string;
}

/**
 * Trigger daily-brief.yml. Plain "Run now" (no args) stays a no-arg Daily
 * digest dispatch. A backfill passes `as_of`/`lookback_days`, which map to
 * the workflow_dispatch inputs `as_of_date` + `lookback_days` (the CLI/CI
 * side names the date input `as_of_date`, not `as_of`).
 */
export async function dispatchRunNow(inputs: RunNowInputs = {}): Promise<{ mocked: boolean }> {
  const payload: Record<string, string> = {
    as_of_date: inputs.as_of ?? "",
    lookback_days: inputs.lookback_days ?? "",
  };
  if (LOCAL_DEV_MODE) {
    local.mockDispatchLog("daily-brief.yml", payload);
    return { mocked: true };
  }
  await gh.dispatchWorkflow("daily-brief.yml", payload);
  return { mocked: false };
}

// --- live workflow run status (Run-now progress + ongoing/finished history) ---

const DAILY_BRIEF_WORKFLOW = "daily-brief.yml";

/**
 * Recent daily-brief workflow runs (newest first) with live status. For the one
 * run that is still going (queued/in_progress), we additionally fetch its job
 * steps to name the current activity and compute a step-based progress fraction.
 * We only do that for the single active run to bound API calls. Best-effort:
 * a jobs-fetch failure degrades to no step detail, never throws the whole view.
 */
export async function getRunStatus(limit = 8): Promise<RunStatusResult> {
  if (LOCAL_DEV_MODE) {
    return { mode: "local-dev", runs: [], active: null };
  }
  const raw = await gh.listWorkflowRuns(DAILY_BRIEF_WORKFLOW, limit);
  const activeRaw = raw.find((r) => r.status !== "completed");

  let currentStep: string | null = null;
  let stepsCompleted = 0;
  let stepsTotal = 0;
  if (activeRaw) {
    try {
      const jobs = await gh.listRunJobs(activeRaw.id);
      const job = jobs[0];
      const steps = job?.steps ?? [];
      stepsTotal = steps.length;
      stepsCompleted = steps.filter((s) => s.status === "completed").length;
      const inProgress = steps.find((s) => s.status === "in_progress");
      currentStep = inProgress ? inProgress.name : activeRaw.status === "queued" ? "Queued — waiting for a runner" : null;
    } catch {
      // best-effort: no step breakdown, still report the run as active
    }
  }

  // Resolve each completed+successful run's brief link server-side by joining
  // to run_log.jsonl (closest ts to the GH run's startedAt/createdAt, same
  // UTC day) instead of guessing a filename from the run's date — the
  // guess broke once digest briefs are named by full run_id (with seconds).
  // Never falls back to a guessed name: unresolved → null, link omitted.
  let runLog: RunLogRow[] = [];
  let briefNames: Set<string> = new Set();
  try {
    [runLog] = await Promise.all([getRunLog()]);
    briefNames = new Set((await listBriefVersions(200)).map((v) => v.name));
  } catch {
    // best-effort: no brief links, still report run status
  }

  function resolveBriefUrl(r: (typeof raw)[number]): string | null {
    if (r.status !== "completed" || r.conclusion !== "success") return null;
    if (runLog.length === 0) return null;
    const anchor = r.run_started_at ?? r.created_at;
    const anchorMs = Date.parse(anchor);
    if (Number.isNaN(anchorMs)) return null;
    const anchorDay = anchor.slice(0, 10);
    let best: RunLogRow | null = null;
    let bestDelta = Infinity;
    for (const row of runLog) {
      if (!row.run_id) continue;
      if (row.ts.slice(0, 10) !== anchorDay) continue; // same-day tolerance
      const rowMs = Date.parse(row.ts);
      if (Number.isNaN(rowMs)) continue;
      const delta = Math.abs(rowMs - anchorMs);
      if (delta < bestDelta) {
        bestDelta = delta;
        best = row;
      }
    }
    if (!best || !best.run_id) return null;
    const name = `${best.run_id}.email.html`;
    if (!briefNames.has(name)) return null; // never link to a file that isn't actually there
    return `/api/versions/${encodeURIComponent(name)}`;
  }

  const runs: WorkflowRunView[] = raw.map((r) => {
    const isActive = activeRaw !== undefined && r.id === activeRaw.id;
    return {
      id: r.id,
      runNumber: r.run_number,
      status: r.status,
      conclusion: r.conclusion,
      event: r.event,
      title: r.display_title,
      branch: r.head_branch,
      htmlUrl: r.html_url,
      createdAt: r.created_at,
      startedAt: r.run_started_at,
      updatedAt: r.updated_at,
      currentStep: isActive ? currentStep : null,
      stepsCompleted: isActive ? stepsCompleted : 0,
      stepsTotal: isActive ? stepsTotal : 0,
      briefUrl: resolveBriefUrl(r),
    };
  });

  const active = runs.find((r) => r.status !== "completed") ?? null;
  return { mode, runs, active };
}

export interface RunEvalInputs {
  prompt_version?: string;
  provider?: string;
  runs?: string;
  limit?: string;
  no_baselines?: boolean;
}

export async function dispatchRunEval(inputs: RunEvalInputs): Promise<{ mocked: boolean }> {
  const payload: Record<string, string | boolean> = {
    prompt_version: inputs.prompt_version ?? "",
    provider: inputs.provider ?? "",
    runs: inputs.runs ?? "1",
    limit: inputs.limit ?? "",
    no_baselines: inputs.no_baselines ?? false,
  };
  if (LOCAL_DEV_MODE) {
    local.mockDispatchLog("run-eval.yml", payload);
    return { mocked: true };
  }
  await gh.dispatchWorkflow("run-eval.yml", payload);
  return { mocked: false };
}

// --- trust / staleness (CONTRACTS.md §2, §7 GET /api/eval-summary) ---

export interface TrustStatus {
  summary: EvalSummary | null;
  liveFingerprint: string;
  stale: boolean;
}

/** Compare the live runtime_config's eval fingerprint to the committed eval_summary's. */
export async function getTrustStatus(): Promise<TrustStatus> {
  const [{ config }, providers, summary] = await Promise.all([getRuntimeConfig(), getConfigYamlProviders(), getEvalSummary()]);
  const liveFingerprint = evalFingerprint(config, providers);
  const stale = summary ? summary.eval_config_fingerprint !== liveFingerprint : true;
  return { summary, liveFingerprint, stale };
}
