// GET /api/run-status — live daily-brief workflow runs (status, current step,
// step-based progress) for the "Run now" progress bar and the ongoing/finished
// run history. Mocked to an empty list in local dev mode (no GitHub token).
import { NextResponse } from "next/server";
import { getRunStatus } from "@/lib/dataSource";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const status = await getRunStatus();
    return NextResponse.json(status, { headers: { "Cache-Control": "no-store" } });
  } catch (err) {
    return NextResponse.json({ error: "status_failed", message: (err as Error).message }, { status: 502 });
  }
}
