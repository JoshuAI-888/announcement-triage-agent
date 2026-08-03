// GET /api/eval-summary — evals/eval_summary.json plus a computed `stale`
// boolean (CONTRACTS.md §7): compares the live runtime_config's eval
// fingerprint (lib/fingerprint.ts, replicating src/config_schema.py exactly)
// against the fingerprint committed in eval_summary.json.
import { NextResponse } from "next/server";
import { getTrustStatus } from "@/lib/dataSource";

export async function GET() {
  const { summary, liveFingerprint, stale } = await getTrustStatus();
  if (!summary) {
    return NextResponse.json({ summary: null, live_fingerprint: liveFingerprint, stale: true, message: "evals/eval_summary.json not found" });
  }
  return NextResponse.json({ ...summary, live_fingerprint: liveFingerprint, stale });
}
