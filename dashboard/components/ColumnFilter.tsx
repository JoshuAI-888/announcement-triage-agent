"use client";

// ColumnFilter — a small multi-select filter dropdown that lives inside a
// FilingsTable header cell (see lib/filingsFilters.ts for the pure logic it
// drives). Purely presentational/controlled: the caller owns the selected
// Set and receives a new one via onChange. Because it sits inside a
// sortable <th onClick=…>, every interaction here stops propagation so
// opening/using the filter never also triggers a column sort.

import { useEffect, useRef, useState } from "react";

export interface ColumnFilterProps {
  label: string; // human column name, for the popover heading + aria
  options: string[]; // distinctValues(...) for this column, pre-sorted
  selected: Set<string>; // current selection ("" / empty set = no filter = all)
  onChange: (next: Set<string>) => void;
  align?: "left" | "right"; // popover alignment; default "left"
}

export function ColumnFilter({ label, options, selected, onChange, align = "left" }: ColumnFilterProps) {
  const [open, setOpen] = useState(false);
  // The popover is positioned `fixed` (viewport coords) rather than absolute:
  // it lives inside the table's `overflow:auto` wrapper, which would otherwise
  // clip it, and fixed lets us clamp it to the viewport so it never spills off
  // a narrow (phone) screen.
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  // Anchor the popover under the trigger button, clamped to the viewport.
  function computePosition() {
    const btn = btnRef.current;
    if (!btn || typeof window === "undefined") return;
    const r = btn.getBoundingClientRect();
    const vw = window.innerWidth;
    const width = Math.min(260, vw - 16);
    let left = align === "right" ? r.right - width : r.left;
    left = Math.max(8, Math.min(left, vw - width - 8));
    setPos({ top: Math.round(r.bottom + 4), left: Math.round(left), width });
  }

  // A fixed popover would drift if the page scrolls or resizes under it — just
  // close it in those cases (recomputing on every scroll frame isn't worth it).
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    function onDocMouseDown(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  function toggleOption(opt: string) {
    const next = new Set(selected);
    if (next.has(opt)) next.delete(opt);
    else next.add(opt);
    onChange(next);
  }

  function clear() {
    onChange(new Set());
  }

  function selectAll() {
    onChange(new Set(options));
  }

  return (
    <div
      className="col-filter"
      style={{ position: "relative", display: "inline-block" }}
      ref={wrapRef}
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <button
        ref={btnRef}
        type="button"
        className={`col-filter-btn${selected.size > 0 ? " is-active" : ""}`}
        aria-label={`Filter by ${label}`}
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          if (!open) computePosition();
          setOpen((prev) => !prev);
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        &#9660;
        {selected.size > 0 && <span className="col-filter-count">{selected.size}</span>}
      </button>
      {open && (
        <div
          className="col-filter-pop"
          style={
            pos
              ? { position: "fixed", top: pos.top, left: pos.left, width: pos.width, zIndex: 60 }
              : { position: "fixed", zIndex: 60, visibility: "hidden" }
          }
          role="dialog"
          aria-label={`${label} filter options`}
        >
          <div className="col-filter-pop-head">
            <span>{label}</span>
            <button type="button" className="col-filter-clear" onClick={clear}>
              Clear
            </button>
          </div>
          <div className="col-filter-list">
            {options.map((opt) => (
              <label key={opt} className="col-filter-opt">
                <input type="checkbox" checked={selected.has(opt)} onChange={() => toggleOption(opt)} />
                {opt}
              </label>
            ))}
          </div>
          <div className="col-filter-foot">
            <button type="button" onClick={selectAll}>
              Select all
            </button>
            <button type="button" className="col-filter-clear" onClick={clear}>
              Clear
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
