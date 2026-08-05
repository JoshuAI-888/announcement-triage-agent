// types.ts — TypeScript mirror of the shapes documented in docs/CONTRACTS.md.
// Keep this in lockstep with config/runtime_config.schema.json (§1) and the
// eval_summary.json / run_log.jsonl shapes (§2/§3). This file has no behaviour;
// see lib/schema.ts for the validator that must mirror src/config_schema.py.

export type Provider = "claude" | "openai" | "glm";
export type PromptVersion = "v1" | "v2" | "v3" | "custom";
export type NewsMode = "search" | "resolved" | "off";
export type PollFrequency = "daily" | "hourly";

export interface RunCfg {
  provider: Provider;
  prompt_version: PromptVersion;
  classification_prompt_override: string | null;
}

export interface EvalCfg {
  provider: Provider;
  concurrency: number;
}

export interface ScheduleCfg {
  poll_time_nzt: string;
  poll_frequency: PollFrequency;
  intraday_alerts: boolean;
}

export interface DraftCfg {
  email: string;
  prompt: string;
}

export interface ThresholdsCfg {
  confidence_floor: number;
  escalate_below_confidence: number;
  escalate_above_chars: number;
}

export interface RankingCfg {
  recency_half_life_hours: number;
  materiality_weight: Record<string, number>;
  watchlist_weight_default: number;
}

export interface PdfCfg {
  ocr_enabled: boolean;
}

export interface RuntimeConfig {
  version: number;
  run: RunCfg;
  eval: EvalCfg;
  schedule: ScheduleCfg;
  draft: DraftCfg;
  thresholds: ThresholdsCfg;
  ranking: RankingCfg;
  pdf: PdfCfg;
  watchlist: string[];
  news_mode: NewsMode;
  items_shown: number;
  theme: string;
}

export interface ScorecardRow {
  recall_material: number;
  precision_material: number;
  grounded_pct: number;
  confidently_wrong: number;
  abstention_ambiguous: number;
  cost_per_item_nzd: number | null;
}

export interface ProviderRow {
  model: string;
  recall: number;
  precision: number;
  grounded: number;
  confidently_wrong: number;
  abstention: number;
  cost_per_item_nzd: number | null;
}

export interface EvalSummary {
  generated_at: string;
  eval_config_fingerprint: string;
  n_items: number;
  runs: number;
  seed_note?: string;
  scorecard: Record<string, ScorecardRow>;
  ranking: { precision_at_5: number; precision_at_10: number };
  providers: ProviderRow[];
  caveats: string[];
}

export interface RunLogRow {
  date: string;
  ts: string;
  kind: "digest" | "intraday";
  processed: number;
  new: number;
  deduped: number;
  material: number;
  needs_look: number;
  escalations: number;
  guardrail_flag_counts: Record<string, number>;
  total_cost_nzd: number;
  runtime_seconds: number;
  prompt_version: string;
  model_primary: string;
  dashboard_url: string | null;
}

export interface BriefVersion {
  name: string;
  date: string;
  kind: "digest" | "intraday";
  url: string;
}

export interface ProvidersBlock {
  [provider: string]: {
    kind?: string;
    model?: string;
    pricing?: { input: number; output: number };
    [key: string]: unknown;
  };
}

export interface PortalAuth {
  salt: string;
  hash: string;
  updated_at: string;
}

// out/pdf_log.jsonl — one line per PDF-handling decision made while fetching
// a filing's primary document (CONTRACTS.md-style append-only log, same
// shape as run_log.jsonl but for the PDF/OCR pipeline).
export type PdfLogDecision =
  | "skipped_form"
  | "pypdf_text"
  | "claude_ocr"
  | "placeholder_too_big"
  | "placeholder_ocr_disabled"
  | "placeholder_no_text"
  | "error";

export interface PdfLogRow {
  ts: string;
  announcement_id: string | null;
  ticker: string;
  form: string;
  primary_document: string;
  bytes: number | null;
  decision: PdfLogDecision;
  chars_out: number;
  model_id: string | null;
  cost_nzd: number | null;
  detail: string;
}

// GET /api/system-prompt response shape.
export interface SystemPromptResult {
  version: string;
  source: "file" | "custom";
  text: string;
}

// out/filings/<date>.json and out/filings/<date>T<HH-MM>.json — the
// per-run classification artifact (CONTRACTS.md). Digest files are named
// <date>.json; intraday files are named <date>T<HH-MM>.json. Read the
// latest by filename via lib/dataSource.ts's getLatestFilings().

export interface FilingFlag {
  code: string;
  label: string;
  why: string;
}

export interface FilingRow {
  announcement_id: string;
  ticker: string;
  company_name: string;
  industry: string | null;
  native_form: string;
  doc_type: string;
  doc_type_label: string;
  materiality: string;
  materiality_label: string;
  confidence: number;
  rationale: string;
  flags: FilingFlag[];
  source_url: string;
  published_at: string;
  score: number | null;
}

export interface FilingsCounts {
  total_received: number;
  material: number;
  immaterial: number;
  needs_more_info: number;
  dropped_offwatchlist: number;
  dead_lettered: number;
}

export interface FilingsRun {
  date: string;
  generated_at: string;
  kind: "digest" | "intraday";
  counts: FilingsCounts;
  filings: FilingRow[];
}

// --- Live workflow runs (the "Run now" progress + ongoing/finished history) ---

export interface WorkflowRunView {
  id: number;
  runNumber: number;
  status: string; // queued | in_progress | completed | waiting | pending | requested
  conclusion: string | null; // success | failure | cancelled | skipped | null (while running)
  event: string; // schedule | workflow_dispatch
  title: string;
  branch: string;
  htmlUrl: string;
  createdAt: string;
  startedAt: string | null;
  updatedAt: string;
  // Progress, populated only for the active (non-completed) run to bound API calls:
  currentStep: string | null; // name of the in-progress step ("current activity")
  stepsCompleted: number;
  stepsTotal: number;
}

export interface RunStatusResult {
  mode: "local-dev" | "github";
  runs: WorkflowRunView[];
  active: WorkflowRunView | null; // newest run that is not yet completed, if any
}
