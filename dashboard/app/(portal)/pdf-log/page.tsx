import { getPdfLog } from "@/lib/dataSource";
import { fmtNzd } from "@/lib/format";
import { PdfLogTable } from "@/components/PdfLogTable";

export const dynamic = "force-dynamic";

export default async function PdfLogPage() {
  const rows = await getPdfLog(200);

  // Audit summary — cheap roll-ups over the visible window.
  const ocrRows = rows.filter((r) => r.decision === "claude_ocr");
  const extractedRows = rows.filter((r) => r.decision === "pypdf_text" || r.decision === "claude_ocr");
  const errorRows = rows.filter((r) => r.decision === "error");
  const placeholderRows = rows.filter((r) => r.decision.startsWith("placeholder"));
  const totalOcrCost = ocrRows.reduce((sum, r) => sum + (r.cost_nzd ?? 0), 0);
  const scored = extractedRows.map((r) => r.quality?.score).filter((s): s is number => typeof s === "number");
  const avgQuality = scored.length ? Math.round(scored.reduce((a, b) => a + b, 0) / scored.length) : null;

  const summary: { label: string; value: string }[] = [
    { label: "Events", value: String(rows.length) },
    { label: "Text extracted", value: String(extractedRows.length) },
    { label: "Claude OCR", value: String(ocrRows.length) },
    { label: "Errors", value: String(errorRows.length) },
    { label: "Placeholders", value: String(placeholderRows.length) },
    { label: "Avg quality", value: avgQuality == null ? "—" : `${avgQuality}/100` },
    { label: "OCR cost", value: totalOcrCost > 0 ? fmtNzd(totalOcrCost) : "—" },
  ];

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Operations</p>
          <h1>PDF / OCR audit log</h1>
          <p>
            Every decision made while fetching a filing&rsquo;s primary document &mdash; text extracted directly,
            handed to Claude for OCR, skipped, or replaced with a placeholder &mdash; from out/pdf_log.jsonl, newest
            first (last {rows.length} events). Click a row for the full audit trail: page completeness, tier/fallback
            path, token usage, quality heuristics, the source PDF, and the extracted transcript.
          </p>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="card card-pad empty">
          <p>No PDF handling events recorded yet.</p>
        </div>
      ) : (
        <>
          <div className="ocr-summary">
            {summary.map((s) => (
              <div key={s.label} className="ocr-summary-item">
                <span className="ocr-summary-value">{s.value}</span>
                <span className="ocr-summary-label">{s.label}</span>
              </div>
            ))}
          </div>
          <PdfLogTable rows={rows} />
        </>
      )}
    </section>
  );
}
