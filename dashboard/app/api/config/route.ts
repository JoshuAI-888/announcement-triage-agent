// GET/POST /api/config — CONTRACTS.md §7.
//   GET  -> the current runtime_config.json.
//   POST -> validate (schema + email/HH:MM regexes + no-gold-field scan, all in
//           lib/schema.ts mirroring src/config_schema.py) -> bump version ->
//           direct-commit to main via the GitHub API (mocked in local dev) ->
//           return the committed config. 400 on any invalid field or gold-field
//           hit; recomputes nothing about gold, ever.

import { NextResponse } from "next/server";
import { getRuntimeConfig, saveRuntimeConfig, mode } from "@/lib/dataSource";

export async function GET() {
  try {
    const { config } = await getRuntimeConfig();
    return NextResponse.json({ config, mode });
  } catch (err) {
    return NextResponse.json({ error: "read_failed", message: (err as Error).message }, { status: 500 });
  }
}

export async function POST(req: Request) {
  let payload: unknown;
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ error: "bad_request", message: "expected a JSON body" }, { status: 400 });
  }
  if (typeof payload !== "object" || payload === null || !("version" in (payload as Record<string, unknown>))) {
    return NextResponse.json({ error: "bad_request", message: "body must include the version you are editing" }, { status: 400 });
  }
  const expectedVersion = (payload as { version: unknown }).version;
  if (typeof expectedVersion !== "number") {
    return NextResponse.json({ error: "bad_request", message: "version must be a number" }, { status: 400 });
  }

  const result = await saveRuntimeConfig(payload, expectedVersion);
  if (!result.ok) {
    return NextResponse.json({ error: "invalid_config", errors: result.errors }, { status: result.status });
  }
  return NextResponse.json({ ok: true, config: result.config, mocked: result.mocked, mode });
}
