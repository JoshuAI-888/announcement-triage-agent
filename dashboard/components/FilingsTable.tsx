"use client";

// FilingsTable — client-side sortable table for out/filings/<date>.json's
// `filings[]` (CONTRACTS.md). Flags arrive pre-rendered as {code, label, why}
// from the Python side, so this only ever displays label/why, never the raw
// code. Sorting, search, and row-expand are all client-only (no server round
// trip); default order is by published_at, newest first.
//
// Sort UX: plain click on a header sets/toggles that column as the sole
// (primary) sort key. Shift-click adds it as a secondary/tertiary key
// instead, applied in the order added — the header shows a small superscript
// rank ("1"/"2"/"3") whenever more than one key is active.

import { useMemo, useState } from "react";
import { fmtDateTime, fmtPct } from "@/lib/format";
import type { FilingRow } from "@/lib/types";
import { docTypeBlurb, extractFormCode } from "@/lib/docTypes";
import { cmpNum, cmpStr, useMultiSort } from "@/lib/sort";

type SortKey =
  | "company_name"
  | "ticker"
  | "doc_type_label"
  | "materiality"
  | "confidence"
  | "rationale"
  | "flags_count"
  | "published_at";

const RATIONALE_WORD_CAP = 100;

function materialityBadgeClass(materiality: string): string {
  const m = materiality.toLowerCase();
  if (m === "material") return "badge green";
  if (m === "immaterial") return "badge";
  if (m.includes("needs") || m.includes("more_info") || m.includes("insufficient")) return "badge orange";
  return "badge";
}

/** material > needs/insufficient > immaterial, per the frozen color/priority contract. */
function materialityRank(materiality: string): number {
  const m = materiality.toLowerCase();
  if (m === "material") return 0;
  if (m.includes("needs") || m.includes("more_info") || m.includes("insufficient")) return 1;
  if (m === "immaterial") return 2;
  return 3;
}

function typeTooltip(label: string): string {
  const code = extractFormCode(label);
  const blurb = docTypeBlurb(code);
  return blurb ?? `${label} — a document type reported to the SEC.`;
}

function capWords(text: string, maxWords: number): { text: string; truncated: boolean } {
  const words = text.trim().split(/\s+/);
  if (words.length <= maxWords) return { text, truncated: false };
  return { text: words.slice(0, maxWords).join(" ") + "…", truncated: true };
}

function matchesSearch(f: FilingRow, needle: string): boolean {
  if (!needle) return true;
  const haystack = [f.company_name, f.ticker, f.doc_type_label, f.materiality_label, f.rationale].join(" \n ").toLowerCase();
  return haystack.includes(needle);
}

export function FilingsTable({ filings }: { filings: FilingRow[] }) {
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return filings;
    return filings.filter((f) => matchesSearch(f, needle));
  }, [filings, search]);

  const comparators = useMemo<Record<SortKey, (a: FilingRow, b: FilingRow) => number>>(
    () => ({
      company_name: (a, b) => cmpStr(a.company_name, b.company_name),
      ticker: (a, b) => cmpStr(a.ticker, b.ticker),
      doc_type_label: (a, b) => cmpStr(a.doc_type_label, b.doc_type_label),
      materiality: (a, b) => materialityRank(a.materiality) - materialityRank(b.materiality),
      confidence: (a, b) => cmpNum(a.confidence, b.confidence),
      rationale: (a, b) => cmpStr(a.rationale, b.rationale),
      flags_count: (a, b) => cmpNum(a.flags.length, b.flags.length),
      published_at: (a, b) => cmpStr(a.published_at, b.published_at),
    }),
    []
  );

  const { sorted, sorts, onHeaderClick, rankOf, dirOf } = useMultiSort<FilingRow, SortKey>(filtered, comparators, [
    { key: "materiality", dir: "asc" },
    { key: "published_at", dir: "desc" },
  ]);

  function toggleExpanded(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

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

  if (filings.length === 0) {
    return (
      <div className="card card-pad empty">
        <p>No filings recorded for the latest run.</p>
      </div>
    );
  }

  return (
    <>
      <div className="table-toolbar">
        <input
          className="input search-input"
          type="search"
          placeholder="Search company, ticker, type, classification, rationale…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search filings"
        />
        <span className="small muted">
          {sorted.length} of {filings.length}
        </span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <Th label="Company" sortKeyName="company_name" />
              <Th label="Ticker" sortKeyName="ticker" />
              <Th label="Type" sortKeyName="doc_type_label" />
              <Th label="Classification" sortKeyName="materiality" />
              <Th label="Confidence" sortKeyName="confidence" alignRight />
              <Th label="Why" sortKeyName="rationale" />
              <Th label="Flags" sortKeyName="flags_count" />
              <Th label="Published" sortKeyName="published_at" />
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((f) => {
              const isExpanded = expanded.has(f.announcement_id);
              const capped = capWords(f.rationale, RATIONALE_WORD_CAP);
              const code = extractFormCode(f.doc_type_label);
              return (
                <tr key={f.announcement_id}>
                  <td>{f.company_name}</td>
                  <td className="mono small">{f.ticker}</td>
                  <td className="small">
                    {f.doc_type_label}
                    {code && (
                      <span className="type-hint" title={typeTooltip(f.doc_type_label)} aria-label={`What is ${code}?`}>
                        ?
                      </span>
                    )}
                  </td>
                  <td>
                    <span className={materialityBadgeClass(f.materiality)}>{f.materiality_label}</span>
                  </td>
                  <td className="align-right tabular">{fmtPct(f.confidence, 0)}</td>
                  <td
                    className={`small rationale-cell${isExpanded ? " expanded" : ""}`}
                    onClick={() => toggleExpanded(f.announcement_id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        toggleExpanded(f.announcement_id);
                      }
                    }}
                  >
                    <span className={isExpanded ? "rationale-full" : "rationale-clamp"}>
                      {isExpanded ? capped.text : f.rationale}
                    </span>
                    <span className="rationale-toggle">
                      {isExpanded ? "▲ less" : "▼ more"}
                    </span>
                  </td>
                  <td>
                    {f.flags.length === 0 ? (
                      <span className="muted">&mdash;</span>
                    ) : (
                      <span className="flag-chip-row">
                        {f.flags.map((flag) => (
                          <span key={flag.code} className="badge red" title={flag.why}>
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
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
