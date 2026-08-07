"use client";

// Live daily-brief workflow runs — ongoing AND finished — polled from
// /api/run-status. Sits above the committed run_log table on the History page so
// the operator can see queued/in-progress runs (which never reach run_log) too.
// Auto-refreshes every 10s; a manual Refresh button forces an immediate reload.
// Columns are multi-key sortable (plain click = primary; shift-click adds a
// secondary key), matching FilingsTable / RunLogTable.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { RunStatusResult, WorkflowRunView } from "@/lib/types";
import { fmtDateTime } from "@/lib/format";
import { cmpNum, cmpStr, useMultiSort } from "@/lib/sort";

const POLL_MS = 10000;

type SortKey = "runNumber" | "event" | "status" | "started" | "duration";

function durationSecs(run: WorkflowRunView): number {
  const start = run.startedAt ?? run.createdAt;
  const end = run.status === "completed" ? run.updatedAt : new Date().toISOString();
  return Math.max(0, Math.floor((new Date(end).getTime() - new Date(start).getTime()) / 1000));
}

function fmtDuration(secs: number): string {
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

function triggerLabel(run: WorkflowRunView): string {
  return run.event === "workflow_dispatch" ? "Manual (Run now)" : run.event === "schedule" ? "Scheduled" : run.event;
}

export function WorkflowRuns() {
  const [data, setData] = useState<RunStatusResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [, tick] = useState(0);
  const aliveRef = useRef(true);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const res = await fetch("/api/run-status", { cache: "no-store" });
      if (!res.ok) {
        if (aliveRef.current) setErr("Could not load workflow runs.");
        return;
      }
      const json = (await res.json()) as RunStatusResult;
      if (aliveRef.current) {
        setData(json);
        setErr(null);
      }
    } catch {
      if (aliveRef.current) setErr("Could not reach the server.");
    } finally {
      if (aliveRef.current) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    load();
    const p = setInterval(load, POLL_MS);
    const t = setInterval(() => tick((n) => n + 1), 1000); // advance live durations
    return () => {
      aliveRef.current = false;
      clearInterval(p);
      clearInterval(t);
    };
  }, [load]);

  const runs = data?.runs ?? [];
  const anyActive = runs.some((r) => r.status !== "completed");

  const comparators = useMemo<Record<SortKey, (a: WorkflowRunView, b: WorkflowRunView) => number>>(
    () => ({
      runNumber: (a, b) => cmpNum(a.runNumber, b.runNumber),
      event: (a, b) => cmpStr(triggerLabel(a), triggerLabel(b)),
      status: (a, b) => cmpStr(statusBadge(a).label, statusBadge(b).label),
      started: (a, b) => cmpStr(a.startedAt ?? a.createdAt, b.startedAt ?? b.createdAt),
      duration: (a, b) => cmpNum(durationSecs(a), durationSecs(b)),
    }),
    []
  );

  const { sorted, sorts, onHeaderClick, rankOf, dirOf } = useMultiSort<WorkflowRunView, SortKey>(runs, comparators, [
    { key: "started", dir: "desc" },
  ]);

  function Th({ label, sortKeyName, alignRight }: { label: string; sortKeyName: SortKey; alignRight?: boolean }) {
    const rank = rankOf(sortKeyName);
    const dir = dirOf(sortKeyName);
    return (
      <th
        className={`sortable${alignRight ? " align-right" : ""}`}
        onClick={(e) => onHeaderClick(sortKeyName, e.shiftKey)}
        title="Click to sort. Shift-click to add as a secondary sort key."
      >
        {label}
        {rank !== null && (
          <span className="sort-arrow">
            {dir === "asc" ? "▲" : "▼"}
            {sorts.length > 1 && <sup className="sort-rank">{rank}</sup>}
          </span>
        )}
      </th>
    );
  }

  return (
    <div className="card card-pad" style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>
          Workflow runs {anyActive && <span className="badge blue" style={{ marginLeft: 6 }}>live</span>}
        </h2>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span className="small muted">Ongoing and finished daily-brief runs (auto-refreshes)</span>
          <button
            type="button"
            className="btn secondary refresh-btn"
            onClick={load}
            disabled={refreshing}
            style={{ minHeight: 32, padding: "0 12px" }}
            title="Reload workflow runs now"
          >
            {refreshing ? "Refreshing…" : "↻ Refresh"}
          </button>
        </div>
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
        <div className="table-wrap table-scroll" style={{ marginTop: 12 }}>
          <table>
            <thead>
              <tr>
                <Th label="Run" sortKeyName="runNumber" />
                <Th label="Trigger" sortKeyName="event" />
                <Th label="Status" sortKeyName="status" />
                <Th label="Started" sortKeyName="started" />
                <Th label="Duration" sortKeyName="duration" alignRight />
                <th>Brief</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => {
                const b = statusBadge(r);
                return (
                  <tr key={r.id}>
                    <td className="mono small">#{r.runNumber}</td>
                    <td className="small">{triggerLabel(r)}</td>
                    <td><span className={`badge ${b.cls}`}>{b.label}</span></td>
                    <td className="mono small">{fmtDateTime(r.startedAt ?? r.createdAt)}</td>
                    <td className="align-right tabular">{fmtDuration(durationSecs(r))}</td>
                    <td className="small">
                      {r.briefUrl ? (
                        <a href={r.briefUrl} target="_blank" rel="noreferrer" title="Open the brief HTML this run produced">view brief ↗</a>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
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
