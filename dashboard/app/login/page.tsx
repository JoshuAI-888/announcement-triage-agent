"use client";

// Built from milford-core-portal-design/assets/templates/login.html (CONTRACTS.md §8).
// Illustrative internal portal template, adapted: a single shared portal
// password instead of per-user email/SSO (there is no user directory here).

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Icon } from "@/components/Icon";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/today";

  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.message || "Incorrect password.");
        setLoading(false);
        return;
      }
      router.push(next);
      router.refresh();
    } catch {
      setError("Could not reach the server. Try again.");
      setLoading(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-form" aria-labelledby="login-title">
        <img className="logo" src="/brand/milfordasset.svg" alt="Milford" />
        <p className="eyebrow">Milford Workspace</p>
        <h1 id="login-title">SEC Announcement Triage Agent.</h1>
        <p className="intro">Sign in with the portal password to view the operator dashboard.</p>
        <form onSubmit={onSubmit}>
          <div className="field">
            <label htmlFor="password">Portal password</label>
            <input
              className="input"
              id="password"
              type="password"
              autoComplete="current-password"
              required
              autoFocus
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && (
            <div className="banner banner-danger" role="alert">
              <Icon code="f071" />
              <span>{error}</span>
            </div>
          )}
          <button className="btn" type="submit" disabled={loading}>
            <Icon code="f2f6" /> {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="small muted" style={{ marginTop: 28 }}>
          Illustrative internal tool. This is a lightweight app-level gate (a single shared
          password), not production auth &mdash; Vercel deployment protection is the outer layer
          in production. See dashboard/README.md.
        </p>
      </section>
      <aside className="login-visual" aria-label="Announcement triage introduction">
        <p className="eyebrow">Invested in you</p>
        <div className="quote">
          One governed view of the <b>daily announcement brief</b>, its trust numbers and its
          configuration.
        </div>
        <p>Designed around Milford&rsquo;s public visual system, adapted for this operator tool.</p>
        <div className="security">
          <span>
            <Icon code="f3ed" /> Portal password gate
          </span>
          <span>
            <Icon code="f017" /> 12-hour session
          </span>
          <span>
            <Icon code="f126" /> Reads/writes main via GitHub
          </span>
        </div>
      </aside>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
