import { getPdfLog } from "@/lib/dataSource";
import { fmtBytes, fmtDateTime, fmtNzd } from "@/lib/format";
import type { PdfLogDecision } from "@/lib/types";

export const dynamic = "force-dynamic";

const DECISION_LABEL: Record<PdfLogDecision, string> = {
  skipped_form: "skipped (form)",
  pypdf_text: "pypdf text",
  claude_ocr: "Claude OCR",
  placeholder_too_big: "placeholder (too big)",
  placeholder_ocr_disabled: "placeholder (OCR off)",
  placeholder_no_text: "placeholder (no text)",
  error: "error",
};

function badgeClass(decision: PdfLogDecision): string {
  switch (decision) {
    case "pypdf_text":
    case "claude_ocr":
      return "badge green";
    case "skipped_form":
      return "badge";
    default:
      // placeholder_too_big, placeholder_ocr_disabled, placeholder_no_text, error
      return "badge orange";
  }
}

export default async function PdfLogPage() {
  const rows = await getPdfLog(200);

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Operations</p>
          <h1>PDF / OCR decision log</h1>
          <p>
            Every decision made while fetching a filing&rsquo;s primary document &mdash; text extracted directly,
            handed to Claude for OCR, skipped, or replaced with a placeholder &mdash; from out/pdf_log.jsonl, newest
            first (last {rows.length} events).
          </p>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="card card-pad empty">
          <p>No PDF handling events recorded yet.</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date / time (UTC)</th>
                <th>Ticker</th>
                <th>Form</th>
                <th>Document</th>
                <th>Decision</th>
                <th className="align-right">Size</th>
                <th className="align-right">Chars out</th>
                <th className="align-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.ts}-${i}`}>
                  <td className="mono small">{fmtDateTime(r.ts)}</td>
                  <td>{r.ticker}</td>
                  <td className="mono small">{r.form}</td>
                  <td className="mono small" title={r.primary_document}>
                    {r.primary_document}
                  </td>
                  <td>
                    <span className={badgeClass(r.decision)} title={r.detail}>
                      {DECISION_LABEL[r.decision] ?? r.decision}
                    </span>
                  </td>
                  <td className="align-right tabular">{fmtBytes(r.bytes)}</td>
                  <td className="align-right tabular">{r.chars_out.toLocaleString()}</td>
                  <td className="align-right tabular">{fmtNzd(r.cost_nzd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
