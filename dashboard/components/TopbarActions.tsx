"use client";

import { useState } from "react";
import { Icon } from "./Icon";

export function TopbarActions({ mode }: { mode: "local-dev" | "github" }) {
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState<"" | "run" | "eval">("");

  async function runNow() {
    setBusy("run");
    setStatus(null);
    try {
      const res = await fetch("/api/run-now", { method: "POST" });
      const body = await res.json();
      setStatus(body.message || (res.ok ? "Dispatched." : "Failed."));
    } catch {
      setStatus("Could not reach the server.");
    } finally {
      setBusy("");
    }
  }

  async function runEval() {
    setBusy("eval");
    setStatus(null);
    try {
      const res = await fetch("/api/run-eval", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const body = await res.json();
      setStatus(body.message || (res.ok ? "Dispatched." : "Failed."));
    } catch {
      setStatus("Could not reach the server.");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="top-actions">
      {status && <span className="small muted" style={{ maxWidth: 320, textAlign: "right" }}>{status}</span>}
      <span className="small muted">
        <i className={`status-dot ${mode === "local-dev" ? "warn" : ""}`}></i> {mode === "local-dev" ? "Local dev mode (mocked GitHub calls)" : "Connected to GitHub"}
      </span>
      <button className="btn secondary" type="button" onClick={runEval} disabled={busy !== ""}>
        <Icon code="f201" /> {busy === "eval" ? "Dispatching…" : "Run eval now"}
      </button>
      <button className="btn" type="button" onClick={runNow} disabled={busy !== ""}>
        <Icon code="f04b" /> {busy === "run" ? "Dispatching…" : "Run now"}
      </button>
    </div>
  );
}
