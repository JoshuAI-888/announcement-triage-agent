"use client";

// FilingsTable — client-side sortable table for out/filings/<date>.json's
// `filings[]` (CONTRACTS.md). Flags arrive pre-rendered as {code, label, why}
// from the Python side, so this only ever displays label/why, never the raw
// code. Sorting is client-only (no server round trip); default order is
// whatever the artifact shipped.

import { useMemo, useState } from "react";
import { fmtDateTime, fmtPct } from "@/lib/format";
import type { FilingRow } from "@/lib/types";

type SortKey = "company_name" | "ticker" | "doc_type_label" | "materiality_label" | "confidence" | "published_at";
type SortDir = "asc" | "desc";

function materialityBadgeClass(materiality: string): string {
  const m = materiality.toLowerCase();
  if (m === "material") return "badge red";
  if (m === "immaterial") return "badge";
  if (m.includes("needs") || m.includes("more_info") || m.includes("insufficient")) return "badge orange";
  return "badge";
}

export function FilingsTable({ filings }: { filings: FilingRow[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("published_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const sorted = useMemo(() => {
    const rows = [...filings];
    rows.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      let cmp: number;
      if (typeof av === "number" && typeof bv === "number") {
        cmp = av - bv;
      } else {
        cmp = String(av).localeCompare(String(bv));
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return rows;
  }, [filings, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  function Th({ label, sortKeyName }: { label: string; sortKeyName: SortKey }) {
    const active = sortKey === sortKeyName;
    return (
      <th className="sortable" onClick={() => toggleSort(sortKeyName)}>
        {label}
        {active && <span className="sort-arrow">{sortDir === "asc" ? "▲" : "▼"}</span>}
      </th>
    );
  }

  if (filings.length === 0) {
    return (
      <div className="card card-pad empty">
        <p>No filings recorded for the latest run.</p>
      </div>
    );
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <Th label="Company" sortKeyName="company_name" />
            <Th label="Ticker" sortKeyName="ticker" />
            <Th label="Type" sortKeyName="doc_type_label" />
            <Th label="Classification" sortKeyName="materiality_label" />
            <th className="align-right sortable" onClick={() => toggleSort("confidence")}>
              Confidence
              {sortKey === "confidence" && <span className="sort-arrow">{sortDir === "asc" ? "▲" : "▼"}</span>}
            </th>
            <th>Why</th>
            <th>Flags</th>
            <Th label="Published" sortKeyName="published_at" />
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((f) => (
            <tr key={f.announcement_id}>
              <td>{f.company_name}</td>
              <td className="mono small">{f.ticker}</td>
              <td className="small">{f.doc_type_label}</td>
              <td>
                <span className={materialityBadgeClass(f.materiality)}>{f.materiality_label}</span>
              </td>
              <td className="align-right tabular">{fmtPct(f.confidence, 0)}</td>
              <td className="small truncate" title={f.rationale}>
                {f.rationale}
              </td>
              <td>
                {f.flags.length === 0 ? (
                  <span className="muted">&mdash;</span>
                ) : (
                  <span className="flag-chip-row">
                    {f.flags.map((flag) => (
                      <span key={flag.code} className="badge orange" title={flag.why}>
                        {flag.label}
                      </span>
                    ))}
                  </span>
                )}
              </td>
              <td className="mono small">{fmtDateTime(f.published_at)}</td>
              <td>
                <a href={f.source_url} target="_blank" rel="noopener noreferrer">
                  Filing &#8599;
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
