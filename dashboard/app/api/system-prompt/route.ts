// GET /api/system-prompt — the ACTIVE classification system prompt, resolved
// from the live runtime_config.json's run.prompt_version (CONTRACTS.md-style
// read, same data-source path as everything else): "custom" reads
// run.classification_prompt_override; any other version reads the committed
// prompts/classify_<version>.md. Read-only — there is no POST here. Editing
// the built-in prompt files is out of scope for the dashboard; the only
// prompt lever exposed to operators is the override field in the Config UI,
// which is gated behind re-running the eval before it can be trusted.
import { NextResponse } from "next/server";
import { getActiveSystemPrompt } from "@/lib/dataSource";

export async function GET() {
  try {
    const result = await getActiveSystemPrompt();
    return NextResponse.json(result);
  } catch (err) {
    return NextResponse.json({ error: "read_failed", message: (err as Error).message }, { status: 500 });
  }
}
