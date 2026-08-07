"use client";

// FilingsTable — client-side filterable/sortable table for out/filings/<date>.json's
// `filings[]` (CONTRACTS.md). Flags arrive pre-rendered as {code, label, why}
// from the Python side, so this only ever displays label/why, never the raw
// code.
//
// Filtering (three composable layers, applied in this order):
//   1. Per-column multi-select filters (Classification/tier, Type, Ticker, Flags)
//      via the header ColumnFilter dropdowns — set membership, AND across columns.
//   2. Free-text search across the visible text columns.
//   3. Multi-key sort (see below).
//
// Sort UX: plain click on a header sets/toggles that column as the sole
// (primary) sort key. Shift-click adds it as a secondary/tertiary key. The
// active sort order is also shown as removable chips above the table, so the
// multi-level sort is discoverable without knowing the shift-click trick.
//
// Tier (Classification) badging/sorting/filtering all route through lib/tier's
// tierOf so the table's material count matches the summary tiles / email.
//
// Export: the CURRENT view (filtered + sorted, in display order) can be
// exported to CSV or to a print-optimized PDF (with clickable source links)
// via lib/filingsExport.

import { useMemo, useState } from "react";
import { fmtDateTime, fmtPct } from "@/lib/format";
import type { FilingRow } from "@/lib/types";
import { docTypeBlurb, extractFormCode } from "@/lib/docTypes";
import { cmpNum, cmpStr, useMultiSort } from "@/lib/sort";
import { TIER_LABEL, tierBadgeClass, tierOf, tierRank } from "@/lib/tier";
import { ColumnFilter } from "@/components/ColumnFilter";
import {
  activeFilterColumnCount,
  applyColumnFilters,
  distinctValues,
  type ColumnFilters,
  type FilterableColumn,
} from "@/lib/filingsFilters";
import { downloadFilingsCsv, openFilingsPrintView, type ExportMeta } from "@/lib/filingsExport";

type SortKey =
  | "company_name"
  | "ticker"
  | "doc_type_label"
  | "materiality"
  | "confidence"
  | "rationale"
  | "flags_count"
  | "published_at";

const SORT_LABEL: Record<SortKey, string> = {
  company_name: "Company",
  ticker: "Ticker",
  doc_type_label: "Type",
  materiality: "Classification",
  confidence: "Confidence",
  rationale: "Why",
  flags_count: "Flags",
  published_at: "Published",
};

const RATIONALE_WORD_CAP = 100;
const EMPTY_SELECTION: Set<string> = new Set();

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
  const haystack = [f.company_name, f.ticker, f.doc_type_label, TIER_LABEL[tierOf(f)], f.materiality_label, f.rationale].join(" \n ").toLowerCase();
  return haystack.includes(needle);
}

export function FilingsTable({
  filings,
  generatedAt,
  kindLabel,
}: {
  filings: FilingRow[];
  generatedAt?: string;
  kindLabel?: string;
}) {
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<ColumnFilters>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // Filter domains are drawn from the FULL run (not the filtered view) so a
  // narrowed selection can always be widened again.
  const filterOptions = useMemo(
    () => ({
      tier: distinctValues(filings, "tier"),
      doc_type_label: distinctValues(filings, "doc_type_label"),
      ticker: distinctValues(filings, "ticker"),
      flags: distinctValues(filings, "flags"),
    }),
    [filings]
  );

  const filtered = useMemo(() => {
    let rows = applyColumnFilters(filings, filters);
    const needle = search.trim().toLowerCase();
    if (needle) rows = rows.filter((f) => matchesSearch(f, needle));
    return rows;
  }, [filings, filters, search]);

  const comparators = useMemo<Record<SortKey, (a: FilingRow, b: FilingRow) => number>>(
    () => ({
      company_name: (a, b) => cmpStr(a.company_name, b.company_name),
      ticker: (a, b) => cmpStr(a.ticker, b.ticker),
      doc_type_label: (a, b) => cmpStr(a.doc_type_label, b.doc_type_label),
      materiality: (a, b) => tierRank(tierOf(a)) - tierRank(tierOf(b)),
      confidence: (a, b) => cmpNum(a.confidence, b.confidence),
      rationale: (a, b) => cmpStr(a.rationale, b.rationale),
      flags_count: (a, b) => cmpNum(a.flags.length, b.flags.length),
      published_at: (a, b) => cmpStr(a.published_at, b.published_at),
    }),
    []
  );

  const { sorted, sorts, onHeaderClick, rankOf, dirOf, removeSort, resetSorts } = useMultiSort<FilingRow, SortKey>(filtered, comparators, [
    { key: "materiality", dir: "asc" },
    { key: "published_at", dir: "desc" },
  ]);

  const activeFilters = activeFilterColumnCount(filters);

  const exportMeta = useMemo<ExportMeta>(
    () => ({
      title: "SEC filings — this run",
      kindLabel: kindLabel ?? "Run",
      generatedAt: generatedAt ?? new Date().toISOString(),
    }),
    [kindLabel, generatedAt]
  );

  function setColumnFilter(col: FilterableColumn, next: Set<string>) {
    setFilters((prev) => ({ ...prev, [col]: next }));
  }

  function toggleExpanded(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function Th({
    label,
    sortKeyName,
    filterCol,
    filterAlign,
    alignRight,
  }: {
    label: string;
    sortKeyName: SortKey;
    filterCol?: FilterableColumn;
    filterAlign?: "left" | "right";
    alignRight?: boolean;
  }) {
    const rank = rankOf(sortKeyName);
    const dir = dirOf(sortKeyName);
    const active = rank !== null;
    return (
      <th className={`sortable${alignRight ? " align-right" : ""}`} title="Click to sort. Shift-click to add as a secondary sort key.">
        <span className="th-inner">
          <span className="th-label" onClick={(e) => onHeaderClick(sortKeyName, e.shiftKey)}>
            {label}
            {active && (
              <span className="sort-arrow">
                {dir === "asc" ? "▲" : "▼"}
                {sorts.length > 1 && <sup className="sort-rank">{rank}</sup>}
              </span>
            )}
          </span>
          {filterCol && (
            <ColumnFilter
              label={label}
              options={filterOptions[filterCol]}
              selected={filters[filterCol] ?? EMPTY_SELECTION}
              onChange={(next) => setColumnFilter(filterCol, next)}
              align={filterAlign}
            />
          )}
        </span>
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
        <div className="toolbar-left">
          <input
            className="input search-input"
            type="search"
            placeholder="Search company, ticker, type, classification, rationale…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search filings"
          />
          {activeFilters > 0 && (
            <button type="button" className="btn ghost small-btn" onClick={() => setFilters({})}>
              Clear filters ({activeFilters})
            </button>
          )}
        </div>
        <div className="toolbar-actions">
          <span className="small muted">
            {sorted.length} of {filings.length}
          </span>
          <button
            type="button"
            className="btn secondary small-btn"
            onClick={() => downloadFilingsCsv(sorted, exportMeta)}
            title="Download the current view as a CSV (includes source URLs)"
          >
            Export CSV
          </button>
          <button
            type="button"
            className="btn secondary small-btn"
            onClick={() => openFilingsPrintView(sorted, exportMeta)}
            title="Open a print-ready view — use your browser's Save as PDF (links stay clickable)"
          >
            Export PDF
          </button>
        </div>
      </div>

      <div className="sort-levels" aria-label="Active sort order">
        <span className="sort-levels-label">Sorted by</span>
        {sorts.length === 0 && <span className="small muted">nothing — click a column header</span>}
        {sorts.map((s, i) => (
          <span key={s.key} className="sort-level-chip">
            {sorts.length > 1 && <b className="sort-level-rank">{i + 1}</b>}
            {SORT_LABEL[s.key]}
            <button
              type="button"
              className="sort-level-dir"
              title="Toggle ascending / descending"
              onClick={() => onHeaderClick(s.key, true)}
            >
              {s.dir === "asc" ? "▲" : "▼"}
            </button>
            <button type="button" className="sort-level-rm" title="Remove this sort level" onClick={() => removeSort(s.key)}>
              ×
            </button>
          </span>
        ))}
        <button type="button" className="btn ghost small-btn" onClick={resetSorts} title="Reset to the default sort order">
          Reset
        </button>
        <span className="sort-hint small muted">Shift-click a header to add a level</span>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <Th label="Company" sortKeyName="company_name" />
              <Th label="Ticker" sortKeyName="ticker" filterCol="ticker" />
              <Th label="Type" sortKeyName="doc_type_label" filterCol="doc_type_label" />
              <Th label="Classification" sortKeyName="materiality" filterCol="tier" />
              <Th label="Confidence" sortKeyName="confidence" alignRight />
              <Th label="Why" sortKeyName="rationale" />
              <Th label="Flags" sortKeyName="flags_count" filterCol="flags" filterAlign="right" />
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
                    <span
                      className={tierBadgeClass(tierOf(f))}
                      title={
                        tierOf(f) === "material" && f.flags.length > 0
                          ? `Material — but a data-quality flag needs verifying (see Flags)`
                          : `Model classification: ${f.materiality_label}`
                      }
                    >
                      {TIER_LABEL[tierOf(f)]}
                    </span>
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
