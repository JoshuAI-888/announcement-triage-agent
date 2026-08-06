"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "./Icon";
import type { RunStatusResult, WorkflowRunView } from "@/lib/types";

const POLL_MS = 4000; // how often we ask GitHub for run status
const MAX_TRACK_MS = 10 * 60 * 1000; // stop following a run after 10 min (safety)

function fmtElapsed(fromIso: string | null): string {
  if (!fromIso) return "0:00";
  const secs = Math.max(0, Math.floor((Date.now() - new Date(fromIso).getTime()) / 1000));
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function progressPct(run: WorkflowRunView): number | null {
  if (run.status === "completed") return 100;
  if (run.stepsTotal > 0) {
    // Cap below 100 while still running so it never reads "done" prematurely.
    return Math.min(95, Math.round((run.stepsCompleted / run.stepsTotal) * 100));
  }
  return null; // indeterminate (queued / no step data yet)
}

function activityLabel(run: WorkflowRunView): string {
  if (run.status === "queued") return "Queued — waiting for a runner";
  if (run.currentStep) return run.currentStep;
  if (run.status === "in_progress") return "Running…";
  return "Working…";
}

export function TopbarActions({ mode }: { mode: "local-dev" | "github" }) {
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState<"" | "run" | "eval">("");
  const [tracking, setTracking] = useState(false);
  const [run, setRun] = useState<WorkflowRunView | null>(null);
  const [done, setDone] = useState<WorkflowRunView | null>(null);
  const [, forceTick] = useState(0); // drives the once-a-second elapsed re-render
  const [backfillOpen, setBackfillOpen] = useState(false);
  const [asOf, setAsOf] = useState("");
  const [lookback, setLookback] = useState("1");

  const sawActive = useRef(false);
  const trackStart = useRef(0);

  const poll = useCallback(async () => {
    try {
      const res = await fetch("/api/run-status", { cache: "no-store" });
      if (!res.ok) return;
      const data = (await res.json()) as RunStatusResult;
      if (data.active) {
        sawActive.current = true;
        setRun(data.active);
        setDone(null);
      } else if (sawActive.current) {
        // We were following a run and it just finished — surface its conclusion.
        const finished = data.runs[0] ?? null;
        setRun(null);
        setDone(finished);
        setTracking(false);
      }
      if (Date.now() - trackStart.current > MAX_TRACK_MS) setTracking(false);
    } catch {
      // transient — keep the last known state, try again next tick
    }
  }, []);

  // Poll while tracking; also tick every second so elapsed time advances.
  useEffect(() => {
    if (!tracking) return;
    poll();
    const p = setInterval(poll, POLL_MS);
    const t = setInterval(() => forceTick((n) => n + 1), 1000);
    return () => {
      clearInterval(p);
      clearInterval(t);
    };
  }, [tracking, poll]);

  async function runNow(payload?: { as_of?: string; lookback_days?: string }) {
    setBusy("run");
    setStatus(null);
    setDone(null);
    setRun(null);
    sawActive.current = false;
    try {
      const res = await fetch("/api/run-now", {
        method: "POST",
        headers: payload ? { "Content-Type": "application/json" } : undefined,
        body: payload ? JSON.stringify(payload) : undefined,
      });
      const body = await res.json();
      setStatus(body.message || (res.ok ? "Dispatched." : "Failed."));
      if (res.ok && mode === "github") {
        trackStart.current = Date.now();
        setTracking(true); // begin following the run we just dispatched
      }
    } catch {
      setStatus("Could not reach the server.");
    } finally {
      setBusy("");
    }
  }

  function runBackfill() {
    if (!asOf) return;
    runNow({ as_of: asOf, lookback_days: lookback });
    setBackfillOpen(false);
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

  const pct = run ? progressPct(run) : null;
  const showProgress = tracking || run !== null;

  return (
    <div className="top-actions-wrap">
      <div className="top-actions">
        {status && !showProgress && (
          <span className="small muted" style={{ maxWidth: 320, textAlign: "right" }}>{status}</span>
        )}
        <span className="small muted">
          <i className={`status-dot ${mode === "local-dev" ? "warn" : ""}`}></i>{" "}
          {mode === "local-dev" ? "Local dev mode (mocked GitHub calls)" : "Connected to GitHub"}
        </span>
        <button className="btn secondary" type="button" onClick={runEval} disabled={busy !== ""}>
          <Icon code="f201" /> {busy === "eval" ? "Dispatching…" : "Run eval now"}
        </button>
        <button className="btn" type="button" onClick={() => runNow()} disabled={busy !== "" || tracking}>
          <Icon code="f04b" /> {busy === "run" ? "Dispatching…" : tracking ? "Running…" : "Run now"}
        </button>
        <button
          className="btn secondary"
          type="button"
          onClick={() => setBackfillOpen((o) => !o)}
          disabled={busy !== "" || tracking}
        >
          <Icon code="f1da" /> Backfill…
        </button>
      </div>

      {backfillOpen && (
        <div className="backfill-panel">
          <label className="small muted" htmlFor="backfill-as-of">
            As of
          </label>
          <input
            id="backfill-as-of"
            className="input"
            type="date"
            value={asOf}
            onChange={(e) => setAsOf(e.target.value)}
          />
          <label className="small muted" htmlFor="backfill-lookback">
            Lookback (days)
          </label>
          <select id="backfill-lookback" className="select" value={lookback} onChange={(e) => setLookback(e.target.value)}>
            <option value="1">1</option>
            <option value="2">2</option>
            <option value="5">5</option>
            <option value="7">7</option>
          </select>
          <button className="btn" type="button" onClick={runBackfill} disabled={!asOf || busy !== "" || tracking}>
            Run backfill
          </button>
        </div>
      )}

      {showProgress && (
        <div className="run-progress" role="status" aria-live="polite">
          {run ? (
            <>
              <div className="run-progress-head">
                <span className="run-progress-activity">
                  <span className={`run-dot ${run.status === "queued" ? "queued" : "active"}`}></span>
                  {activityLabel(run)}
                  {run.stepsTotal > 0 && (
                    <span className="muted"> · step {run.stepsCompleted}/{run.stepsTotal}</span>
                  )}
                </span>
                <span className="run-progress-meta mono">
                  {fmtElapsed(run.startedAt ?? run.createdAt)}
                  {run.event === "schedule" && <span className="muted"> · scheduled run</span>}
                  {" · "}
                  <a href={run.htmlUrl} target="_blank" rel="noreferrer">logs ↗</a>
                </span>
              </div>
              <div className={`run-bar ${pct === null ? "indeterminate" : ""}`}>
                <div className="run-bar-fill" style={pct === null ? undefined : { width: `${pct}%` }}></div>
              </div>
            </>
          ) : (
            <div className="run-progress-head">
              <span className="run-progress-activity">
                <span className="run-dot active"></span>Starting run…
              </span>
            </div>
          )}
        </div>
      )}

      {done && (
        <div className="run-progress">
          <div className="run-progress-head">
            <span className="run-progress-activity">
              <span className={`run-dot ${done.conclusion === "success" ? "ok" : done.conclusion === "skipped" ? "skip" : "fail"}`}></span>
              {done.conclusion === "success"
                ? "Run finished successfully"
                : done.conclusion === "skipped"
                ? "Run finished — nothing to do (schedule gate skipped it)"
                : `Run finished: ${done.conclusion ?? "unknown"}`}
            </span>
            <span className="run-progress-meta mono">
              <a href={done.htmlUrl} target="_blank" rel="noreferrer">logs ↗</a>
            </span>
          </div>
        </div>
      )}

      <style>{`
        .top-actions-wrap { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }
        .backfill-panel { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end;
          background: var(--surface-2, rgba(127,127,127,0.06)); border: 1px solid var(--border, rgba(127,127,127,0.18));
          border-radius: 10px; padding: 8px 12px; font-size: 12.5px; }
        .backfill-panel .input, .backfill-panel .select { padding: 4px 8px; font-size: 12.5px; }
        .run-progress { width: min(520px, 100%); background: var(--surface-2, rgba(127,127,127,0.06));
          border: 1px solid var(--border, rgba(127,127,127,0.18)); border-radius: 10px; padding: 8px 12px; }
        .run-progress-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; font-size: 12.5px; }
        .run-progress-activity { display: inline-flex; align-items: center; gap: 8px; font-weight: 600; }
        .run-progress-meta { white-space: nowrap; opacity: 0.85; }
        .run-progress-meta a { color: inherit; }
        .run-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex: 0 0 auto; }
        .run-dot.active { background: #2f6bff; box-shadow: 0 0 0 0 rgba(47,107,255,0.6); animation: run-pulse 1.4s infinite; }
        .run-dot.queued { background: #b0851f; animation: run-pulse 1.4s infinite; }
        .run-dot.ok { background: #2fae66; }
        .run-dot.skip { background: #8a8a8a; }
        .run-dot.fail { background: #d1495b; }
        .run-bar { position: relative; height: 6px; margin-top: 8px; border-radius: 999px;
          background: rgba(127,127,127,0.2); overflow: hidden; }
        .run-bar-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #2f6bff, #57a0ff);
          width: 0; transition: width 0.6s ease; }
        .run-bar.indeterminate .run-bar-fill { width: 40%; animation: run-slide 1.2s infinite ease-in-out; }
        @keyframes run-slide { 0% { margin-left: -40%; } 100% { margin-left: 100%; } }
        @keyframes run-pulse { 0% { box-shadow: 0 0 0 0 rgba(47,107,255,0.5); } 70% { box-shadow: 0 0 0 6px rgba(47,107,255,0); } 100% { box-shadow: 0 0 0 0 rgba(47,107,255,0); } }
        @media (prefers-reduced-motion: reduce) {
          .run-dot.active, .run-dot.queued { animation: none; }
          .run-bar.indeterminate .run-bar-fill { animation: none; margin-left: 30%; }
        }
      `}</style>
    </div>
  );
}
