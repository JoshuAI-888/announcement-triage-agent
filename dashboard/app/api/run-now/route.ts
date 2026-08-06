// POST /api/run-now — workflow_dispatch daily-brief.yml (CONTRACTS.md §7).
// Accepts an optional JSON body { as_of?, lookback_days? } for a manual
// backfill (mirrors /api/run-eval's pattern); a plain "Run now" posts no body
// and stays a no-arg Daily digest dispatch. Mocked (logged, not called) in
// local dev mode — see lib/dataSource.ts.
import { NextResponse } from "next/server";
import { dispatchRunNow, mode, type RunNowInputs } from "@/lib/dataSource";

export async function POST(req: Request) {
  let body: RunNowInputs = {};
  try {
    body = (await req.json()) ?? {};
  } catch {
    // no body is fine — plain "Run now" posts without one
  }
  try {
    const { mocked } = await dispatchRunNow(body);
    return NextResponse.json({
      ok: true,
      mocked,
      mode,
      message: mocked
        ? "Local dev mode: logged the dispatch instead of calling GitHub. See server console."
        : "Dispatched daily-brief.yml on main.",
    });
  } catch (err) {
    return NextResponse.json({ error: "dispatch_failed", message: (err as Error).message }, { status: 502 });
  }
}
