// filingsFilters.ts — pure, SSR-safe column-filter logic for FilingsTable's
// header dropdowns (ColumnFilter.tsx). No React, no DOM: this module only
// derives filter domains and applies set-membership filters over FilingRow[].
// Tier values are sourced from lib/tier.ts so the filter domain/order always
// agrees with the badge/sort behaviour ("brief-tiering-rule").

import type { FilingRow } from "@/lib/types";
import { tierOf, TIER_LABEL, tierRank, type Tier } from "@/lib/tier";

// The four filterable columns.
export type FilterableColumn = "tier" | "doc_type_label" | "ticker" | "flags";

// Absent key OR empty set for a column === no constraint (show all).
export type ColumnFilters = Partial<Record<FilterableColumn, Set<string>>>;

// Sentinel value a row with no flags contributes to the "flags" column domain.
export const NO_FLAGS = "No flags";

/** The display value(s) a row contributes to a column's filter domain. */
export function valuesForRow(f: FilingRow, col: FilterableColumn): string[] {
  switch (col) {
    case "tier":
      return [TIER_LABEL[tierOf(f)]];
    case "ticker":
      return [f.ticker];
    case "doc_type_label":
      return [f.doc_type_label];
    case "flags":
      return f.flags.length === 0 ? [NO_FLAGS] : f.flags.map((flag) => flag.label);
    default:
      return [];
  }
}

/** Sorted distinct domain for a column across all rows. */
export function distinctValues(rows: FilingRow[], col: FilterableColumn): string[] {
  const set = new Set<string>();
  for (const f of rows) {
    for (const v of valuesForRow(f, col)) set.add(v);
  }

  if (col === "tier") {
    // tierRank order (Material, Needs a look, Immaterial), not alpha.
    const allTiers: Tier[] = ["material", "needs_look", "immaterial"];
    return allTiers
      .slice()
      .sort((a, b) => tierRank(a) - tierRank(b))
      .map((t) => TIER_LABEL[t])
      .filter((label) => set.has(label));
  }

  const values = [...set];
  if (col === "flags") {
    // Alpha-sort real flag labels, then push the "No flags" sentinel last.
    const real = values.filter((v) => v !== NO_FLAGS).sort((a, b) => a.localeCompare(b));
    return set.has(NO_FLAGS) ? [...real, NO_FLAGS] : real;
  }

  return values.sort((a, b) => a.localeCompare(b));
}

/** True if the row satisfies EVERY active column filter (AND across columns). */
export function rowMatchesFilters(f: FilingRow, filters: ColumnFilters): boolean {
  for (const col of Object.keys(filters) as FilterableColumn[]) {
    const allowed = filters[col];
    if (!allowed || allowed.size === 0) continue; // no constraint
    const rowValues = valuesForRow(f, col);
    if (!rowValues.some((v) => allowed.has(v))) return false;
  }
  return true;
}

/** Convenience: filter an array. */
export function applyColumnFilters(rows: FilingRow[], filters: ColumnFilters): FilingRow[] {
  return rows.filter((f) => rowMatchesFilters(f, filters));
}

/** Count of columns that currently constrain (non-empty sets). For toolbar "Clear (n)". */
export function activeFilterColumnCount(filters: ColumnFilters): number {
  let count = 0;
  for (const col of Object.keys(filters) as FilterableColumn[]) {
    const allowed = filters[col];
    if (allowed && allowed.size > 0) count++;
  }
  return count;
}
