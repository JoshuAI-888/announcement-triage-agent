// POST /api/config/revert — "revert to previous" affordance (CONTRACTS.md §7
// note: "Provide a 'revert to previous' affordance if feasible"). Restores the
// prior committed content of runtime_config.json as a NEW version-bumped
// commit (forward, history-preserving — never a hard reset). In local dev
// mode this restores from dashboard/.local-data/'s one-step snapshot; in
// production it walks GitHub's commit history for the file.

import { NextResponse } from "next/server";
import { mode, revertRuntimeConfig } from "@/lib/dataSource";

export async function POST() {
  const result = await revertRuntimeConfig();
  if (!result.ok) {
    return NextResponse.json({ error: "revert_failed", message: result.error }, { status: result.status });
  }
  return NextResponse.json({ ok: true, config: result.config, mocked: result.mocked, mode });
}
