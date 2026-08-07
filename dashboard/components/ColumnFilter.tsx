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
  const wrapRef = useRef<HTMLDivElement>(null);

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
        type="button"
        className={`col-filter-btn${selected.size > 0 ? " is-active" : ""}`}
        aria-label={`Filter by ${label}`}
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
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
          style={{ position: "absolute", zIndex: 20, top: "100%", [align]: 0 } as React.CSSProperties}
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
