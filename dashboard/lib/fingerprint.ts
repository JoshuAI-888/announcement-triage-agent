// fingerprint.ts — JS replica of src/config_schema.py:eval_fingerprint().
//
// Must produce BYTE-IDENTICAL hashes to the Python implementation for the same
// inputs, because the dashboard compares this against `eval_config_fingerprint`
// committed by the Python eval writer (evals/report.py) in evals/eval_summary.json
// (CONTRACTS.md §1/§2). A drifting implementation would show false-stale (or
// worse, false-fresh) banners.
//
// Python does:
//   material = {"prompt_version":..., "prompt_override_sha":..., "provider":...,
//               "model":..., "pricing":...}
//   blob = json.dumps(material, sort_keys=True, ensure_ascii=False)
//   return sha256(blob.encode()).hexdigest()[:16]
//
// json.dumps with default separators renders `{"a": 1, "b": 2}` (comma-space,
// colon-space) and sorts keys alphabetically at every nesting level. The only
// non-string values in `material` live inside `pricing` (config.yaml always
// writes those as YAML float literals, e.g. `1.00`), so Python's float repr
// (`1.0`, not `1`) has to be replicated explicitly — plain `JSON.stringify`
// would emit `1` and silently break the hash match.

import { createHash } from "crypto";
import type { ProvidersBlock, RuntimeConfig } from "./types";

export function sha256Hex(input: string): string {
  return createHash("sha256").update(input, "utf8").digest("hex");
}

/** Render a number the way Python's json.dumps renders a float: always a decimal point. */
function pyFloatLiteral(n: number): string {
  if (!Number.isFinite(n)) throw new Error(`non-finite pricing value: ${n}`);
  if (Number.isInteger(n)) return `${n}.0`;
  // Simple 2dp pricing values (e.g. 1.4, 0.0186) stringify identically to
  // Python's repr for JS's default Number->String conversion.
  return String(n);
}

function pricingBlob(pricing: { input?: number; output?: number } | null | undefined): string {
  if (!pricing) return "null";
  const keys = Object.keys(pricing).sort(); // sort_keys is recursive in json.dumps
  const parts = keys.map((k) => `${JSON.stringify(k)}: ${pyFloatLiteral((pricing as Record<string, number>)[k])}`);
  return `{${parts.join(", ")}}`;
}

function jsonStrOrNull(v: string | null | undefined): string {
  return v === null || v === undefined ? "null" : JSON.stringify(v);
}

/**
 * Compute the 16-hex-char eval fingerprint for a runtime config against the
 * base config.yaml `providers:` block. `providersBlock` is config.yaml's
 * `providers` mapping (provider -> {model, pricing: {input, output}}), parsed
 * from YAML exactly as Python's `base_config.get("providers", {})`.
 */
export function evalFingerprint(rc: RuntimeConfig, providersBlock: ProvidersBlock): string {
  const provider = rc.eval.provider;
  const pconf = providersBlock?.[provider] ?? {};
  const override = rc.run.classification_prompt_override || "";
  const overrideSha = override ? sha256Hex(override) : "";
  const model = pconf.model ?? null;
  const pricing = pconf.pricing ?? null;

  // Top-level keys of `material`, sorted alphabetically (sort_keys=True):
  // model, pricing, prompt_override_sha, prompt_version, provider
  const entries = [
    `"model": ${jsonStrOrNull(model ?? null)}`,
    `"pricing": ${pricingBlob(pricing)}`,
    `"prompt_override_sha": ${JSON.stringify(overrideSha)}`,
    `"prompt_version": ${JSON.stringify(rc.run.prompt_version)}`,
    `"provider": ${JSON.stringify(provider)}`,
  ];
  const blob = `{${entries.join(", ")}}`;
  return sha256Hex(blob).slice(0, 16);
}
