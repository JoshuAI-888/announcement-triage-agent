// POST /api/run-now — workflow_dispatch daily-brief.yml (CONTRACTS.md §7).
// Mocked (logged, not called) in local dev mode — see lib/dataSource.ts.
import { NextResponse } from "next/server";
import { dispatchRunNow, mode } from "@/lib/dataSource";

export async function POST() {
  try {
    const { mocked } = await dispatchRunNow();
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
