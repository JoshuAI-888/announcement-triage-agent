// GET /api/filings — the latest out/filings/<date>.json (or intraday
// <date>T<HH-MM>.json) classification run, picked by filename. Reads via
// lib/dataSource.ts's getLatestFilings(), which uses the same LOCAL_DEV_MODE
// / GitHub-contents branching as the run-log and pdf-log routes — never a
// hardcoded fetch. A missing directory/file returns { run: null } (200),
// not a 500.
import { NextResponse } from "next/server";
import { getLatestFilings } from "@/lib/dataSource";

export async function GET() {
  try {
    const run = await getLatestFilings();
    return NextResponse.json({ run });
  } catch (err) {
    return NextResponse.json({ error: "read_failed", message: (err as Error).message }, { status: 500 });
  }
}
