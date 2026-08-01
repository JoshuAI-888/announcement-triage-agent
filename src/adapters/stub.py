"""stub.py — a second adapter that satisfies the protocol and does nothing.

Its purpose is to prove the ExchangeAdapter interface generalises past the
reference exchange, not to work (SPEC.md §6.1). `poll()` returns an empty list;
`normalise()` refuses rather than inventing a record.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.adapters import UNKNOWN_DOC_TYPE
from src.models import Announcement


class StubAdapter:
    exchange_code = "STUB"

    def poll(self, since: datetime) -> list[dict]:
        return []

    def normalise(self, raw: dict) -> Announcement:
        raise NotImplementedError(
            "StubAdapter proves the interface generalises; it has no source to normalise"
        )

    def map_doc_type(self, native_type: str) -> str:
        return UNKNOWN_DOC_TYPE

    def price_sensitive_flag(self, raw: dict) -> Optional[bool]:
        return None
