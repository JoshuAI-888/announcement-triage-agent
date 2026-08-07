"use client";

// sort.ts — shared multi-key sort behaviour for portal tables (FilingsTable,
// RunLogTable, WorkflowRuns). Plain click sets/toggles a single primary sort
// key. Shift-click adds the column as a secondary/tertiary key, applied in
// the order added (stable — first non-zero comparator wins). Client-side only.

import { useMemo, useState } from "react";

export type SortDir = "asc" | "desc";

export interface SortSpec<K extends string> {
  key: K;
  dir: SortDir;
}

export interface UseMultiSort<T, K extends string> {
  sorted: T[];
  sorts: SortSpec<K>[];
  /** Call from a header's onClick(e) — pass e.shiftKey. */
  onHeaderClick: (key: K, shiftKey: boolean) => void;
  /** 1-based position in the active sort order, or null if this key isn't active. */
  rankOf: (key: K) => number | null;
  /** Current direction for this key, or null if inactive. */
  dirOf: (key: K) => SortDir | null;
}

/**
 * Generic multi-key sort. `comparators` maps each sortable column key to a
 * comparator over two rows (ascending sense; direction is applied by this hook).
 */
export function useMultiSort<T, K extends string>(
  rows: T[],
  comparators: Record<K, (a: T, b: T) => number>,
  initial: SortSpec<K>[] = []
): UseMultiSort<T, K> {
  const [sorts, setSorts] = useState<SortSpec<K>[]>(initial);

  function onHeaderClick(key: K, shiftKey: boolean) {
    setSorts((prev) => {
      const idx = prev.findIndex((s) => s.key === key);
      if (shiftKey) {
        // Add (or toggle direction of) a secondary/tertiary key, keep the rest.
        if (idx === -1) return [...prev, { key, dir: "asc" }];
        const next = [...prev];
        next[idx] = { key, dir: next[idx].dir === "asc" ? "desc" : "asc" };
        return next;
      }
      // Plain click: this becomes the sole primary key, toggling direction if
      // it was already the (sole) active key.
      if (idx === 0 && prev.length === 1) {
        return [{ key, dir: prev[0].dir === "asc" ? "desc" : "asc" }];
      }
      return [{ key, dir: "asc" }];
    });
  }

  const sorted = useMemo(() => {
    if (sorts.length === 0) return rows;
    const copy = [...rows];
    copy.sort((a, b) => {
      for (const s of sorts) {
        const cmp = comparators[s.key](a, b);
        if (cmp !== 0) return s.dir === "asc" ? cmp : -cmp;
      }
      return 0;
      // eslint-disable-next-line
    });
    return copy;
    // comparators is expected to be stable-ish (defined once per component);
    // re-sort whenever rows or the active sort spec changes.
  }, [rows, sorts]); // eslint-disable-line react-hooks/exhaustive-deps

  function rankOf(key: K): number | null {
    const idx = sorts.findIndex((s) => s.key === key);
    return idx === -1 ? null : idx + 1;
  }
  function dirOf(key: K): SortDir | null {
    return sorts.find((s) => s.key === key)?.dir ?? null;
  }

  return { sorted, sorts, onHeaderClick, rankOf, dirOf };
}

/** Locale-aware string comparator, null/undefined-safe (nulls sort last). */
export function cmpStr(a: string | null | undefined, b: string | null | undefined): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return a.localeCompare(b);
}

/** Numeric comparator, null/undefined-safe (nulls sort last). */
export function cmpNum(a: number | null | undefined, b: number | null | undefined): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return a - b;
}
