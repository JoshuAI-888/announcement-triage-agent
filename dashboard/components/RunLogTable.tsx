"use client";

// RunLogTable — client-side, multi-key-sortable table for the completed
// out/run_log.jsonl rows shown on the History page. history/page.tsx is a
// server component (fetches getRunLog() server-side); this component just
// takes the rows as a prop and owns sort/scroll/UI state client-side, same
// pattern (and same sort UX) as FilingsTable.

import { useMemo } from "react";
import type { RunLogRow } from "@/lib/types";
import { explainFlag, KIND_LABEL } from "@/lib/flags";
import { fmtDateTime, fmtNzd } from "@/lib/format";
import { modelRole } from "@/lib/models";
import { cmpNum, cmpStr, useMultiSort } from "@/lib/sort";

type SortKey =
  | "ts"
  | "kind"
  | "processed"
  | "new"
  | "deduped"
  | "material"
  | "needs_look"
  | "escalations"
  | "guardrail_count"
  | "total_cost_nzd"
  | "runtime_seconds"
  | "prompt_version"
  | "model_primary";

function guardrailCount(r: RunLogRow): number {
  return Object.values(r.guardrail_flag_counts || {}).reduce((sum, v) => sum + v, 0);
}

export function RunLogTable({ rows }: { rows: RunLogRow[] }) {
  const comparators = useMemo<Record<SortKey, (a: RunLogRow, b: RunLogRow) => number>>(
    () => ({
      ts: (a, b) => cmpStr(a.ts, b.ts),
      kind: (a, b) => cmpStr(KIND_LABEL[a.kind] ?? a.kind, KIND_LABEL[b.kind] ?? b.kind),
      processed: (a, b) => cmpNum(a.processed, b.processed),
      new: (a, b) => cmpNum(a.new, b.new),
      deduped: (a, b) => cmpNum(a.deduped, b.deduped),
      material: (a, b) => cmpNum(a.material, b.material),
      needs_look: (a, b) => cmpNum(a.needs_look, b.needs_look),
      escalations: (a, b) => cmpNum(a.escalations, b.escalations),
      guardrail_count: (a, b) => cmpNum(guardrailCount(a), guardrailCount(b)),
      total_cost_nzd: (a, b) => cmpNum(a.total_cost_nzd, b.total_cost_nzd),
      runtime_seconds: (a, b) => cmpNum(a.runtime_seconds, b.runtime_seconds),
      prompt_version: (a, b) => cmpStr(a.prompt_version, b.prompt_version),
      model_primary: (a, b) => cmpStr(a.model_primary, b.model_primary),
    }),
    []
  );

  const { sorted, sorts, onHeaderClick, rankOf, dirOf } = useMultiSort<RunLogRow, SortKey>(rows, comparators, [
    { key: "ts", dir: "desc" },
  ]);

  function Th({ label, sortKeyName, alignRight }: { label: string; sortKeyName: SortKey; alignRight?: boolean }) {
    const rank = rankOf(sortKeyName);
    const dir = dirOf(sortKeyName);
    const active = rank !== null;
    return (
      <th
        className={`sortable${alignRight ? " align-right" : ""}`}
        onClick={(e) => onHeaderClick(sortKeyName, e.shiftKey)}
        title="Click to sort. Shift-click to add as a secondary sort key."
      >
        {label}
        {active && (
          <span className="sort-arrow">
            {dir === "asc" ? "▲" : "▼"}
            {sorts.length > 1 && <sup className="sort-rank">{rank}</sup>}
          </span>
        )}
      </th>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="card card-pad empty">
        <p>No rows in out/run_log.jsonl yet in this checkout.</p>
      </div>
    );
  }

  return (
    <div className="table-wrap table-scroll">
      <table>
        <thead>
          <tr>
            <Th label="Date / time (UTC)" sortKeyName="ts" />
            <Th label="Kind" sortKeyName="kind" />
            <Th label="Processed" sortKeyName="processed" />
            <Th label="New" sortKeyName="new" />
            <Th label="Deduped" sortKeyName="deduped" />
            <Th label="Material" sortKeyName="material" />
            <Th label="Needs look" sortKeyName="needs_look" />
            <Th label="Escalations" sortKeyName="escalations" />
            <Th label="Guardrail flags" sortKeyName="guardrail_count" />
            <Th label="Cost (NZD)" sortKeyName="total_cost_nzd" alignRight />
            <Th label="Runtime (s)" sortKeyName="runtime_seconds" alignRight />
            <Th label="Prompt" sortKeyName="prompt_version" />
            <Th label="Model" sortKeyName="model_primary" />
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={`${r.ts}-${i}`}>
              <td className="mono small">{fmtDateTime(r.ts)}</td>
              <td>
                <span className={`badge ${r.kind === "intraday" ? "orange" : r.kind === "backfill" ? "purple" : ""}`}>
                  {KIND_LABEL[r.kind] ?? r.kind}
                </span>
              </td>
              <td>{r.processed}</td>
              <td>{r.new}</td>
              <td>{r.deduped}</td>
              <td>{r.material}</td>
              <td>{r.needs_look}</td>
              <td>
                <span className={r.escalations > 0 ? "badge orange" : "badge"}>{r.escalations}</span>
              </td>
              <td className="small">
                {Object.keys(r.guardrail_flag_counts || {}).length === 0 ? (
                  "—"
                ) : (
                  <span className="flag-chip-row">
                    {Object.entries(r.guardrail_flag_counts).map(([k, v]) => {
                      const info = explainFlag(k);
                      return (
                        <span key={k} title={info.why || info.meaning}>
                          {info.label} ({v})
                        </span>
                      );
                    })}
                  </span>
                )}
              </td>
              <td className="align-right tabular">{fmtNzd(r.total_cost_nzd)}</td>
              <td className="align-right tabular">{r.runtime_seconds.toFixed(1)}</td>
              <td>{r.prompt_version}</td>
              <td className="mono small" title={modelRole(r.model_primary).role} style={{ cursor: "help" }}>
                {r.model_primary} <span className="muted">({modelRole(r.model_primary).label})</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
