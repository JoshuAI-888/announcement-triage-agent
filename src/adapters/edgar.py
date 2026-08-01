"""edgar.py — reference ExchangeAdapter for SEC EDGAR (SPEC.md §6.1).

Increment 2 implements `poll` / `fetch_ticker` (fetch only). `normalise` and
`map_doc_type` belong to Increment 3 and raise NotImplementedError until then.
`price_sensitive_flag` returns None because EDGAR supplies no such signal
(SPEC.md §5.1).

Data source: the free, key-free data.sec.gov JSON API. EDGAR requires a
descriptive User-Agent with a contact address, taken from config.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

import requests

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
    ) -> None:
        self.watchlist = [t.upper() for t in watchlist]
        self.timeout = timeout_seconds
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

    def map_doc_type(self, native_type: str) -> str:
        raise NotImplementedError(
            "doc_type mapping is Increment 3 (normalise.py + config/doc_type_map.yaml)"
        )

    def normalise(self, raw: dict):
        raise NotImplementedError("normalisation is Increment 3 (normalise.py)")

    def price_sensitive_flag(self, raw: dict) -> Optional[bool]:
        return None  # EDGAR supplies no price-sensitive signal (SPEC.md §5.1)
