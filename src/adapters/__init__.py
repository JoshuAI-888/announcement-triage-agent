"""ExchangeAdapter protocol (SPEC.md §6.1).

Every exchange names the same document a different thing and publishes it a
different way. An adapter is the only place that knowledge is allowed to live:
everything downstream of `normalise()` sees canonical `Announcement` records
and nothing else.

One reference implementation (`edgar.py`) and one stub (`stub.py`). The stub's
purpose is to prove the interface generalises, not to work.
"""

from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

import yaml

from src.models import Announcement

# Native doc type that could not be mapped. Never guess — SPEC.md §6.2.
UNKNOWN_DOC_TYPE = "admin"

DOC_TYPE_MAP_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "doc_type_map.yaml"


def load_doc_type_map(exchange: str) -> dict[str, str]:
    """The native -> canonical doc_type mapping for one exchange (SPEC.md §6.2)."""
    mapping = yaml.safe_load(DOC_TYPE_MAP_PATH.read_text(encoding="utf-8"))
    if exchange not in mapping:
        raise ValueError(f"config/doc_type_map.yaml has no section for exchange {exchange!r}")
    return {str(key).upper(): value for key, value in (mapping[exchange] or {}).items()}


@runtime_checkable
class ExchangeAdapter(Protocol):
    exchange_code: str

    def poll(self, since: datetime) -> list[dict]:
        """Return raw source payloads published after `since`."""

    def normalise(self, raw: dict) -> Announcement:
        """Raw payload -> canonical Announcement."""

    def map_doc_type(self, native_type: str) -> str:
        """Native taxonomy -> canonical enum. Unknown -> 'admin', and log it."""

    def price_sensitive_flag(self, raw: dict) -> Optional[bool]:
        """None where the exchange supplies no such signal."""


# --- source document -> plain text -------------------------------------------
#
# Turning a source's native document format into plain text is adapter work, so
# it lives here rather than downstream. Standard library only (SPEC.md §3).

_BLOCK_TAGS = {
    "p", "div", "br", "tr", "table", "li", "ul", "ol", "h1", "h2", "h3", "h4",
    "h5", "h6", "hr", "section", "article", "td", "th", "blockquote", "pre",
}
# Only tags whose *content* is not visible text. Void elements (meta, link, br,
# img) must never appear here: they have no end tag, so a depth counter that
# they increment is never decremented and the rest of the document disappears.
_SKIP_TAGS = {"script", "style", "title"}


class _TextExtractor(HTMLParser):
    """Collect visible text, inserting breaks at block boundaries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        # Self-closing: contributes a break at most, never a skip depth.
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    """Reduce an HTML or XML filing document to its visible text."""
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    text = "".join(parser.parts)
    # Filings are full of non-breaking, zero-width and BOM characters. To G2 they
    # are invisible differences between a quote and its source, so drop them here.
    return text.replace("\xa0", " ").replace("\u200b", "").replace("\ufeff", "")


def normalise_whitespace(text: str) -> str:
    """Collapse runs of whitespace, keeping at most one blank line between blocks.

    `body_text` is compared character-for-character against `evidence_quote` by
    guardrail G2, so the normalisation applied here has to be stable and
    documented rather than incidental.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n")]

    out: list[str] = []
    for line in lines:
        if line:
            out.append(line)
        elif out and out[-1] != "":
            out.append("")
    return "\n".join(out).strip()
