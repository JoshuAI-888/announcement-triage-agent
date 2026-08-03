// GET /api/oauth/google — STUB. Paired with /api/gmail/draft (CONTRACTS.md
// §7); the Google OAuth flow for a live Gmail draft is Phase 2 and out of
// scope for this build. Left as a clearly-marked stub so the route exists.
import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json(
    {
      error: "not_implemented",
      message: "Google OAuth for the live Gmail draft (Phase 2) is not built yet. See docs/CONTRACTS.md §7.",
    },
    { status: 501 }
  );
}
