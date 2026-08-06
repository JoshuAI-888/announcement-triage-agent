"""edgar.py — reference ExchangeAdapter for SEC EDGAR (SPEC.md §6.1).

`poll` / `fetch_ticker` return raw submission payloads; `normalise` turns one
into a canonical `Announcement`, fetching the primary document and reducing it
to plain text. `price_sensitive_flag` returns None because EDGAR supplies no
such signal (SPEC.md §5.1).

Data source: the free, key-free data.sec.gov JSON API. EDGAR requires a
descriptive User-Agent with a contact address, taken from config.
"""

from __future__ import annotations

import base64
import io
import json
import os
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from pypdf import PdfReader

from src.adapters import UNKNOWN_DOC_TYPE, html_to_text, normalise_whitespace
from src.models import Announcement
from src.store import parse_iso

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{document}"

# Primary-document filenames whose bytes are NOT narrative text. Running
# html_to_text over these dumps the raw container (e.g. a multi-MB %PDF operator
# stream) into body_text, which truncates the real signal and bloats the text
# cache. We skip ingesting the bytes and synthesise a short metadata-only body
# instead (see `_placeholder_body`). ARS — the glossy annual report to
# shareholders, a PDF that duplicates the separately-filed 10-K — is the common
# case; spreadsheet / archive / image exhibits are others.
_NON_TEXT_DOC_SUFFIXES = (
    ".pdf", ".xlsx", ".xls", ".zip",
    ".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff",
)
# Leading bytes of a PDF. Guards the fetch path (a doc served as PDF despite a
# text/HTML filename) and stale caches written before this skip logic existed.
_PDF_MAGIC = "%PDF-"
# Embedded in every synthesised metadata body (see `_placeholder_body`) so
# downstream code — checks, ranking, the brief — can recognise a filing whose
# primary document was not ingested and treat its short body as intentional.
NON_TEXT_BODY_SENTINEL = "primary document not ingested:"

# --- tiered PDF pipeline (SPEC.md §6.1 extension) ----------------------------
#
# A blanket "skip every PDF" rule throws away real narrative text: most 8-K /
# 10-K / 10-Q exhibits filed as PDF are ordinary text documents with a text
# layer that extracts cleanly. Only a narrow set of forms are routine/glossy
# duplicates worth skipping outright — ARS (the annual report to shareholders)
# duplicates the separately-filed 10-K and is never itself the event.
_SKIP_EXTRACTION_FORMS = {"ARS"}
# Above this many bytes we don't attempt extraction — pypdf and (especially)
# base64-encoding the whole document for OCR both get expensive/slow past a
# few MB, and a filing this large is not going to be summarised faithfully by
# either path anyway.
_MAX_PDF_BYTES = 15 * 1024 * 1024
# Pinned Claude model for native-PDF OCR — independent of run.provider, since
# ANTHROPIC_API_KEY is always present even when the configured classifier
# provider is openai/glm.
_OCR_MODEL = "claude-haiku-4-5-20251001"


class EdgarAdapter:
    exchange_code = "EDGAR"

    def __init__(
        self,
        *,
        watchlist: list[str],
        user_agent: str,
        timeout_seconds: int,
        rate_limit_rps: float,
        doc_type_map: Optional[dict[str, str]] = None,
        truncate_chars: Optional[int] = None,
        text_cache_dir: Optional[Path] = None,
        ocr_enabled: bool = True,
        pdf_log_path: Optional[Path] = None,
        ocr_pricing_usd_per_mtok: Optional[dict] = None,
        fx_usd_nzd: Optional[float] = None,
    ) -> None:
        self.watchlist = [t.upper() for t in watchlist]
        self.timeout = timeout_seconds
        self.doc_type_map = doc_type_map or {}
        self.truncate_chars = truncate_chars
        self.text_cache_dir = Path(text_cache_dir) if text_cache_dir else None
        # OCR toggle: default True so every existing call site (checks, other
        # adapters, ad-hoc scripts constructing EdgarAdapter directly) keeps
        # working unchanged.
        self.ocr_enabled = ocr_enabled
        # Append-only decision log for PDF-tier routing (SPEC.md §6.1
        # extension). None disables logging entirely — offline checks and
        # scripts that don't care about the audit trail don't need to pass it.
        self.pdf_log_path = Path(pdf_log_path) if pdf_log_path else None
        # Claude pricing + FX for OCR cost accounting. This is ALWAYS the
        # "claude" provider's pricing regardless of run.provider — OCR is
        # pinned to Claude, so its cost must be priced in Claude's own rates,
        # not whatever provider the daily classifier is configured to use.
        self._ocr_pricing = ocr_pricing_usd_per_mtok or {}
        self._fx_usd_nzd = fx_usd_nzd
        self._min_interval = 1.0 / rate_limit_rps if rate_limit_rps > 0 else 0.0
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        )
        self._last_request_at = 0.0
        self._ticker_to_cik: dict[str, str] = {}

    # --- HTTP with rate limiting + retries (SPEC.md §12) ---------------------

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        wait = self._min_interval - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)

    def _get_json(self, url: str) -> object:
        """GET + parse JSON with two retries on transport failure (2s, 8s backoff)."""
        backoffs = [2, 8]
        attempt = 0
        while True:
            self._throttle()
            try:
                resp = self._session.get(url, timeout=self.timeout)
                self._last_request_at = time.monotonic()
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException:
                self._last_request_at = time.monotonic()
                if attempt >= len(backoffs):
                    raise
                time.sleep(backoffs[attempt])
                attempt += 1

    def _load_cik_map(self) -> None:
        if self._ticker_to_cik:
            return
        data = self._get_json(TICKERS_URL)
        for entry in data.values():
            self._ticker_to_cik[entry["ticker"].upper()] = str(entry["cik_str"]).zfill(10)

    # --- ExchangeAdapter protocol (SPEC.md §6.1) -----------------------------

    def poll(self, since: datetime, until: Optional[datetime] = None) -> list[dict]:
        """Return raw source payloads across the whole watchlist published in (since, until]."""
        out: list[dict] = []
        for ticker in self.watchlist:
            out.extend(self.fetch_ticker(ticker, since, until=until))
        return out

    def fetch_ticker(self, ticker: str, since: datetime, until: Optional[datetime] = None) -> list[dict]:
        """Poll a single ticker. Raised exceptions are the caller's dead-letter boundary."""
        self._load_cik_map()
        cik10 = self._ticker_to_cik.get(ticker.upper())
        if cik10 is None:
            raise ValueError(
                f"watchlist ticker {ticker!r} not found in EDGAR company_tickers map"
            )
        data = self._get_json(SUBMISSIONS_URL.format(cik10=cik10))
        return self._extract_filings(ticker.upper(), cik10, data, since, until=until)

    def _extract_filings(
        self, ticker: str, cik10: str, data: dict, since: datetime, until: Optional[datetime] = None
    ) -> list[dict]:
        company_name = data.get("name", ticker)
        # SIC description (industry) lives at the top level of the submissions
        # JSON, one per issuer — not per filing. Carried through on every raw
        # filing dict so normalise() can put it on the Announcement; it plays
        # no part in compute_id (SPEC.md §5.1 hash inputs are unchanged).
        industry = data.get("sicDescription") or None
        recent = data.get("filings", {}).get("recent", {})
        accession = recent.get("accessionNumber", [])
        forms = recent.get("form", [])
        acceptance = recent.get("acceptanceDateTime", [])
        filing_date = recent.get("filingDate", [])
        report_date = recent.get("reportDate", [])
        primary_doc = recent.get("primaryDocument", [])
        primary_desc = recent.get("primaryDocDescription", [])
        items = recent.get("items", [])
        cik_int = str(int(cik10))

        def at(seq, i):
            return seq[i] if i < len(seq) else None

        out: list[dict] = []
        for i in range(len(accession)):
            accepted_raw = at(acceptance, i) or at(filing_date, i)
            if not accepted_raw:
                continue
            published_at = parse_iso(accepted_raw)
            if since is not None and published_at <= since:
                continue
            if until is not None and published_at > until:
                continue

            form = at(forms, i) or ""
            desc = (at(primary_desc, i) or "").strip()
            headline = desc or f"{form} filing"
            document = at(primary_doc, i) or ""
            source_url = ARCHIVE_URL.format(
                cik=cik_int,
                accession_nodash=accession[i].replace("-", ""),
                document=document,
            )
            out.append(
                {
                    "exchange": self.exchange_code,
                    "ticker": ticker,
                    "cik": cik10,
                    "company_name": company_name,
                    "industry": industry,
                    "form": form,
                    "native_doc_type": form,
                    "accession_number": accession[i],
                    "filing_date": at(filing_date, i),
                    "report_date": at(report_date, i),
                    "acceptance_datetime": accepted_raw,
                    "published_at": published_at.isoformat(),
                    "headline": headline,
                    "primary_document": document,
                    "primary_doc_description": desc,
                    "items": at(items, i) or "",
                    "source_url": source_url,
                }
            )
        return out

    # --- document text -------------------------------------------------------

    def _get_text(self, url: str) -> str:
        """GET a document body with the same throttle and retry policy as the JSON API."""
        backoffs = [2, 8]
        attempt = 0
        while True:
            self._throttle()
            try:
                resp = self._session.get(url, timeout=self.timeout)
                self._last_request_at = time.monotonic()
                resp.raise_for_status()
                return resp.text
            except requests.RequestException:
                self._last_request_at = time.monotonic()
                if attempt >= len(backoffs):
                    raise
                time.sleep(backoffs[attempt])
                attempt += 1

    def _get_bytes(self, url: str) -> bytes:
        """GET raw bytes with the same throttle and retry policy as `_get_text`."""
        backoffs = [2, 8]
        attempt = 0
        while True:
            self._throttle()
            try:
                resp = self._session.get(url, timeout=self.timeout)
                self._last_request_at = time.monotonic()
                resp.raise_for_status()
                return resp.content
            except requests.RequestException:
                self._last_request_at = time.monotonic()
                if attempt >= len(backoffs):
                    raise
                time.sleep(backoffs[attempt])
                attempt += 1

    @staticmethod
    def _is_non_text_document(document: str) -> bool:
        """True if the primary-document filename is a non-text container (PDF/xlsx/image)."""
        return document.lower().strip().endswith(_NON_TEXT_DOC_SUFFIXES)

    @staticmethod
    def _placeholder_body(raw: dict, reason: str) -> str:
        """A short metadata-only body for a filing whose primary document is not text.

        The filing is NOT dropped: it keeps flowing through classify/rank so it
        still surfaces. Crucially it carries the submissions-JSON materiality
        signal that is independent of the document body — the form and, for 8-Ks,
        the item codes (2.02 results, 1.01 material agreement, 5.02 departures,
        8.01 other events) — so an event filing is classified on what it is even
        when we cannot read its PDF. With only metadata to ground on, the
        classifier stays low-confidence and the item routes to human review
        rather than being silently called immaterial.
        """
        form = (raw.get("form") or "filing").strip()
        items = (raw.get("items") or "").strip()
        desc = (raw.get("primary_doc_description") or raw.get("headline") or "").strip()
        document = (raw.get("primary_document") or "").strip()
        parts = [f"[{reason}: {document}]", f"Form {form}."]
        if items:
            parts.append(f"8-K items: {items}." if form.startswith("8-K") else f"Items: {items}.")
        if desc:
            parts.append(desc)
        return normalise_whitespace(" ".join(parts))

    # --- PDF decision log (out/pdf_log.jsonl) --------------------------------

    def _log_pdf_decision(
        self,
        raw: dict,
        *,
        decision: str,
        body_text: str,
        pdf_bytes: Optional[bytes] = None,
        model_id: Optional[str] = None,
        cost_nzd: Optional[float] = None,
        detail: str = "",
    ) -> None:
        """Append one JSON row recording a PDF-tier routing decision.

        Never raised to the caller — a logging failure (disk full, missing
        parent, permissions) must not take down the fetch pipeline. Called for
        every PDF decision (skip/extract/OCR/placeholder), never for the
        normal HTML text path.
        """
        if self.pdf_log_path is None:
            return
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "announcement_id": raw.get("announcement_id"),
            "ticker": raw.get("ticker"),
            "form": raw.get("form"),
            "primary_document": raw.get("primary_document"),
            "bytes": len(pdf_bytes) if pdf_bytes is not None else None,
            "decision": decision,
            "chars_out": len(body_text),
            "model_id": model_id,
            "cost_nzd": cost_nzd,
            "detail": detail,
        }
        try:
            self.pdf_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.pdf_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # --- PDF text extraction --------------------------------------------------

    @staticmethod
    def _extract_pdf_text(pdf_bytes: bytes) -> str:
        """Best-effort text layer extraction via pypdf.

        Never raises: a corrupt, encrypted or unreadable PDF yields empty
        text so the caller falls through to OCR (or a placeholder) instead of
        crashing the fetch pipeline.
        """
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            parts = []
            for page in reader.pages:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    continue
            return "\n".join(parts)
        except Exception:
            return ""

    def _claude_ocr(self, pdf_bytes: bytes, raw: dict) -> tuple[str, str, Optional[float]]:
        """OCR a scanned/image PDF via the Claude API directly.

        PINNED to Claude — uses the `anthropic` SDK and `ANTHROPIC_API_KEY`
        directly, NOT the configured provider client (run.provider may be
        openai/glm; OCR must still work, since ANTHROPIC_API_KEY is always
        present regardless of which provider classifies the daily brief).

        Best-effort and defensive: any failure (SDK not installed, no API
        key, network/API error) returns ("", "", None) so the caller falls
        back to a placeholder body. This method must NEVER raise — it runs
        inside the adapter's normal document-fetch path, which many other
        filings depend on completing.
        """
        try:
            from anthropic import Anthropic
        except ImportError:
            return "", "", None

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return "", "", None

        try:
            client = Anthropic(api_key=api_key)
            b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")
            response = client.messages.create(
                model=_OCR_MODEL,
                max_tokens=4096,
                temperature=0,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Transcribe all readable text from this filing as "
                                    "plain text. Output only the transcription."
                                ),
                            },
                        ],
                    }
                ],
            )
            text_blocks = [
                block.text for block in response.content if getattr(block, "type", None) == "text"
            ]
            text = normalise_whitespace("\n".join(text_blocks))

            cost_nzd: Optional[float] = None
            try:
                usage = response.usage
                in_rate = self._ocr_pricing.get("input")
                out_rate = self._ocr_pricing.get("output")
                if usage is not None and self._fx_usd_nzd and in_rate is not None and out_rate is not None:
                    usd = (
                        (usage.input_tokens / 1_000_000) * in_rate
                        + (usage.output_tokens / 1_000_000) * out_rate
                    )
                    cost_nzd = usd * self._fx_usd_nzd
            except Exception:
                cost_nzd = None  # best-effort — a missing/odd usage shape must not crash OCR

            return text, _OCR_MODEL, cost_nzd
        except Exception:
            return "", "", None

    # --- tiered PDF pipeline ---------------------------------------------------

    def _fetch_pdf_document(self, raw: dict) -> str:
        """Tiered handling for a primary document that is (or turned out to be) a PDF.

        1. Skip-by-form: routine/redundant forms (ARS — the glossy annual
           report, which duplicates the separately-filed 10-K) get a metadata
           placeholder without ever downloading the bytes.
        2. Otherwise download the PDF bytes (enforcing `_MAX_PDF_BYTES`) and
           extract with pypdf. Real extracted content (>=200 non-whitespace
           chars) is used as-is.
        3. A PDF with no usable text layer (scanned/image PDF) falls to
           Claude OCR when `self.ocr_enabled`, else a placeholder.

        Every branch logs a decision row via `_log_pdf_decision` — this is
        the only place PDF decisions are logged; the normal HTML path logs
        nothing.
        """
        form = (raw.get("form") or "").strip().upper()

        if form in _SKIP_EXTRACTION_FORMS:
            text = self._placeholder_body(raw, "routine-form PDF primary document not ingested")
            self._log_pdf_decision(
                raw, decision="skipped_form", body_text=text,
                detail=f"form {form} is in the routine/redundant skip-extraction set",
            )
            return text

        pdf_bytes = self._get_bytes(raw["source_url"])

        if len(pdf_bytes) > _MAX_PDF_BYTES:
            text = self._placeholder_body(raw, "oversized PDF primary document not ingested")
            self._log_pdf_decision(
                raw, decision="placeholder_too_big", body_text=text, pdf_bytes=pdf_bytes,
                detail=f"{len(pdf_bytes)} bytes exceeds the {_MAX_PDF_BYTES}-byte cap",
            )
            return text

        pypdf_text = normalise_whitespace(self._extract_pdf_text(pdf_bytes))
        non_ws_chars = sum(1 for ch in pypdf_text if not ch.isspace())
        if non_ws_chars >= 200:
            self._log_pdf_decision(
                raw, decision="pypdf_text", body_text=pypdf_text, pdf_bytes=pdf_bytes,
                detail=f"pypdf extracted {non_ws_chars} non-whitespace chars",
            )
            return pypdf_text

        if not self.ocr_enabled:
            text = self._placeholder_body(raw, "scanned PDF primary document not ingested")
            self._log_pdf_decision(
                raw, decision="placeholder_ocr_disabled", body_text=text, pdf_bytes=pdf_bytes,
                detail=f"pypdf found only {non_ws_chars} non-whitespace chars; ocr_enabled=False",
            )
            return text

        try:
            ocr_text, model_id, cost_nzd = self._claude_ocr(pdf_bytes, raw)
        except Exception as exc:  # _claude_ocr is already defensive; belt-and-suspenders
            text = self._placeholder_body(raw, "scanned PDF primary document not ingested")
            self._log_pdf_decision(
                raw, decision="error", body_text=text, pdf_bytes=pdf_bytes,
                detail=f"Claude OCR raised: {exc}",
            )
            return text

        if ocr_text:
            self._log_pdf_decision(
                raw, decision="claude_ocr", body_text=ocr_text, pdf_bytes=pdf_bytes,
                model_id=model_id, cost_nzd=cost_nzd,
                detail="pypdf found no text layer; Claude native-PDF OCR used",
            )
            return ocr_text

        text = self._placeholder_body(raw, "scanned PDF primary document not ingested")
        self._log_pdf_decision(
            raw, decision="placeholder_no_text", body_text=text, pdf_bytes=pdf_bytes,
            detail="pypdf found no text layer and Claude OCR returned no text",
        )
        return text

    def fetch_document_text(self, raw: dict) -> str:
        """Plain text of the filing's primary document, whitespace-normalised.

        Cached next to the raw payload so re-normalising a corpus costs no
        further requests against EDGAR. Non-text-container primary documents
        (spreadsheet / archive / image) are never fetched or cached as bytes
        — they get a synthesised metadata body instead (see
        `_placeholder_body`). PDF primary documents go through the tiered
        pipeline (see `_fetch_pdf_document`): skip-by-form, pypdf extraction,
        then optional Claude OCR, each decision logged.
        """
        if not raw.get("primary_document"):
            raise ValueError(
                f"filing {raw['accession_number']} has no primary document to fetch"
            )

        cache_path = None
        if self.text_cache_dir is not None and raw.get("announcement_id"):
            cache_path = self.text_cache_dir / f"{raw['announcement_id']}.txt"
            if cache_path.is_file():
                cached = cache_path.read_text(encoding="utf-8")
                # A raw PDF stream cached before this skip logic existed is
                # re-synthesised below rather than returned as garbage body_text.
                if not cached.startswith(_PDF_MAGIC):
                    return cached

        document = raw["primary_document"]

        if document.lower().strip().endswith(".pdf"):
            text = self._fetch_pdf_document(raw)
        elif self._is_non_text_document(document):
            # Non-PDF non-text container (xlsx/zip/image): skip the download
            # entirely — the bytes carry no extractable narrative. No PDF-tier
            # decision to make, but still logged as skipped_form for the
            # dashboard's decision-log completeness.
            text = self._placeholder_body(raw, "non-text primary document not ingested")
            self._log_pdf_decision(
                raw, decision="skipped_form", body_text=text,
                detail=f"non-PDF non-text container ({document})",
            )
        else:
            raw_text = self._get_text(raw["source_url"])
            if raw_text.startswith(_PDF_MAGIC):
                # Served as a PDF despite a text/HTML filename: route through
                # the same tiered PDF pipeline (re-fetched as bytes below —
                # the text GET above cannot be reused for pypdf/OCR).
                text = self._fetch_pdf_document(raw)
            else:
                # Normal HTML/text document — no PDF decision, nothing logged.
                text = normalise_whitespace(html_to_text(raw_text))
        if not text:
            raise ValueError(
                f"filing {raw['accession_number']} produced no text from {raw['source_url']}"
            )
        # Cache guard: a %PDF stream must never be written (every branch above
        # guarantees `text` is synthesised metadata or extracted text, never
        # raw PDF bytes).
        if cache_path is not None and not text.startswith(_PDF_MAGIC):
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(text, encoding="utf-8")
        return text

    # --- ExchangeAdapter protocol (continued) --------------------------------

    def map_doc_type(self, native_type: str) -> str:
        """Native EDGAR form -> canonical enum. Unknown -> 'admin', with a warning."""
        key = (native_type or "").strip().upper()
        mapped = self.doc_type_map.get(key)
        if mapped is None:
            warnings.warn(
                f"unmapped EDGAR form {native_type!r}; falling back to {UNKNOWN_DOC_TYPE!r} "
                f"(add it to config/doc_type_map.yaml)",
                stacklevel=2,
            )
            return UNKNOWN_DOC_TYPE
        return mapped

    def normalise(self, raw: dict) -> Announcement:
        """Raw EDGAR payload -> canonical Announcement (SPEC.md §5.1)."""
        published_at = parse_iso(raw["published_at"])
        ticker = raw["ticker"].upper()
        headline = normalise_whitespace(raw["headline"])
        native_id = raw["accession_number"]

        body_text = self.fetch_document_text(raw)
        truncated = self.truncate_chars is not None and len(body_text) > self.truncate_chars
        if truncated:
            print(
                f"TRUNCATION: {ticker} {raw['form']} {native_id} cut from "
                f"{len(body_text)} to {self.truncate_chars} chars"
            )
            # rstrip so the hard cut cannot leave a ragged trailing space.
            body_text = body_text[: self.truncate_chars].rstrip()

        return Announcement(
            announcement_id=Announcement.compute_id(
                self.exchange_code, ticker, published_at, headline, native_id
            ),
            exchange=self.exchange_code,
            ticker=ticker,
            company_name=raw["company_name"],
            industry=raw.get("industry"),
            published_at=published_at,
            headline=headline,
            doc_type=self.map_doc_type(raw["form"]),
            native_doc_type=self._native_doc_type(raw),
            native_id=native_id,
            issuer_price_sensitive_flag=self.price_sensitive_flag(raw),
            body_text=body_text,
            char_count=len(body_text),
            truncated=truncated,
            source_url=raw["source_url"],
            fetched_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _native_doc_type(raw: dict) -> str:
        """The source's own label, kept for audit. 8-K item codes are part of it."""
        form = raw["form"]
        items = (raw.get("items") or "").strip()
        return f"{form} [{items}]" if items else form

    def price_sensitive_flag(self, raw: dict) -> Optional[bool]:
        return None  # EDGAR supplies no price-sensitive signal (SPEC.md §5.1)
