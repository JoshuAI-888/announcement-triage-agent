"""edgar.py — reference ExchangeAdapter for SEC EDGAR (SPEC.md §6.1).

`poll` / `fetch_ticker` return raw submission payloads; `normalise` turns one
into a canonical `Announcement`, fetching the primary document and reducing it
to plain text. `price_sensitive_flag` returns None because EDGAR supplies no
such signal (SPEC.md §5.1).

Data source: the free, key-free data.sec.gov JSON API. EDGAR requires a
descriptive User-Agent with a contact address, taken from config.
"""

from __future__ import annotations

import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from src.adapters import UNKNOWN_DOC_TYPE, html_to_text, normalise_whitespace
from src.models import Announcement
from src.store import parse_iso

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{document}"


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
    ) -> None:
        self.watchlist = [t.upper() for t in watchlist]
        self.timeout = timeout_seconds
        self.doc_type_map = doc_type_map or {}
        self.truncate_chars = truncate_chars
        self.text_cache_dir = Path(text_cache_dir) if text_cache_dir else None
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

    def poll(self, since: datetime) -> list[dict]:
        """Return raw source payloads across the whole watchlist published after `since`."""
        out: list[dict] = []
        for ticker in self.watchlist:
            out.extend(self.fetch_ticker(ticker, since))
        return out

    def fetch_ticker(self, ticker: str, since: datetime) -> list[dict]:
        """Poll a single ticker. Raised exceptions are the caller's dead-letter boundary."""
        self._load_cik_map()
        cik10 = self._ticker_to_cik.get(ticker.upper())
        if cik10 is None:
            raise ValueError(
                f"watchlist ticker {ticker!r} not found in EDGAR company_tickers map"
            )
        data = self._get_json(SUBMISSIONS_URL.format(cik10=cik10))
        return self._extract_filings(ticker.upper(), cik10, data, since)

    def _extract_filings(
        self, ticker: str, cik10: str, data: dict, since: datetime
    ) -> list[dict]:
        company_name = data.get("name", ticker)
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

    def fetch_document_text(self, raw: dict) -> str:
        """Plain text of the filing's primary document, whitespace-normalised.

        Cached next to the raw payload so re-normalising a corpus costs no
        further requests against EDGAR.
        """
        if not raw.get("primary_document"):
            raise ValueError(
                f"filing {raw['accession_number']} has no primary document to fetch"
            )

        cache_path = None
        if self.text_cache_dir is not None and raw.get("announcement_id"):
            cache_path = self.text_cache_dir / f"{raw['announcement_id']}.txt"
            if cache_path.is_file():
                return cache_path.read_text(encoding="utf-8")

        text = normalise_whitespace(html_to_text(self._get_text(raw["source_url"])))
        if not text:
            raise ValueError(
                f"filing {raw['accession_number']} produced no text from {raw['source_url']}"
            )
        if cache_path is not None:
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
