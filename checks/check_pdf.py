"""check_pdf.py — tiered PDF pipeline: skip-by-form, pypdf extraction, OCR fallback.

Offline, no network, no real Anthropic call. `EdgarAdapter._get_bytes` is
monkeypatched to return small hand-built PDFs (never fetched over HTTP), and
`EdgarAdapter._claude_ocr` is monkeypatched per-scenario rather than allowed
to reach the real API — this check must never spend money or need a key.

Covers:
  - `_is_non_text_document` suffix detection
  - placeholder body: carries the NON_TEXT_BODY_SENTINEL, the form, and 8-K items
  - skip-by-form (ARS): `skipped_form`, no download at all
  - a non-PDF non-text container (.xlsx): `skipped_form`, no download at all
  - a small text-bearing PDF: `pypdf_text`, real extracted content returned
  - an oversized PDF: `placeholder_too_big`, no extraction attempted
  - `ocr_enabled=False` on a PDF with no text layer: `placeholder_ocr_disabled`
  - `ocr_enabled=True`, OCR succeeds: `claude_ocr`, its text is returned
  - `ocr_enabled=True`, OCR returns nothing: `placeholder_no_text`
  - `ocr_enabled=True`, OCR raises: `error`, still returns a placeholder (never crashes)
  - every decision writes a well-formed `pdf_log.jsonl` row (exact schema)

Run:  python -m checks.check_pdf
"""

from __future__ import annotations

import json
import tempfile
from io import BytesIO
from pathlib import Path

from checks._harness import Check, run

LOG_ROW_KEYS = {
    "ts", "announcement_id", "ticker", "form", "primary_document", "bytes",
    "decision", "chars_out", "model_id", "cost_nzd", "detail",
}
VALID_DECISIONS = {
    "skipped_form", "pypdf_text", "claude_ocr", "placeholder_too_big",
    "placeholder_ocr_disabled", "placeholder_no_text", "error",
}


def _make_text_pdf_bytes() -> bytes:
    """A tiny, syntactically valid PDF with a real extractable text layer.

    Built with pypdf's own writer (not hand-crafted xref offsets) so it is
    guaranteed to round-trip through pypdf's reader in this environment.
    """
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)

    # Comfortably over the 200-non-whitespace-char floor `_fetch_pdf_document`
    # requires before it trusts pypdf's extraction over falling to OCR.
    sentence = (
        "This is a test SEC filing document with real extractable text "
        "content so the pypdf extraction tier succeeds without needing the "
        "OCR fallback, comfortably past the two hundred character floor. "
    )
    content = f"BT /Helv 12 Tf 10 250 Td ({sentence * 2}) Tj ET".encode("latin-1")

    stream_obj = DecodedStreamObject()
    stream_obj.set_data(content)
    stream_ref = writer._add_object(stream_obj)

    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/Type1")
    font[NameObject("/BaseFont")] = NameObject("/Helvetica")
    font_ref = writer._add_object(font)

    fontdict = DictionaryObject()
    fontdict[NameObject("/Helv")] = font_ref
    resources = DictionaryObject()
    resources[NameObject("/Font")] = fontdict

    page[NameObject("/Contents")] = stream_ref
    page[NameObject("/Resources")] = resources

    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _make_empty_pdf_bytes() -> bytes:
    """A tiny, syntactically valid PDF with no text layer at all (a blank page)."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _make_adapter(pdf_log_path, *, ocr_enabled: bool = True):
    from src.adapters.edgar import EdgarAdapter

    return EdgarAdapter(
        watchlist=[],
        user_agent="check_pdf test agent",
        timeout_seconds=5,
        rate_limit_rps=0,  # no throttling — every network call is monkeypatched anyway
        ocr_enabled=ocr_enabled,
        pdf_log_path=Path(pdf_log_path),
        ocr_pricing_usd_per_mtok={"input": 1.00, "output": 5.00},
        fx_usd_nzd=1.7,
    )


def _make_raw(*, form: str, document: str, ticker: str = "TEST", items: str = "") -> dict:
    return {
        "exchange": "EDGAR",
        "ticker": ticker,
        "company_name": f"{ticker} Inc.",
        "form": form,
        "accession_number": f"0000000000-26-{ticker}",
        "announcement_id": f"ann-{ticker}-{document}",
        "headline": f"{form} filing",
        "primary_document": document,
        "primary_doc_description": f"{form} exhibit",
        "items": items,
        "source_url": f"https://sec.gov/Archives/edgar/data/1/000000/{document}",
    }


def _read_log_rows(pdf_log_path: Path) -> list[dict]:
    if not pdf_log_path.is_file():
        return []
    return [json.loads(line) for line in pdf_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _refuse_network(*_args, **_kwargs):
    raise AssertionError("network call attempted — this decision path must not download anything")


def check_is_non_text_document(c: Check) -> None:
    from src.adapters.edgar import EdgarAdapter

    c.require(EdgarAdapter._is_non_text_document("filing.pdf"), "'.pdf' is a non-text document")
    c.require(EdgarAdapter._is_non_text_document("  FILING.PDF  "), "suffix check is case/whitespace insensitive")
    c.require(EdgarAdapter._is_non_text_document("data.xlsx"), "'.xlsx' is a non-text document")
    c.require(EdgarAdapter._is_non_text_document("archive.zip"), "'.zip' is a non-text document")
    c.require(EdgarAdapter._is_non_text_document("chart.png"), "'.png' is a non-text document")
    c.require(not EdgarAdapter._is_non_text_document("filing.htm"), "'.htm' is NOT a non-text document")
    c.require(not EdgarAdapter._is_non_text_document("filing.txt"), "'.txt' is NOT a non-text document")


def check_placeholder_body(c: Check) -> None:
    from src.adapters.edgar import NON_TEXT_BODY_SENTINEL, EdgarAdapter

    raw = _make_raw(form="8-K", document="exhibit99.pdf", items="2.02,9.01")
    body = EdgarAdapter._placeholder_body(raw, "routine-form PDF primary document not ingested")
    c.require(NON_TEXT_BODY_SENTINEL in body, "placeholder body carries the sentinel")
    c.require("Form 8-K." in body, "placeholder body names the form")
    c.require("8-K items: 2.02,9.01." in body, "placeholder body carries 8-K item codes")
    c.require(body.startswith("["), "placeholder body opens with the bracketed reason")


def check_skip_by_form_ars(c: Check) -> None:
    """ARS (skip-by-form): synthesised placeholder, no download at all."""
    from src.adapters.edgar import NON_TEXT_BODY_SENTINEL

    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "pdf_log.jsonl"
        adapter = _make_adapter(log_path)
        adapter._get_bytes = _refuse_network  # proves skip-by-form never downloads
        adapter._get_text = _refuse_network

        raw = _make_raw(form="ARS", document="ars2025.pdf", ticker="ARSCO")
        text = adapter.fetch_document_text(raw)

        c.require(NON_TEXT_BODY_SENTINEL in text, "ARS skip-by-form yields a placeholder body")
        c.require("Form ARS." in text, "ARS placeholder names the form")

        rows = _read_log_rows(log_path)
        c.equal(len(rows), 1, "ARS skip-by-form writes exactly one log row")
        c.equal(rows[0]["decision"], "skipped_form", "ARS skip-by-form logs decision=skipped_form")
        c.equal(rows[0]["bytes"], None, "ARS skip-by-form logs bytes=null (never downloaded)")
        c.equal(rows[0]["ticker"], "ARSCO", "log row carries the ticker")
        c.equal(rows[0]["form"], "ARS", "log row carries the form")


def check_skip_non_pdf_container(c: Check) -> None:
    """A non-PDF non-text container (.xlsx): skipped_form, no download at all."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "pdf_log.jsonl"
        adapter = _make_adapter(log_path)
        adapter._get_bytes = _refuse_network
        adapter._get_text = _refuse_network

        raw = _make_raw(form="8-K", document="data.xlsx", ticker="XLXCO")
        text = adapter.fetch_document_text(raw)

        c.require(text.startswith("["), "xlsx container yields a placeholder body")
        rows = _read_log_rows(log_path)
        c.equal(len(rows), 1, "xlsx container writes exactly one log row")
        c.equal(rows[0]["decision"], "skipped_form", "xlsx container logs decision=skipped_form")
        c.equal(rows[0]["bytes"], None, "xlsx container logs bytes=null (never downloaded)")


def check_pypdf_text(c: Check) -> None:
    """A small text-bearing PDF: extracted via pypdf, no OCR needed."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "pdf_log.jsonl"
        adapter = _make_adapter(log_path)
        pdf_bytes = _make_text_pdf_bytes()
        adapter._get_bytes = lambda url: pdf_bytes
        adapter._claude_ocr = lambda pdf_bytes, raw: (_ for _ in ()).throw(
            AssertionError("OCR must not be invoked when pypdf already found real text")
        )

        raw = _make_raw(form="8-K", document="exhibit99.pdf", ticker="TXTCO")
        text = adapter.fetch_document_text(raw)

        c.require("test SEC filing document" in text, "pypdf_text returns the real extracted content")
        c.require(len(text) >= 200, "extracted text clears the 200-char real-content floor")

        rows = _read_log_rows(log_path)
        c.equal(len(rows), 1, "text-bearing PDF writes exactly one log row")
        c.equal(rows[0]["decision"], "pypdf_text", "text-bearing PDF logs decision=pypdf_text")
        c.equal(rows[0]["bytes"], len(pdf_bytes), "log row records the downloaded byte count")
        c.equal(rows[0]["chars_out"], len(text), "log row's chars_out matches the returned body length")
        c.equal(rows[0]["model_id"], None, "pypdf_text path never touches a model, model_id is null")
        c.equal(rows[0]["cost_nzd"], None, "pypdf_text path costs nothing, cost_nzd is null")


def check_placeholder_too_big(c: Check) -> None:
    """A PDF over the size cap: placeholder without ever attempting extraction."""
    from src.adapters.edgar import _MAX_PDF_BYTES

    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "pdf_log.jsonl"
        adapter = _make_adapter(log_path)
        oversized = b"%PDF-1.4\n" + b"x" * (_MAX_PDF_BYTES + 1)
        adapter._get_bytes = lambda url: oversized
        adapter._claude_ocr = lambda pdf_bytes, raw: (_ for _ in ()).throw(
            AssertionError("OCR must not be invoked for an oversized PDF")
        )

        raw = _make_raw(form="8-K", document="huge.pdf", ticker="BIGCO")
        text = adapter.fetch_document_text(raw)

        c.require(text.startswith("["), "oversized PDF yields a placeholder body")
        rows = _read_log_rows(log_path)
        c.equal(rows[0]["decision"], "placeholder_too_big", "oversized PDF logs decision=placeholder_too_big")
        c.equal(rows[0]["bytes"], len(oversized), "log row records the oversized byte count")


def check_ocr_disabled(c: Check) -> None:
    """A PDF with no text layer, ocr_enabled=False: placeholder, OCR never called."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "pdf_log.jsonl"
        adapter = _make_adapter(log_path, ocr_enabled=False)
        empty_bytes = _make_empty_pdf_bytes()
        adapter._get_bytes = lambda url: empty_bytes
        adapter._claude_ocr = lambda pdf_bytes, raw: (_ for _ in ()).throw(
            AssertionError("OCR must not be invoked when ocr_enabled is False")
        )

        raw = _make_raw(form="8-K", document="scanned.pdf", ticker="SCANCO")
        text = adapter.fetch_document_text(raw)

        c.require(text.startswith("["), "no-text-layer PDF with OCR off yields a placeholder body")
        rows = _read_log_rows(log_path)
        c.equal(rows[0]["decision"], "placeholder_ocr_disabled", "logs decision=placeholder_ocr_disabled")
        c.equal(rows[0]["bytes"], len(empty_bytes), "log row records the downloaded byte count")
        c.equal(rows[0]["model_id"], None, "no model was used")


def check_claude_ocr_success(c: Check) -> None:
    """A PDF with no text layer, OCR enabled and succeeding: claude_ocr, its text returned."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "pdf_log.jsonl"
        adapter = _make_adapter(log_path, ocr_enabled=True)
        empty_bytes = _make_empty_pdf_bytes()
        adapter._get_bytes = lambda url: empty_bytes
        ocr_text = "Transcribed via mock OCR: quarterly results attached as a scanned exhibit."
        adapter._claude_ocr = lambda pdf_bytes, raw: (ocr_text, "claude-haiku-4-5-20251001", 0.0042)

        raw = _make_raw(form="8-K", document="scanned.pdf", ticker="OCRCO")
        text = adapter.fetch_document_text(raw)

        c.equal(text, ocr_text, "claude_ocr path returns the OCR'd text verbatim")
        rows = _read_log_rows(log_path)
        c.equal(rows[0]["decision"], "claude_ocr", "logs decision=claude_ocr")
        c.equal(rows[0]["model_id"], "claude-haiku-4-5-20251001", "log row carries the OCR model id")
        c.equal(rows[0]["cost_nzd"], 0.0042, "log row carries the OCR cost in NZD")
        c.equal(rows[0]["chars_out"], len(ocr_text), "log row's chars_out matches the returned text")


def check_claude_ocr_empty(c: Check) -> None:
    """OCR runs but returns nothing usable: placeholder_no_text."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "pdf_log.jsonl"
        adapter = _make_adapter(log_path, ocr_enabled=True)
        empty_bytes = _make_empty_pdf_bytes()
        adapter._get_bytes = lambda url: empty_bytes
        adapter._claude_ocr = lambda pdf_bytes, raw: ("", "", None)  # empty result, e.g. no key / no SDK

        raw = _make_raw(form="8-K", document="scanned.pdf", ticker="EMPTYCO")
        text = adapter.fetch_document_text(raw)

        c.require(text.startswith("["), "empty OCR result falls back to a placeholder body")
        rows = _read_log_rows(log_path)
        c.equal(rows[0]["decision"], "placeholder_no_text", "logs decision=placeholder_no_text")
        c.equal(rows[0]["cost_nzd"], None, "no cost recorded when OCR returned nothing")


def check_claude_ocr_error(c: Check) -> None:
    """OCR raises: the pipeline never crashes, falls back to a placeholder, logs 'error'."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "pdf_log.jsonl"
        adapter = _make_adapter(log_path, ocr_enabled=True)
        empty_bytes = _make_empty_pdf_bytes()
        adapter._get_bytes = lambda url: empty_bytes

        def _raise(pdf_bytes, raw):
            raise RuntimeError("simulated OCR failure")

        adapter._claude_ocr = _raise

        raw = _make_raw(form="8-K", document="scanned.pdf", ticker="ERRCO")
        text = adapter.fetch_document_text(raw)  # must not raise

        c.require(text.startswith("["), "an OCR exception still yields a placeholder body, not a crash")
        rows = _read_log_rows(log_path)
        c.equal(rows[0]["decision"], "error", "logs decision=error")
        c.require("simulated OCR failure" in rows[0]["detail"], "log row's detail carries the error message")


def check_log_rows_well_formed(c: Check) -> None:
    """Every decision this check exercised wrote a well-formed pdf_log.jsonl row."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "pdf_log.jsonl"
        adapter = _make_adapter(log_path, ocr_enabled=True)

        # ARS (no download)
        adapter._get_bytes = _refuse_network
        adapter.fetch_document_text(_make_raw(form="ARS", document="ars.pdf", ticker="A"))

        # xlsx container (no download)
        adapter.fetch_document_text(_make_raw(form="8-K", document="data.xlsx", ticker="B"))

        # pypdf_text
        text_bytes = _make_text_pdf_bytes()
        adapter._get_bytes = lambda url: text_bytes
        adapter._claude_ocr = lambda pdf_bytes, raw: ("", "", None)
        adapter.fetch_document_text(_make_raw(form="8-K", document="c.pdf", ticker="C"))

        # claude_ocr
        empty_bytes = _make_empty_pdf_bytes()
        adapter._get_bytes = lambda url: empty_bytes
        adapter._claude_ocr = lambda pdf_bytes, raw: ("ocr'd text here, non-trivial length.", "m", 0.01)
        adapter.fetch_document_text(_make_raw(form="8-K", document="d.pdf", ticker="D"))

        rows = _read_log_rows(log_path)
        c.equal(len(rows), 4, "four decisions were logged")
        for row in rows:
            c.equal(set(row.keys()), LOG_ROW_KEYS, f"log row for {row.get('ticker')} has exactly the documented keys")
            c.require(row["decision"] in VALID_DECISIONS, f"{row['ticker']}: decision {row['decision']!r} is a documented value")
            c.require(isinstance(row["ts"], str) and "T" in row["ts"], f"{row['ticker']}: ts is an ISO8601 string")
            c.require(isinstance(row["chars_out"], int), f"{row['ticker']}: chars_out is an int")
            c.require(row["bytes"] is None or isinstance(row["bytes"], int), f"{row['ticker']}: bytes is int|null")
            c.require(row["cost_nzd"] is None or isinstance(row["cost_nzd"], (int, float)), f"{row['ticker']}: cost_nzd is float|null")
            c.require(row["model_id"] is None or isinstance(row["model_id"], str), f"{row['ticker']}: model_id is str|null")
        c.note("out/pdf_log.jsonl schema: ts, announcement_id, ticker, form, primary_document, "
               "bytes, decision, chars_out, model_id, cost_nzd, detail — one JSON object per line")


def check_pdf_log_path_none_never_crashes(c: Check) -> None:
    """pdf_log_path=None (the default-safe construction) must skip logging, not crash."""
    from src.adapters.edgar import EdgarAdapter

    adapter = EdgarAdapter(
        watchlist=[], user_agent="check_pdf test agent", timeout_seconds=5, rate_limit_rps=0,
    )
    c.require(adapter.pdf_log_path is None, "pdf_log_path defaults to None")
    c.require(adapter.ocr_enabled is True, "ocr_enabled defaults to True (existing call sites unaffected)")
    adapter._get_bytes = _refuse_network
    text = adapter.fetch_document_text(_make_raw(form="ARS", document="ars.pdf", ticker="NOLOG"))
    c.require(text.startswith("["), "still produces a placeholder body with no log path configured")


def body(c: Check) -> None:
    check_is_non_text_document(c)
    check_placeholder_body(c)
    check_skip_by_form_ars(c)
    check_skip_non_pdf_container(c)
    check_pypdf_text(c)
    check_placeholder_too_big(c)
    check_ocr_disabled(c)
    check_claude_ocr_success(c)
    check_claude_ocr_empty(c)
    check_claude_ocr_error(c)
    check_log_rows_well_formed(c)
    check_pdf_log_path_none_never_crashes(c)


if __name__ == "__main__":
    run("tiered PDF pipeline: skip-by-form, pypdf, OCR fallback, decision log", body)
