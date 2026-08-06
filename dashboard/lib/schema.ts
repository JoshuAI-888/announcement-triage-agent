// schema.ts — Node/JS mirror of src/config_schema.py:RuntimeConfig (CONTRACTS.md §1).
//
// This MUST stay in lockstep with `config/runtime_config.schema.json` (generated
// from the pydantic model) and with `src/config_schema.py`'s validators:
//   - same enums, same ranges, same regexes (poll_time_nzt HH:MM, draft.email)
//   - same extra="forbid" behaviour at every nested level
//   - the same no-gold-field boundary (assert_no_gold_fields): any key or string
//     value that reaches into data/gold/ is rejected, full stop (Prohibition #1 / S4).
//
// validateRuntimeConfig() is the single authority POST /api/config calls before
// ever committing anything. It never trusts the client's `version` for anything
// other than optimistic-concurrency comparison (the route recomputes it).

import type {
  DraftCfg,
  EvalCfg,
  NewsMode,
  PdfCfg,
  PollFrequency,
  Provider,
  PromptVersion,
  RankingCfg,
  RunCfg,
  RuntimeConfig,
  ScheduleCfg,
  ThresholdsCfg,
} from "./types";

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

// --- the no-gold-field boundary (prohibition #1 / S4) — mirrors config_schema.py ---
const GOLD_FORBIDDEN_KEY = /(gold|label_|slice_tag|labeller|pass_number|difficulty)/i;
const GOLD_FORBIDDEN_VALUE = /data[\\/]+gold/i;

export class GoldFieldError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "GoldFieldError";
  }
}

export function assertNoGoldFields(raw: unknown, path = "$"): void {
  if (raw === null || raw === undefined) return;
  if (Array.isArray(raw)) {
    raw.forEach((v, i) => assertNoGoldFields(v, `${path}[${i}]`));
    return;
  }
  if (typeof raw === "object") {
    for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
      if (GOLD_FORBIDDEN_KEY.test(k)) {
        throw new GoldFieldError(`forbidden gold-related key at ${path}.${k}`);
      }
      assertNoGoldFields(v, `${path}.${k}`);
    }
    return;
  }
  if (typeof raw === "string") {
    if (GOLD_FORBIDDEN_VALUE.test(raw)) {
      throw new GoldFieldError(`forbidden gold path in value at ${path}: ${JSON.stringify(raw)}`);
    }
  }
}

export interface ValidationResult {
  ok: boolean;
  errors: string[];
  value?: RuntimeConfig;
}

const PROVIDERS: Provider[] = ["claude", "openai", "glm"];
const PROMPT_VERSIONS: PromptVersion[] = ["v1", "v2", "v3", "custom"];
const NEWS_MODES: NewsMode[] = ["search", "resolved", "off"];
const POLL_FREQUENCIES: PollFrequency[] = ["daily", "hourly"];

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function checkExtraKeys(obj: Record<string, unknown>, allowed: string[], path: string, errors: string[]) {
  for (const k of Object.keys(obj)) {
    if (!allowed.includes(k)) {
      errors.push(`${path}: unknown field '${k}' (extra=forbid)`);
    }
  }
}

function num(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/**
 * Validate a raw JSON payload against the RuntimeConfig contract. Mirrors
 * src/config_schema.py:validate() — runs the gold-field scan FIRST (so a
 * malformed-but-gold-carrying payload is rejected for the gold reason, same
 * as the Python side), then the full structural/range/enum validation.
 */
export function validateRuntimeConfig(raw: unknown): ValidationResult {
  const errors: string[] = [];

  try {
    assertNoGoldFields(raw);
  } catch (e) {
    if (e instanceof GoldFieldError) {
      return { ok: false, errors: [e.message] };
    }
    throw e;
  }

  if (!isPlainObject(raw)) {
    return { ok: false, errors: ["payload must be a JSON object"] };
  }

  checkExtraKeys(
    raw,
    ["version", "run", "eval", "schedule", "draft", "thresholds", "ranking", "pdf", "watchlist", "news_mode", "items_shown", "theme"],
    "$",
    errors
  );

  // --- version ---
  const version = raw.version;
  if (!(typeof version === "number" && Number.isInteger(version) && version >= 1)) {
    errors.push("version: must be an integer >= 1");
  }

  // --- run (optional, has defaults) ---
  const runRaw = raw.run ?? {};
  let run: RunCfg = { provider: "claude", prompt_version: "v3", classification_prompt_override: null };
  if (!isPlainObject(runRaw)) {
    errors.push("run: must be an object");
  } else {
    checkExtraKeys(runRaw, ["provider", "prompt_version", "classification_prompt_override"], "run", errors);
    const provider = runRaw.provider ?? "claude";
    if (!PROVIDERS.includes(provider as Provider)) errors.push(`run.provider: must be one of ${PROVIDERS.join(", ")}`);
    const promptVersion = runRaw.prompt_version ?? "v3";
    if (!PROMPT_VERSIONS.includes(promptVersion as PromptVersion))
      errors.push(`run.prompt_version: must be one of ${PROMPT_VERSIONS.join(", ")}`);
    const override = runRaw.classification_prompt_override ?? null;
    if (override !== null) {
      if (typeof override !== "string") errors.push("run.classification_prompt_override: must be a string or null");
      else if (override.length > 20000) errors.push("run.classification_prompt_override: max length is 20000");
    }
    run = {
      provider: provider as Provider,
      prompt_version: promptVersion as PromptVersion,
      classification_prompt_override: (override as string | null) ?? null,
    };
  }

  // --- eval (optional, has defaults) ---
  const evalRaw = raw.eval ?? {};
  let evalCfg: EvalCfg = { provider: "claude", concurrency: 12 };
  if (!isPlainObject(evalRaw)) {
    errors.push("eval: must be an object");
  } else {
    checkExtraKeys(evalRaw, ["provider", "concurrency"], "eval", errors);
    const provider = evalRaw.provider ?? "claude";
    if (!PROVIDERS.includes(provider as Provider)) errors.push(`eval.provider: must be one of ${PROVIDERS.join(", ")}`);
    const concurrency = evalRaw.concurrency ?? 12;
    if (!(num(concurrency) && Number.isInteger(concurrency) && concurrency >= 1 && concurrency <= 32)) {
      errors.push("eval.concurrency: must be an integer between 1 and 32");
    }
    evalCfg = { provider: provider as Provider, concurrency: concurrency as number };
  }

  // --- schedule (required) ---
  const scheduleRaw = raw.schedule;
  let schedule: ScheduleCfg = { poll_time_nzt: "06:00", poll_frequency: "daily", intraday_alerts: false, lookback_days: 1 };
  if (!isPlainObject(scheduleRaw)) {
    errors.push("schedule: required object");
  } else {
    checkExtraKeys(scheduleRaw, ["poll_time_nzt", "poll_frequency", "intraday_alerts", "lookback_days"], "schedule", errors);
    const pollTime = scheduleRaw.poll_time_nzt ?? "06:00";
    if (typeof pollTime !== "string" || !HHMM.test(pollTime)) {
      errors.push("schedule.poll_time_nzt: must be HH:MM (24h)");
    }
    const pollFrequency = scheduleRaw.poll_frequency ?? "daily";
    if (!POLL_FREQUENCIES.includes(pollFrequency as PollFrequency)) {
      errors.push(`schedule.poll_frequency: must be one of ${POLL_FREQUENCIES.join(", ")}`);
    }
    const intradayAlerts = scheduleRaw.intraday_alerts ?? false;
    if (typeof intradayAlerts !== "boolean") errors.push("schedule.intraday_alerts: must be a boolean");
    // Tolerate absence: runtime_config.json on disk may not carry this field
    // until the Python side ships lockback_days, so default to 1 rather than
    // erroring — but still reject a present-but-invalid value.
    const lookbackDays = scheduleRaw.lookback_days ?? 1;
    if (!(num(lookbackDays) && Number.isInteger(lookbackDays) && lookbackDays >= 1)) {
      errors.push("schedule.lookback_days: must be an integer >= 1");
    }
    schedule = {
      poll_time_nzt: pollTime as string,
      poll_frequency: pollFrequency as PollFrequency,
      intraday_alerts: intradayAlerts as boolean,
      lookback_days: lookbackDays as number,
    };
  }

  // --- draft (required) ---
  const draftRaw = raw.draft;
  let draft: DraftCfg = { email: "", prompt: "" };
  if (!isPlainObject(draftRaw)) {
    errors.push("draft: required object");
  } else {
    checkExtraKeys(draftRaw, ["email", "prompt"], "draft", errors);
    const email = draftRaw.email;
    if (typeof email !== "string" || !EMAIL.test(email)) {
      errors.push("draft.email: must be a valid email address");
    }
    const prompt = draftRaw.prompt;
    if (typeof prompt !== "string") errors.push("draft.prompt: required string");
    else if (prompt.length > 8000) errors.push("draft.prompt: max length is 8000");
    draft = { email: (email as string) ?? "", prompt: (prompt as string) ?? "" };
  }

  // --- thresholds (optional, has defaults) ---
  const thresholdsRaw = raw.thresholds ?? {};
  let thresholds: ThresholdsCfg = { confidence_floor: 0.65, escalate_below_confidence: 0.65, escalate_above_chars: 20000 };
  if (!isPlainObject(thresholdsRaw)) {
    errors.push("thresholds: must be an object");
  } else {
    checkExtraKeys(thresholdsRaw, ["confidence_floor", "escalate_below_confidence", "escalate_above_chars"], "thresholds", errors);
    const confidenceFloor = thresholdsRaw.confidence_floor ?? 0.65;
    if (!(num(confidenceFloor) && confidenceFloor >= 0 && confidenceFloor <= 1)) {
      errors.push("thresholds.confidence_floor: must be between 0 and 1");
    }
    const escalateBelow = thresholdsRaw.escalate_below_confidence ?? 0.65;
    if (!(num(escalateBelow) && escalateBelow >= 0 && escalateBelow <= 1)) {
      errors.push("thresholds.escalate_below_confidence: must be between 0 and 1");
    }
    const escalateAboveChars = thresholdsRaw.escalate_above_chars ?? 20000;
    if (!(num(escalateAboveChars) && Number.isInteger(escalateAboveChars) && escalateAboveChars >= 0)) {
      errors.push("thresholds.escalate_above_chars: must be a non-negative integer");
    }
    thresholds = {
      confidence_floor: confidenceFloor as number,
      escalate_below_confidence: escalateBelow as number,
      escalate_above_chars: escalateAboveChars as number,
    };
  }

  // --- ranking (optional, has defaults) ---
  const rankingRaw = raw.ranking ?? {};
  let ranking: RankingCfg = {
    recency_half_life_hours: 12,
    materiality_weight: { material: 1.0, insufficient_info: 0.4, immaterial: 0.0 },
    watchlist_weight_default: 1.0,
  };
  if (!isPlainObject(rankingRaw)) {
    errors.push("ranking: must be an object");
  } else {
    checkExtraKeys(rankingRaw, ["recency_half_life_hours", "materiality_weight", "watchlist_weight_default"], "ranking", errors);
    const recency = rankingRaw.recency_half_life_hours ?? 12;
    if (!(num(recency) && recency > 0)) errors.push("ranking.recency_half_life_hours: must be > 0");
    const materialityWeight = rankingRaw.materiality_weight ?? { material: 1.0, insufficient_info: 0.4, immaterial: 0.0 };
    if (!isPlainObject(materialityWeight)) {
      errors.push("ranking.materiality_weight: must be an object");
    } else {
      for (const [k, v] of Object.entries(materialityWeight)) {
        if (!num(v)) errors.push(`ranking.materiality_weight.${k}: must be a number`);
      }
    }
    const watchlistWeightDefault = rankingRaw.watchlist_weight_default ?? 1.0;
    if (!(num(watchlistWeightDefault) && watchlistWeightDefault >= 0)) {
      errors.push("ranking.watchlist_weight_default: must be >= 0");
    }
    ranking = {
      recency_half_life_hours: recency as number,
      materiality_weight: materialityWeight as Record<string, number>,
      watchlist_weight_default: watchlistWeightDefault as number,
    };
  }

  // --- pdf (optional, has defaults) ---
  const pdfRaw = raw.pdf ?? {};
  let pdf: PdfCfg = { ocr_enabled: true };
  if (!isPlainObject(pdfRaw)) {
    errors.push("pdf: must be an object");
  } else {
    checkExtraKeys(pdfRaw, ["ocr_enabled"], "pdf", errors);
    const ocrEnabled = pdfRaw.ocr_enabled ?? true;
    if (typeof ocrEnabled !== "boolean") errors.push("pdf.ocr_enabled: must be a boolean");
    pdf = { ocr_enabled: ocrEnabled as boolean };
  }

  // --- watchlist (required, min 1, uppercase, unique) ---
  const watchlistRaw = raw.watchlist;
  let watchlist: string[] = [];
  if (!Array.isArray(watchlistRaw) || watchlistRaw.length < 1) {
    errors.push("watchlist: required non-empty array");
  } else if (!watchlistRaw.every((t) => typeof t === "string")) {
    errors.push("watchlist: every entry must be a string");
  } else {
    watchlist = watchlistRaw as string[];
    if (watchlist.some((t) => t !== t.toUpperCase())) {
      errors.push("watchlist: tickers must be uppercase");
    }
    if (new Set(watchlist).size !== watchlist.length) {
      errors.push("watchlist: duplicate tickers are not allowed");
    }
  }

  // --- news_mode ---
  const newsMode = raw.news_mode ?? "search";
  if (!NEWS_MODES.includes(newsMode as NewsMode)) {
    errors.push(`news_mode: must be one of ${NEWS_MODES.join(", ")}`);
  }

  // --- items_shown ---
  const itemsShown = raw.items_shown ?? 20;
  if (!(num(itemsShown) && Number.isInteger(itemsShown) && itemsShown >= 1 && itemsShown <= 100)) {
    errors.push("items_shown: must be an integer between 1 and 100");
  }

  // --- theme ---
  const theme = raw.theme ?? "milford";
  if (typeof theme !== "string") errors.push("theme: must be a string");

  if (errors.length > 0) {
    return { ok: false, errors };
  }

  const value: RuntimeConfig = {
    version: version as number,
    run,
    eval: evalCfg,
    schedule,
    draft,
    thresholds,
    ranking,
    pdf,
    watchlist,
    news_mode: newsMode as NewsMode,
    items_shown: itemsShown as number,
    theme: theme as string,
  };
  return { ok: true, errors: [], value };
}
