// test-validation.mjs — a tiny standalone check (no test framework) that
// lib/schema.ts's validateRuntimeConfig() rejects the same categories of bad
// input checks/check_config.py asserts against the Python side: an unknown
// enum value, a malformed email, and every no-gold-field boundary case.
// Run with `npm run test:validation` (node --experimental-strip-types).

import { validateRuntimeConfig } from "../lib/schema.ts";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..", "..");

let failures = 0;
function check(label, pred) {
  if (pred) {
    console.log(`  ok   ${label}`);
  } else {
    console.error(`  FAIL ${label}`);
    failures++;
  }
}

function loadValidBase() {
  const raw = readFileSync(path.join(repoRoot, "runtime_config.json"), "utf-8");
  return JSON.parse(raw);
}

console.log("runtime_config.json contract (dashboard/lib/schema.ts)\n");

const base = loadValidBase();

// --- the committed file validates ---
{
  const result = validateRuntimeConfig(base);
  check("committed runtime_config.json validates", result.ok === true);
}

// --- bad enum ---
{
  const bad = structuredClone(base);
  bad.run.provider = "gemini";
  const result = validateRuntimeConfig(bad);
  check("unknown run.provider enum rejected", result.ok === false);
}

// --- bad email ---
{
  const bad = structuredClone(base);
  bad.draft.email = "not-an-email";
  const result = validateRuntimeConfig(bad);
  check("invalid draft.email rejected", result.ok === false);
}

// --- bad HH:MM ---
{
  const bad = structuredClone(base);
  bad.schedule.poll_time_nzt = "25:00";
  const result = validateRuntimeConfig(bad);
  check("invalid poll_time_nzt rejected", result.ok === false);
}

// --- lowercase ticker ---
{
  const bad = structuredClone(base);
  bad.watchlist = ["aapl"];
  const result = validateRuntimeConfig(bad);
  check("lowercase ticker rejected", result.ok === false);
}

// --- unknown top-level key (extra=forbid) ---
{
  const bad = structuredClone(base);
  bad.unknown_key = 1;
  const result = validateRuntimeConfig(bad);
  check("unknown top-level key rejected (extra=forbid)", result.ok === false);
}

// --- gold-ish fields (Prohibition #1 / S4) ---
{
  const bad = structuredClone(base);
  bad.gold_labels = { x: "material" };
  const result = validateRuntimeConfig(bad);
  check("a gold_labels key is refused", result.ok === false);
}
{
  const bad = structuredClone(base);
  bad.slice_tag = "clear_material";
  const result = validateRuntimeConfig(bad);
  check("a slice_tag key is refused", result.ok === false);
}
{
  const bad = structuredClone(base);
  bad.draft.prompt = "read data/gold/gold.csv";
  const result = validateRuntimeConfig(bad);
  check("a value pointing at data/gold is refused", result.ok === false);
}

console.log("");
if (failures > 0) {
  console.error(`${failures} check(s) failed.`);
  process.exit(1);
} else {
  console.log("all checks passed.");
}
