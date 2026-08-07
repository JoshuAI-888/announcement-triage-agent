// filingsExport.ts — client-side export helpers for the filings table
// (FilingsTable.tsx). Two output paths, both driven off the same FilingRow[]
// + ExportMeta the caller already has:
//   - filingsToCsv / downloadFilingsCsv: RFC-4180 CSV, Excel-friendly (BOM +
//     CRLF), for spreadsheet workflows.
//   - openFilingsPrintView: a self-contained HTML document in a new window,
//     styled for print-to-PDF, with clickable source links preserved.
// Tier badging matches lib/tier.ts (the authoritative material/needs_look/
// immaterial split — see docs memory "brief-tiering-rule") so exports agree
// with what the table and summary tiles show. No external deps, no CDN
// assets (CSP-safe) — vanilla DOM/string building only. SSR-safe: window/
// document are touched only inside the two side-effecting functions below.

import type { FilingRow } from "@/lib/types";
import { tierOf, TIER_LABEL } from "@/lib/tier";
import { fmtDateTime, fmtPct } from "@/lib/format";

export interface ExportMeta {
  title: string; // e.g. "SEC filings — this run"
  kindLabel: string; // e.g. "Daily digest"
  generatedAt: string; // ISO string of the run's generated_at
}

const CSV_HEADER = ["Company", "Ticker", "Type", "Tier", "Materiality", "Confidence", "Why", "Flags", "Published", "Source URL"];

/** Quote a single CSV field per RFC-4180: wrap in quotes and double any
 *  internal quotes whenever the value contains a quote, comma, or newline. */
function csvField(value: string): string {
  if (/["\n\r,]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function csvRow(values: string[]): string {
  return values.map(csvField).join(",");
}

/** Pure — builds an RFC-4180 CSV string (UTF-8 BOM + CRLF line endings) from
 *  filing rows. No I/O, so it's easy to unit-test independently of the DOM. */
export function filingsToCsv(rows: FilingRow[]): string {
  const lines = [csvRow(CSV_HEADER)];
  for (const f of rows) {
    lines.push(
      csvRow([
        f.company_name,
        f.ticker,
        f.doc_type_label,
        TIER_LABEL[tierOf(f)],
        f.materiality_label,
        fmtPct(f.confidence, 0),
        f.rationale,
        f.flags.map((flag) => flag.label).join("; "),
        fmtDateTime(f.published_at),
        f.source_url,
      ])
    );
  }
  const BOM = "﻿";
  return BOM + lines.join("\r\n") + "\r\n";
}

/** Filename timestamp derived from meta.generatedAt (fallback: now), e.g.
 *  "filings-2026-08-08-1504". */
function exportTimestamp(generatedAt: string): string {
  const d = new Date(generatedAt);
  const t = Number.isNaN(d.getTime()) ? new Date() : d;
  const pad = (n: number) => String(n).padStart(2, "0");
  const y = t.getFullYear();
  const mo = pad(t.getMonth() + 1);
  const da = pad(t.getDate());
  const h = pad(t.getHours());
  const mi = pad(t.getMinutes());
  return `${y}-${mo}-${da}-${h}${mi}`;
}

/** Builds the CSV via filingsToCsv and triggers a browser download. SSR-safe
 *  no-op when `document` isn't available. */
export function downloadFilingsCsv(rows: FilingRow[], meta: ExportMeta): void {
  if (typeof document === "undefined") return;
  const csv = filingsToCsv(rows);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `filings-${exportTimestamp(meta.generatedAt)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Escapes text for safe interpolation into HTML (element content or a
 *  quoted attribute value). Row-derived strings (company name, rationale,
 *  flag labels, URLs, etc.) are untrusted-ish free text from the model/
 *  filer, so every one of them goes through this before hitting the page. */
function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function tierPillStyle(tier: ReturnType<typeof tierOf>): string {
  if (tier === "material") return "background:#e6f8ea;color:#25783a;";
  if (tier === "needs_look") return "background:#fff1e7;color:#a94b08;";
  return "background:#eef2f3;color:#303c42;";
}

const PILL_BASE = "display:inline-block;padding:2px 8px;border-radius:999px;font-size:10.5px;font-weight:600;white-space:nowrap;";
const FLAG_PILL_STYLE = `${PILL_BASE}background:#fae9e7;color:#983830;margin:0 4px 2px 0;`;

function buildRowHtml(f: FilingRow): string {
  const tier = tierOf(f);
  const flagsHtml =
    f.flags.length === 0
      ? "&mdash;"
      : f.flags.map((flag) => `<span class="pill" style="${FLAG_PILL_STYLE}" title="${escapeHtml(flag.why)}">${escapeHtml(flag.label)}</span>`).join(" ");
  const href = escapeHtml(f.source_url);
  return `<tr>
    <td>${escapeHtml(f.company_name)}</td>
    <td class="mono">${escapeHtml(f.ticker)}</td>
    <td>${escapeHtml(f.doc_type_label)}</td>
    <td><span class="pill" style="${PILL_BASE}${tierPillStyle(tier)}">${escapeHtml(TIER_LABEL[tier])}</span></td>
    <td class="align-right">${escapeHtml(fmtPct(f.confidence, 0))}</td>
    <td>${escapeHtml(f.rationale)}</td>
    <td>${flagsHtml}</td>
    <td class="mono">${escapeHtml(fmtDateTime(f.published_at))}</td>
    <td><a href="${href}" target="_blank" rel="noopener">Filing &#8599;</a></td>
  </tr>`;
}

function buildPrintDocument(rows: FilingRow[], meta: ExportMeta): string {
  const rowsHtml = rows.map(buildRowHtml).join("\n");
  const title = escapeHtml(meta.title);
  const subtitle = `${escapeHtml(meta.kindLabel)} &middot; ${escapeHtml(fmtDateTime(meta.generatedAt))} &middot; ${rows.length} filing${
    rows.length === 1 ? "" : "s"
  }`;
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>${title}</title>
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1a1f23;
    background: #fff;
    margin: 24px;
    font-size: 13px;
  }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .subtitle { color: #5a6570; font-size: 12px; margin: 0 0 16px; }
  table { width: 100%; border-collapse: collapse; font-size: 10.5px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #dde2e5; vertical-align: top; }
  th { background: #f4f6f7; font-weight: 600; }
  td.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; white-space: nowrap; }
  td.align-right { text-align: right; }
  a { color: #1a56db; text-decoration: underline; }
  .pill { break-inside: avoid; }
  .no-print { margin-bottom: 16px; }
  .no-print button {
    font: inherit;
    padding: 8px 16px;
    border: 1px solid #1a56db;
    background: #1a56db;
    color: #fff;
    border-radius: 6px;
    cursor: pointer;
  }
  @media print {
    @page { margin: 14mm; }
    body { margin: 0; font-size: 11px; color: #000; }
    .no-print { display: none; }
    table { font-size: 10.5px; }
    tr { break-inside: avoid; }
    thead { display: table-header-group; }
    a { color: #000; text-decoration: underline; }
  }
</style>
</head>
<body>
  <div class="no-print">
    <button type="button" onclick="window.print()">Print / Save as PDF</button>
  </div>
  <h1>${title}</h1>
  <p class="subtitle">${subtitle}</p>
  <table>
    <thead>
      <tr>
        <th>Company</th>
        <th>Ticker</th>
        <th>Type</th>
        <th>Tier</th>
        <th class="align-right">Conf.</th>
        <th>Why</th>
        <th>Flags</th>
        <th>Published</th>
        <th>Source</th>
      </tr>
    </thead>
    <tbody>
${rowsHtml}
    </tbody>
  </table>
</body>
</html>`;
}

/** Opens a new window with a self-contained, print-optimized HTML view of
 *  the given rows and triggers the browser print dialog. No-op (with a
 *  console warning) if the popup is blocked. */
export function openFilingsPrintView(rows: FilingRow[], meta: ExportMeta): void {
  if (typeof window === "undefined") return;
  const win = window.open("", "_blank");
  if (!win) {
    console.warn("openFilingsPrintView: popup blocked, could not open print view");
    return;
  }
  win.document.write(buildPrintDocument(rows, meta));
  win.document.close();

  let printed = false;
  const doPrint = () => {
    if (printed) return;
    printed = true;
    try {
      win.print();
    } catch {
      // Window may already be closed by the user — nothing to do.
    }
  };
  win.onload = doPrint;
  setTimeout(doPrint, 400);
}
