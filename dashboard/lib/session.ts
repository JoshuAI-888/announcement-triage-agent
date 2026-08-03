// session.ts — lightweight signed session cookie for the portal password gate
// (CONTRACTS.md §8). NOT production auth: there is no user identity, no
// rotation, no revocation list — just an HMAC-signed, time-boxed token proving
// "this browser supplied the portal password once." Keep Vercel's own
// Deployment Protection on as the outer, harder layer (see DEPLOY.md §3).
//
// Implemented with Web Crypto (`crypto.subtle`) rather than Node's `crypto`
// module so the exact same code runs in both the Edge middleware (which gates
// every route) and Node route handlers — no Buffer, no dual implementations
// to keep in sync.

const encoder = new TextEncoder();
const decoder = new TextDecoder();

export const SESSION_COOKIE = "portal_session";
const SESSION_TTL_MS = 12 * 60 * 60 * 1000; // 12 hours

function bytesToBase64Url(bytes: Uint8Array): string {
  let str = "";
  for (let i = 0; i < bytes.length; i++) str += String.fromCharCode(bytes[i]);
  const b64 = btoa(str);
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function base64UrlToBytes(b64url: string): Uint8Array<ArrayBuffer> {
  const pad = (4 - (b64url.length % 4)) % 4;
  const b64 = b64url.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat(pad);
  const str = atob(b64);
  const bytes = new Uint8Array(str.length);
  for (let i = 0; i < str.length; i++) bytes[i] = str.charCodeAt(i);
  return bytes;
}

async function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
    "verify",
  ]);
}

export function defaultSecret(): string {
  const s = process.env.PORTAL_SESSION_SECRET;
  if (s && s.length > 0) return s;
  // Dev fallback only — always set PORTAL_SESSION_SECRET in any real deploy.
  // eslint-disable-next-line no-console
  console.warn(
    "[portal-auth] PORTAL_SESSION_SECRET is not set — using an insecure development fallback. " +
      "Set it before deploying."
  );
  return "insecure-local-dev-secret-do-not-use-in-production";
}

export async function createSessionToken(secret: string = defaultSecret()): Promise<string> {
  const payload = { iat: Date.now(), exp: Date.now() + SESSION_TTL_MS };
  const body = bytesToBase64Url(encoder.encode(JSON.stringify(payload)));
  const key = await hmacKey(secret);
  const sig = await crypto.subtle.sign("HMAC", key, encoder.encode(body));
  const sigB64 = bytesToBase64Url(new Uint8Array(sig));
  return `${body}.${sigB64}`;
}

export async function verifySessionToken(token: string | undefined | null, secret: string = defaultSecret()): Promise<boolean> {
  if (!token) return false;
  const parts = token.split(".");
  if (parts.length !== 2) return false;
  const [body, sig] = parts;
  try {
    const key = await hmacKey(secret);
    const valid = await crypto.subtle.verify("HMAC", key, base64UrlToBytes(sig), encoder.encode(body));
    if (!valid) return false;
    const payload = JSON.parse(decoder.decode(base64UrlToBytes(body))) as { iat: number; exp: number };
    if (typeof payload.exp !== "number" || Date.now() > payload.exp) return false;
    return true;
  } catch {
    return false;
  }
}
