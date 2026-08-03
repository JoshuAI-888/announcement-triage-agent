// proxy.ts — the portal password gate (CONTRACTS.md §8). Runs on the Edge
// runtime and gates every route/API except /login and the auth endpoints
// themselves and Next's own static assets. This is a LIGHTWEIGHT app-level
// gate (a single shared password, a signed cookie, no user identity) — keep
// Vercel's own Deployment Protection on as the outer, harder layer
// (see README.md / DEPLOY.md §3 upstream). Do not treat this as sufficient on
// its own.
//
// Named `proxy.ts` (not `middleware.ts`): Next.js 16 renamed the root-level
// request-gating convention from "middleware" to "proxy" — same job, same
// place, new file/export name.

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { SESSION_COOKIE, verifySessionToken } from "./lib/session";

const PUBLIC_PATHS = new Set(["/login", "/api/auth/login"]);

export async function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (PUBLIC_PATHS.has(pathname)) {
    return NextResponse.next();
  }

  const token = req.cookies.get(SESSION_COOKIE)?.value;
  const valid = await verifySessionToken(token);

  if (!valid) {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json({ error: "unauthorized", message: "sign in to the portal first" }, { status: 401 });
    }
    const loginUrl = new URL("/login", req.url);
    if (pathname !== "/") loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  // Exclude Next internals and the public asset folders (brand/fonts/styles)
  // copied from milford-core-portal-design into public/.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|brand/|fonts/|styles/).*)"],
};
