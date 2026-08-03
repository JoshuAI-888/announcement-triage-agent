// portalAuth.ts — salted SHA-256 password hashing for the portal gate
// (CONTRACTS.md §8). This is a LIGHTWEIGHT app-level gate, not production
// auth: single shared password, no per-user identity, no lockout/rate-limit
// beyond what Vercel's own layer provides. Keep Vercel Deployment Protection
// on as the outer layer (DEPLOY.md §3).

import { randomBytes, createHash, timingSafeEqual } from "crypto";
import type { PortalAuth } from "./types";

export function hashPassword(password: string, salt: string): string {
  return createHash("sha256").update(`${salt}:${password}`, "utf8").digest("hex");
}

export function newPortalAuth(password: string): PortalAuth {
  const salt = randomBytes(16).toString("hex");
  return {
    salt,
    hash: hashPassword(password, salt),
    updated_at: new Date().toISOString(),
  };
}

export function verifyPassword(password: string, auth: PortalAuth): boolean {
  const candidate = hashPassword(password, auth.salt);
  const a = Buffer.from(candidate, "hex");
  const b = Buffer.from(auth.hash, "hex");
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

/** The seeded default: password "milfordsec". Used only if no portal_auth.json is found. */
export function defaultPortalAuth(): PortalAuth {
  return newPortalAuth("milfordsec");
}
