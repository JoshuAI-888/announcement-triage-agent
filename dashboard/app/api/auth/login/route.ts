// POST /api/auth/login — portal password gate (CONTRACTS.md §8). Verifies the
// supplied password against the salted SHA-256 hash in dashboard/portal_auth.json
// (via lib/dataSource, GitHub-backed in prod, local file in dev), and on success
// sets a signed, httpOnly session cookie. This is a lightweight app-level gate,
// not user auth — there is no identity, just "knows the shared password."

import { NextResponse } from "next/server";
import { getPortalAuth } from "@/lib/dataSource";
import { verifyPassword } from "@/lib/portalAuth";
import { createSessionToken, SESSION_COOKIE } from "@/lib/session";

export async function POST(req: Request) {
  let password: unknown;
  try {
    const body = await req.json();
    password = body?.password;
  } catch {
    return NextResponse.json({ error: "bad_request", message: "expected JSON body { password }" }, { status: 400 });
  }
  if (typeof password !== "string" || password.length === 0) {
    return NextResponse.json({ error: "bad_request", message: "password is required" }, { status: 400 });
  }

  const auth = await getPortalAuth();
  if (!verifyPassword(password, auth)) {
    return NextResponse.json({ error: "invalid_password", message: "Incorrect password." }, { status: 401 });
  }

  const token = await createSessionToken();
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 12 * 60 * 60, // 12 hours, mirrors lib/session.ts's SESSION_TTL_MS
  });
  return res;
}
