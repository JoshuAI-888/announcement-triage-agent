"use client";

// Live daily-brief workflow runs — ongoing AND finished — polled from
// /api/run-status. Sits above the committed run_log table on the History page so
// the operator can see queued/in-progress runs (which never reach run_log) too.
import { useEffect, useState } from "react";
import type { RunStatusResult, WorkflowRunView } from "@/lib/types";
import { fmtDateTime } from "@/lib/format";

const POLL_MS = 10000;

function duration(run: WorkflowRunView): string {
  const start = run.startedAt ?? run.createdAt;
  const end = run.status === "completed" ? run.updatedAt : new Date().toISOString();
  const secs = Math.max(0, Math.floor((new Date(end).getTime() - new Date(start).getTime()) / 1000));
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function statusBadge(run: WorkflowRunView): { cls: string; label: string } {
  if (run.status !== "completed") {
    if (run.status === "queued" || run.status === "pending" || run.status === "waiting" || run.status === "requested") {
      return { cls: "orange", label: "Queued" };
    }
    return { cls: "blue", label: run.currentStep ? `In progress · ${run.currentStep}` : "In progress" };
  }
  switch (run.conclusion) {
    case "success":
      return { cls: "green", label: "Success" };
    case "skipped":
      return { cls: "", label: "Skipped" };
    case "cancelled":
      return { cls: "", label: "Cancelled" };
    default:
      return { cls: "red", label: run.conclusion ?? "Failed" };
  }
}

export function WorkflowRuns() {
  const [data, setData] = useState<RunStatusResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [, tick] = useState(0);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const res = await fetch("/api/run-status", { cache: "no-store" });
        if (!res.ok) {
          if (alive) setErr("Could not load workflow runs.");
          return;
        }
        const json = (await res.json()) as RunStatusResult;
        if (alive) {
          setData(json);
          setErr(null);
        }
      } catch {
        if (alive) setErr("Could not reach the server.");
      }
    }
    load();
    const p = setInterval(load, POLL_MS);
    const t = setInterval(() => tick((n) => n + 1), 1000); // advance live durations
    return () => {
      alive = false;
      clearInterval(p);
      clearInterval(t);
    };
  }, []);

  const runs = data?.runs ?? [];
  const anyActive = runs.some((r) => r.status !== "completed");

  return (
    <div className="card card-pad" style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>
          Workflow runs {anyActive && <span className="badge blue" style={{ marginLeft: 6 }}>live</span>}
        </h2>
        <span className="small muted">Ongoing and finished daily-brief runs (auto-refreshes)</span>
      </div>

      {data?.mode === "local-dev" ? (
        <p className="small muted" style={{ marginTop: 10 }}>
          Live workflow runs appear here when the portal is connected to GitHub (production). Local dev mode mocks GitHub calls.
        </p>
      ) : err && !data ? (
        <p className="small muted" style={{ marginTop: 10 }}>{err}</p>
      ) : runs.length === 0 ? (
        <p className="small muted" style={{ marginTop: 10 }}>{data ? "No recent runs." : "Loading…"}</p>
      ) : (
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Trigger</th>
                <th>Status</th>
                <th>Started</th>
                <th className="align-right">Duration</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const b = statusBadge(r);
                return (
                  <tr key={r.id}>
                    <td className="mono small">#{r.runNumber}</td>
                    <td className="small">{r.event === "workflow_dispatch" ? "Manual (Run now)" : r.event === "schedule" ? "Scheduled" : r.event}</td>
                    <td><span className={`badge ${b.cls}`}>{b.label}</span></td>
                    <td className="mono small">{fmtDateTime(r.startedAt ?? r.createdAt)}</td>
                    <td className="align-right tabular">{duration(r)}</td>
                    <td className="small"><a href={r.htmlUrl} target="_blank" rel="noreferrer">logs ↗</a></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
