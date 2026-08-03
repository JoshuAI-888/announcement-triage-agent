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

export interface RuntimeConfig {
  version: number;
  run: RunCfg;
  eval: EvalCfg;
  schedule: ScheduleCfg;
  draft: DraftCfg;
  thresholds: ThresholdsCfg;
  ranking: RankingCfg;
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
