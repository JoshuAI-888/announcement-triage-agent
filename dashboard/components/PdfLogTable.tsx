"use client";

// PdfLogTable — the interactive OCR / PDF-decision audit table. Each row is the
// routing decision for one filing's primary document; clicking a row expands a
// detail panel with the full audit trail: page completeness, tier/fallback
// trail, token usage, quality heuristics, the source PDF link, and (for rows
// that produced real text) the persisted transcript, lazy-loaded from
// /api/ocr-text on first expand so the initial payload stays small.

import { useCallback, useState } from "react";
import type { OcrQuality, PdfLogDecision, PdfLogRow } from "@/lib/types";
import { fmtBytes, fmtDateTime, fmtNzd } from "@/lib/format";

const DECISION_LABEL: Record<PdfLogDecision, string> = {
  skipped_form: "skipped (form)",
  pypdf_text: "pypdf text",
  claude_ocr: "Claude OCR",
  placeholder_too_big: "placeholder (too big)",
  placeholder_ocr_disabled: "placeholder (OCR off)",
  placeholder_no_text: "placeholder (no text)",
  error: "error",
};

// Human labels for the tier-trail slugs written by the Python pipeline.
const TIER_LABEL: Record<string, string> = {
  form_check: "Form check",
  download: "Download",
  size_check: "Size check",
  pypdf: "pypdf text layer",
  ocr_disabled: "OCR disabled",
  claude_ocr: "Claude OCR",
};

function decisionBadgeClass(decision: PdfLogDecision): string {
  switch (decision) {
    case "pypdf_text":
    case "claude_ocr":
      return "badge green";
    case "skipped_form":
      return "badge";
    case "error":
      return "badge red";
    default:
      return "badge orange";
  }
}

function qualityBadgeClass(label: OcrQuality["label"]): string {
  return label === "good" ? "badge green" : label === "fair" ? "badge orange" : "badge red";
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

type TranscriptState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "loaded"; text: string }
  | { status: "error"; message: string };

export function PdfLogTable({ rows: initialRows }: { rows: PdfLogRow[] }) {
  const [rows, setRows] = useState(initialRows);
  const [openId, setOpenId] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<Record<string, TranscriptState>>({});
  const [deleting, setDeleting] = useState<string | null>(null);

  const handleDelete = useCallback(async (ts: string) => {
    if (!window.confirm("Delete this row from the audit log? This removes it from out/pdf_log.jsonl.")) return;
    setDeleting(ts);
    try {
      const res = await fetch("/api/pdf-log", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ts }),
      });
      if (!res.ok) {
        const msg = (await res.json().catch(() => ({}))) as { message?: string };
        window.alert(`Delete failed: ${msg.message ?? res.status}`);
        return;
      }
      setRows((prev) => prev.filter((r) => r.ts !== ts));
    } catch (e) {
      window.alert(`Delete failed: ${(e as Error).message}`);
    } finally {
      setDeleting(null);
    }
  }, []);

  const loadTranscript = useCallback(
    async (textPath: string) => {
      setTranscripts((prev) => {
        if (prev[textPath] && prev[textPath].status !== "error") return prev; // already loading/loaded
        return { ...prev, [textPath]: { status: "loading" } };
      });
      try {
        const res = await fetch(`/api/ocr-text?path=${encodeURIComponent(textPath)}`);
        if (!res.ok) {
          const msg = res.status === 404 ? "Transcript file not found." : `Load failed (HTTP ${res.status}).`;
          setTranscripts((prev) => ({ ...prev, [textPath]: { status: "error", message: msg } }));
          return;
        }
        const data = (await res.json()) as { text?: string };
        setTranscripts((prev) => ({ ...prev, [textPath]: { status: "loaded", text: data.text ?? "" } }));
      } catch (err) {
        setTranscripts((prev) => ({
          ...prev,
          [textPath]: { status: "error", message: (err as Error).message },
        }));
      }
    },
    []
  );

  const toggle = useCallback(
    (rowKey: string, row: PdfLogRow) => {
      const next = openId === rowKey ? null : rowKey;
      setOpenId(next);
      if (next && row.text_path) void loadTranscript(row.text_path);
    },
    [openId, loadTranscript]
  );

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th className="ocr-caret-col" aria-label="Expand" />
            <th>Date / time (UTC)</th>
            <th>Company</th>
            <th>Form</th>
            <th>Document</th>
            <th>Decision</th>
            <th>Quality</th>
            <th className="align-right">Pages</th>
            <th className="align-right">Chars</th>
            <th className="align-right">Cost</th>
            <th className="ocr-actions-col" aria-label="Delete" />
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const rowKey = `${r.ts}-${i}`;
            const isOpen = openId === rowKey;
            const q = r.quality ?? null;
            const pagesCell =
              r.page_count == null ? "—" : `${r.pages_with_text ?? 0}/${r.page_count}`;
            return (
              <FragmentRow
                key={rowKey}
                r={r}
                rowKey={rowKey}
                isOpen={isOpen}
                quality={q}
                pagesCell={pagesCell}
                transcript={r.text_path ? transcripts[r.text_path] ?? { status: "idle" } : null}
                onToggle={() => toggle(rowKey, r)}
                onDelete={() => handleDelete(r.ts)}
                isDeleting={deleting === r.ts}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function FragmentRow({
  r,
  rowKey,
  isOpen,
  quality,
  pagesCell,
  transcript,
  onToggle,
  onDelete,
  isDeleting,
}: {
  r: PdfLogRow;
  rowKey: string;
  isOpen: boolean;
  quality: OcrQuality | null;
  pagesCell: string;
  transcript: TranscriptState | null;
  onToggle: () => void;
  onDelete: () => void;
  isDeleting: boolean;
}) {
  const complete =
    r.page_count != null && r.page_count > 0
      ? (r.pages_with_text ?? 0) >= r.page_count
      : null;

  return (
    <>
      <tr className="ocr-row" onClick={onToggle} aria-expanded={isOpen}>
        <td className="ocr-caret-col">
          <span className={`ocr-caret${isOpen ? " open" : ""}`} aria-hidden>
            &#9656;
          </span>
        </td>
        <td className="mono small">{fmtDateTime(r.ts)}</td>
        <td>
          <strong className="ocr-ticker">{r.ticker}</strong>
          {r.company_name ? <span className="ocr-company">{r.company_name}</span> : null}
        </td>
        <td className="mono small">{r.form}</td>
        <td className="mono small ocr-doc" title={r.primary_document}>
          {r.source_url ? (
            <a
              href={r.source_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
            >
              {r.primary_document} &#8599;
            </a>
          ) : (
            r.primary_document
          )}
        </td>
        <td>
          <span className={decisionBadgeClass(r.decision)} title={r.detail}>
            {DECISION_LABEL[r.decision] ?? r.decision}
          </span>
        </td>
        <td>
          {quality ? (
            <span className={qualityBadgeClass(quality.label)} title={`Heuristic score ${quality.score}/100`}>
              {quality.label} {quality.score}
            </span>
          ) : (
            <span className="ocr-muted">—</span>
          )}
        </td>
        <td className="align-right tabular">
          {pagesCell !== "—" ? (
            <span className={complete === false ? "ocr-warn" : undefined}>{pagesCell}</span>
          ) : (
            "—"
          )}
        </td>
        <td className="align-right tabular">{r.chars_out.toLocaleString()}</td>
        <td className="align-right tabular">{fmtNzd(r.cost_nzd)}</td>
        <td className="ocr-actions-col">
          <button
            type="button"
            className="ocr-del-btn"
            title="Delete this row"
            aria-label="Delete row"
            disabled={isDeleting}
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
          >
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden focusable="false">
              <path fill="currentColor" d="M6 2h4a1 1 0 0 1 1 1v1h3v2h-1v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6H3V4h3V3a1 1 0 0 1 1-1zm0 4v8h4V6H6zm1-2h2V3H7v1z"/>
            </svg>
          </button>
        </td>
      </tr>
      {isOpen && (
        <tr className="ocr-detail-row">
          <td className="ocr-detail-cell" colSpan={11}>
            <DetailPanel r={r} quality={quality} complete={complete} transcript={transcript} />
          </td>
        </tr>
      )}
    </>
  );
}

function DetailPanel({
  r,
  quality,
  complete,
  transcript,
}: {
  r: PdfLogRow;
  quality: OcrQuality | null;
  complete: boolean | null;
  transcript: TranscriptState | null;
}) {
  const trail = r.tier_trail ?? [];
  const tokens =
    r.input_tokens != null || r.output_tokens != null
      ? `${(r.input_tokens ?? 0).toLocaleString()} in · ${(r.output_tokens ?? 0).toLocaleString()} out`
      : null;

  return (
    <div className="ocr-detail">
      <p className="ocr-detail-note">{r.detail}</p>

      {trail.length > 0 && (
        <div className="ocr-trail">
          {trail.map((step, i) => (
            <span key={`${step}-${i}`} className="ocr-trail-step">
              {TIER_LABEL[step] ?? step}
            </span>
          ))}
        </div>
      )}

      <dl className="ocr-kv">
        <div>
          <dt>Completeness</dt>
          <dd>
            {r.page_count == null ? (
              "Not applicable (no page scan)"
            ) : complete ? (
              <span className="ocr-ok">All {r.page_count} page(s) yielded text</span>
            ) : (
              <span className="ocr-warn">
                {r.pages_with_text ?? 0} of {r.page_count} page(s) yielded text —{" "}
                {r.page_count - (r.pages_with_text ?? 0)} blank/unreadable
              </span>
            )}
          </dd>
        </div>
        {tokens && (
          <div>
            <dt>Tokens</dt>
            <dd className="tabular">{tokens}</dd>
          </div>
        )}
        {r.model_id && (
          <div>
            <dt>Model</dt>
            <dd className="mono small">{r.model_id}</dd>
          </div>
        )}
        <div>
          <dt>Cost</dt>
          <dd className="tabular">{fmtNzd(r.cost_nzd)}</dd>
        </div>
        <div>
          <dt>Size</dt>
          <dd className="tabular">{fmtBytes(r.bytes)}</dd>
        </div>
        {quality && (
          <>
            <div>
              <dt>Printable / alpha</dt>
              <dd className="tabular">
                {pct(quality.printable_ratio)} / {pct(quality.alpha_ratio)}
              </dd>
            </div>
            <div>
              <dt>Unrecognised glyphs</dt>
              <dd className="tabular">
                <span className={quality.replacement_chars > 0 ? "ocr-warn" : undefined}>
                  {quality.replacement_chars}
                </span>
              </dd>
            </div>
            <div>
              <dt>Chars / page</dt>
              <dd className="tabular">{quality.chars_per_page ?? "—"}</dd>
            </div>
          </>
        )}
        {r.accession_number && (
          <div>
            <dt>Accession</dt>
            <dd className="mono small">{r.accession_number}</dd>
          </div>
        )}
        {r.cik && (
          <div>
            <dt>CIK</dt>
            <dd className="mono small">{r.cik}</dd>
          </div>
        )}
      </dl>

      {r.source_url && (
        <p className="ocr-pdf-link">
          <a href={r.source_url} target="_blank" rel="noopener noreferrer">
            Open source PDF in a new tab &#8599;
          </a>
        </p>
      )}

      <TranscriptBlock textPath={r.text_path ?? null} transcript={transcript} />
    </div>
  );
}

function TranscriptBlock({
  textPath,
  transcript,
}: {
  textPath: string | null;
  transcript: TranscriptState | null;
}) {
  if (!textPath || !transcript) {
    return (
      <p className="ocr-muted ocr-transcript-empty">
        No transcript — this decision produced a placeholder, not extracted text.
      </p>
    );
  }
  return (
    <div className="ocr-transcript-wrap">
      <div className="ocr-transcript-head">Extracted text</div>
      {transcript.status === "loading" && <p className="ocr-muted">Loading transcript…</p>}
      {transcript.status === "error" && (
        <p className="ocr-warn">Could not load transcript: {transcript.message}</p>
      )}
      {transcript.status === "loaded" &&
        (transcript.text.trim() ? (
          <pre className="ocr-transcript">{transcript.text}</pre>
        ) : (
          <p className="ocr-muted">Transcript is empty.</p>
        ))}
    </div>
  );
}
