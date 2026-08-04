// GET /api/pdf-log — out/pdf_log.jsonl, newest first, capped to the most
// recent 200 rows. Reads via lib/dataSource.ts's getPdfLog(), which uses the
// same LOCAL_DEV_MODE / GitHub-contents branching as the run-log and
// versions routes — never a hardcoded fetch. Malformed lines are skipped;
// a missing file returns an empty list (200), not a 500.
import { NextResponse } from "next/server";
import { getPdfLog } from "@/lib/dataSource";

export async function GET() {
  try {
    const rows = await getPdfLog(200);
    return NextResponse.json({ rows });
  } catch (err) {
    return NextResponse.json({ error: "read_failed", message: (err as Error).message }, { status: 500 });
  }
}
