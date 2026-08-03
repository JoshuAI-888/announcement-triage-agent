// GET /api/gmail/draft — STUB. Live Gmail draft read/write (CONTRACTS.md §7)
// is Phase 2 (Google OAuth + the Gmail API) and is explicitly OUT OF SCOPE for
// this build. Do not wire this up to a real Gmail client here — this route
// exists only so the frontend has a stable endpoint to call once Phase 2
// lands, and so its absence doesn't silently 404 with no explanation.
import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json(
    {
      error: "not_implemented",
      message:
        "Gmail draft integration (OAuth + live Gmail draft read) is a Phase 2 feature and is not built yet. " +
        "See docs/CONTRACTS.md §7 and dashboard/README.md.",
    },
    { status: 501 }
  );
}
