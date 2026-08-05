// models.ts — plain-language descriptions of the AI models the agent uses, so a
// reader never sees a bare "claude-haiku-4-5" without knowing what it actually
// does. Keyed by family substring; matched case-insensitively against the model
// id recorded in run_log (model_primary) and shown wherever a model is listed.

export interface ModelRole {
  label: string; // short friendly name, e.g. "Claude Haiku"
  role: string; // one-line plain-language description of what it does here
}

const ROLES: { match: string; label: string; role: string }[] = [
  {
    match: "haiku",
    label: "Claude Haiku",
    role: "Fast, low-cost model. Does the first-pass read of every filing — decides material vs immaterial and drafts the reasoning. This is the workhorse for the daily run.",
  },
  {
    match: "sonnet",
    label: "Claude Sonnet",
    role: "Mid-tier model — more capable than Haiku, cheaper than Opus. Used when a balance of quality and cost is wanted.",
  },
  {
    match: "opus",
    label: "Claude Opus",
    role: "Most capable (and most expensive) model. Only used for escalation — a slower, more careful re-read of a filing the first pass was unsure about or that was very long. Escalation is currently OFF for the daily run to control cost.",
  },
  {
    match: "gpt",
    label: "OpenAI GPT",
    role: "OpenAI's model, selectable as an alternative classifier provider.",
  },
  {
    match: "glm",
    label: "GLM",
    role: "Zhipu's GLM model, selectable as an alternative classifier provider.",
  },
];

/** Plain-language role for a model id (e.g. "claude-haiku-4-5"). Falls back to the raw id. */
export function modelRole(modelId: string | null | undefined): ModelRole {
  if (!modelId) return { label: "—", role: "No model recorded for this run." };
  const low = modelId.toLowerCase();
  const hit = ROLES.find((r) => low.includes(r.match));
  if (hit) return { label: hit.label, role: hit.role };
  return { label: modelId, role: "Classifier model used for this run." };
}

/** The two-tier setup, for the FAQ. */
export const MODEL_TIERS = ROLES.filter((r) => ["haiku", "opus"].includes(r.match)).map((r) => ({
  label: r.label,
  role: r.role,
}));
