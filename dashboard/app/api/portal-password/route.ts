// POST /api/portal-password — change the portal password (CONTRACTS.md §8).
// Requires the current password, then writes a new salted SHA-256 hash. In
// production this commits dashboard/portal_auth.json to main via the GitHub
// API (the same commit path config edits use); it takes effect on the next
// deploy (~1 min, Vercel's Git integration auto-redeploys on the commit). In
// local dev mode it writes the file directly (see lib/dataSource.ts —
// portal_auth.json lives inside dashboard/, so this is a real local write,
// not a mock).
import { NextResponse } from "next/server";
import { getPortalAuth, savePortalAuth } from "@/lib/dataSource";
import { newPortalAuth, verifyPassword } from "@/lib/portalAuth";

export async function POST(req: Request) {
  let body: { current_password?: unknown; new_password?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "bad_request", message: "expected JSON body" }, { status: 400 });
  }
  const { current_password, new_password } = body;
  if (typeof current_password !== "string" || typeof new_password !== "string") {
    return NextResponse.json({ error: "bad_request", message: "current_password and new_password are required strings" }, { status: 400 });
  }
  if (new_password.length < 8) {
    return NextResponse.json({ error: "weak_password", message: "new password must be at least 8 characters" }, { status: 400 });
  }

  const current = await getPortalAuth();
  if (!verifyPassword(current_password, current)) {
    return NextResponse.json({ error: "invalid_password", message: "current password is incorrect" }, { status: 401 });
  }

  const next = newPortalAuth(new_password);
  const { mocked } = await savePortalAuth(next);
  return NextResponse.json({
    ok: true,
    mocked,
    message: mocked
      ? "Local dev mode: wrote dashboard/portal_auth.json locally (production commits it to main instead)."
      : "Password updated. Takes effect on the next deploy (~1 min).",
  });
}
