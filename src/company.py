"""company.py — best-effort, cached AI company profiles (deploy build, Phase 1).

One Claude call per ticker, PINNED to Claude regardless of `run.provider` — the
same pattern as `src.adapters.edgar._claude_ocr` — because `ANTHROPIC_API_KEY`
is always present even when the configured classifier provider is openai/glm.
Results are cached in committed `data/company_profiles.json` keyed by ticker,
so a given ticker is ever profiled once across the life of the repo.

Best-effort: any failure (no SDK, no key, network/API error, an unreadable
cache file) degrades to an industry-only profile. This module must NEVER
raise — it runs inside the enrich step that every other filing in the run
depends on completing.

Callers are expected to call this ONLY for the items that warrant the cost
(material + needs-a-look), not every classified filing — see src/enrich.py.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")  # make ANTHROPIC_API_KEY available, like src/classify.py

CACHE_PATH = ROOT / "data" / "company_profiles.json"

# Pinned Claude model for company profiles — independent of run.provider, the
# same pattern as src.adapters.edgar._OCR_MODEL.
_PROFILE_MODEL = "claude-haiku-4-5-20251001"

CAVEAT = "AI-generated context from general knowledge — verify before relying."

try:  # pragma: no cover — replaced with a fake in checks/check_company.py
    from anthropic import Anthropic
except ImportError:  # pragma: no cover
    Anthropic = None  # type: ignore[assignment]


def _read_cache(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}  # a corrupt cache file is treated as empty, not fatal


def _write_cache(cache: dict, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    except OSError:
        pass  # best-effort — a disk problem must not break the run


def _parse_profile(text: str) -> tuple[str, str]:
    """Prefer explicit `Business:` / `Edge:` labels (what the prompt requests);
    fall back to a first-sentence split only when the model returned no labels.
    Best-effort, never raises."""
    business = edge = ""
    for line in text.replace("\r", "\n").split("\n"):
        s = line.strip().lstrip("-*• ").strip()
        low = s.lower()
        if low.startswith("business:"):
            business = s.split(":", 1)[1].strip()
        elif low.startswith("edge:"):
            edge = s.split(":", 1)[1].strip()
    if business or edge:
        return business, edge
    return _split_sentences(text)


def _split_sentences(text: str) -> tuple[str, str]:
    """First sentence -> business, the rest -> edge. Abbreviation-safe so a period
    in "Inc." / "Corp." doesn't end the sentence. Best-effort, never raises."""
    protected = text.replace("\n", " ")
    for abbr in ("Inc.", "Corp.", "Co.", "Cos.", "Ltd.", "L.P.", "LLC.", "plc.",
                 "S.A.", "N.V.", "U.S.", "Mfg.", "Jr.", "Sr.", "St."):
        protected = protected.replace(abbr, abbr.replace(".", "\x00"))
    parts = [s.strip() for s in protected.split(". ") if s.strip()]
    if not parts:
        return "", ""
    restore = lambda s: s.replace("\x00", ".")
    business = restore(parts[0]).rstrip(". ") + "."
    edge = restore(". ".join(parts[1:])).rstrip(". ")
    if edge:
        edge += "."
    return business, edge


def _generate(ticker: str, company_name: str) -> Optional[tuple[str, str]]:
    """One Claude call: (business, edge), or None on any failure. Never raises.

    PINNED to Claude via the `anthropic` SDK + ANTHROPIC_API_KEY directly, NOT
    the configured provider client (run.provider may be openai/glm; this must
    still work).
    """
    if Anthropic is None:
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        client = Anthropic(api_key=api_key)
        prompt = (
            f"Describe {company_name} ({ticker}) factually and neutrally from general "
            f"knowledge, as exactly two labelled lines and nothing else. Do not restate "
            f"the company name; no buy/sell/hold/target-price/recommendation wording.\n"
            f"Business: <one short sentence on what the company does>\n"
            f"Edge: <one short sentence on its main competitive edge or moat>"
        )
        response = client.messages.create(
            model=_PROFILE_MODEL,
            max_tokens=200,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        text = "\n".join(t.strip() for t in text_blocks if t.strip())
        if not text:
            return None
        business, edge = _parse_profile(text)
        if not (business or edge):
            return None
        return business, edge
    except Exception:
        return None


def company_profile(
    ticker: str,
    company_name: str,
    industry: Optional[str],
    config: dict,
    cache_path: Path = CACHE_PATH,
) -> dict:
    """Best-effort, cached company profile. NEVER raises — see module docstring.

    Returns {"industry": industry, "business": str, "edge": str, "caveat": CAVEAT}.
    `business`/`edge` are "" when generation failed or hasn't run — the caller
    can always render `industry` alone in that case.
    """
    try:
        cache = _read_cache(cache_path)
        entry = cache.get(ticker)
        if entry is None:
            generated = _generate(ticker, company_name)
            if generated is None:
                return {"industry": industry, "business": "", "edge": "", "caveat": CAVEAT}
            business, edge = generated
            entry = {
                "business": business,
                "edge": edge,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            cache[ticker] = entry
            _write_cache(cache, cache_path)
        return {
            "industry": industry,
            "business": entry.get("business", ""),
            "edge": entry.get("edge", ""),
            "caveat": CAVEAT,
        }
    except Exception:
        return {"industry": industry, "business": "", "edge": "", "caveat": CAVEAT}
