"""A1 — skeleton, config.yaml, src/models.py.

Asserts the repository skeleton exists (SPEC.md §2), that config.yaml carries
every tunable named in SPEC.md §4, and that the Pydantic contracts in
src/models.py match SPEC.md §5 field for field — including the amended
announcement_id hash (v1.1, native_id folded in) and fail-loud validation.

Run:  python -m checks.check_skeleton
"""

from __future__ import annotations

import hashlib
import typing
from datetime import datetime, timezone
from pathlib import Path

import yaml

from checks._harness import Check, run

ROOT = Path(__file__).resolve().parent.parent

# SPEC.md §2 — the parts of the layout that Increment 1 is responsible for.
# README.md, prompts/classify_v*.md and data/gold/* belong to later increments
# or to the owner, so they are deliberately not asserted here.
REQUIRED_FILES = [
    "SPEC.md",
    "requirements.txt",
    "config.yaml",
    ".gitignore",
    "src/__init__.py",
    "src/models.py",
    "src/adapters/__init__.py",
    "src/fetch.py",
    "src/normalise.py",
    "src/classify.py",
    "src/verify.py",
    "src/rank.py",
    "src/brief.py",
    "src/store.py",
    "src/run.py",
    "evals/__init__.py",
    "evals/run_eval.py",
    "evals/baselines.py",
    "evals/report.py",
]

REQUIRED_DIRS = ["data/raw", "prompts", "out/briefs", "out/eval_runs", "src/adapters", "evals"]

# SPEC.md §3
REQUIRED_DEPENDENCIES = ["anthropic", "pydantic", "requests", "python-dotenv", "pandas", "pyyaml"]

# SPEC.md §5.1 — canonical Announcement fields, in order.
# "industry" was added in the deploy build (Phase 1, "descriptive morning brief")
# — SIC description from the source, where supplied; None where it isn't. It
# plays no part in compute_id's hash inputs, so idempotency is unaffected.
ANNOUNCEMENT_FIELDS = [
    "announcement_id",
    "exchange",
    "ticker",
    "company_name",
    "industry",
    "published_at",
    "headline",
    "doc_type",
    "native_doc_type",
    "native_id",
    "issuer_price_sensitive_flag",
    "body_text",
    "char_count",
    "truncated",
    "source_url",
    "fetched_at",
]

# SPEC.md §5.2 — model-returned fields, then runtime metadata appended by classify.py.
CLASSIFICATION_MODEL_FIELDS = [
    "announcement_id",
    "materiality",
    "confidence",
    "categories",
    "evidence_quote",
    "rationale",
    "entities",
    "previously_disclosed",
    "needs_human_review",
]
CLASSIFICATION_RUNTIME_FIELDS = [
    "model_id",
    "prompt_version",
    "input_tokens",
    "output_tokens",
    "cost_nzd",
    "latency_ms",
    "escalated",
    "guardrail_flags",
]

# SPEC.md §5.3 — fixed category enum. The model must not invent categories.
CATEGORIES = [
    "guidance_change",
    "earnings_result",
    "m_and_a",
    "capital_raise",
    "director_dealing",
    "contract_award",
    "operational_incident",
    "governance_change",
    "index_change",
    "regulatory",
    "admin",
]


def valid_announcement_kwargs() -> dict:
    return {
        "announcement_id": "a" * 64,
        "exchange": "EDGAR",
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "published_at": datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        "headline": "Results of Operations",
        "doc_type": "earnings_result",
        "native_doc_type": "8-K",
        "native_id": "0000320193-26-000001",
        "issuer_price_sensitive_flag": None,
        "body_text": "Some body text.",
        "char_count": 15,
        "truncated": False,
        "source_url": "https://www.sec.gov/Archives/edgar/data/320193/x.htm",
        "fetched_at": datetime(2026, 7, 1, 12, 5, tzinfo=timezone.utc),
    }


def valid_classification_kwargs() -> dict:
    return {
        "announcement_id": "a" * 64,
        "materiality": "material",
        "confidence": 0.87,
        "categories": ["guidance_change"],
        "evidence_quote": "revenue is expected to decline",
        "rationale": "Guidance was lowered.",
        "entities": {"amounts": ["$412m"], "counterparties": [], "effective_dates": ["2026-09-30"]},
        "previously_disclosed": False,
        "needs_human_review": False,
    }


def body(c: Check) -> None:
    # --- 1. Repository skeleton (SPEC.md §2) --------------------------------
    for rel in REQUIRED_FILES:
        c.require((ROOT / rel).is_file(), f"file exists: {rel}")
    for rel in REQUIRED_DIRS:
        c.require((ROOT / rel).is_dir(), f"directory exists: {rel}")

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for entry in [".env", "state.db", "data/raw/", "out/"]:
        c.require(entry in gitignore, f".gitignore covers {entry}")
    c.require(not (ROOT / ".env").is_file() or ".env" in gitignore, ".env is never committed")

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for dep in REQUIRED_DEPENDENCIES:
        c.require(dep.lower() in requirements, f"SPEC §3 dependency pinned: {dep}")

    # --- 2. config.yaml carries every tunable (SPEC.md §4) ------------------
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    c.require(isinstance(config, dict), "config.yaml parses to a mapping")

    for key in ["exchange", "watchlist", "models", "pricing_usd_per_mtok", "thresholds", "ranking"]:
        c.require(key in config, f"config.yaml has section: {key}")
    c.require("fx_usd_nzd" in config, "config.yaml has fx_usd_nzd")
    c.require("prompt_version" in config, "config.yaml has prompt_version")

    exchange = config["exchange"]
    for key in [
        "reference",
        "poll_interval_minutes",
        "request_timeout_seconds",
        "rate_limit_requests_per_second",
        "user_agent",
    ]:
        c.require(key in exchange, f"config.exchange has: {key}")
    c.require(exchange["reference"] in ("NZX", "ASX", "EDGAR"), "config.exchange.reference is a known exchange")
    c.require(
        exchange["rate_limit_requests_per_second"] > 0,
        "config.exchange.rate_limit_requests_per_second is positive",
    )
    c.require("@" in exchange["user_agent"], "config.exchange.user_agent carries a contact address")

    c.require(isinstance(config["watchlist"], list) and config["watchlist"], "watchlist is a non-empty list")
    c.require(
        all(isinstance(t, str) and t == t.upper() for t in config["watchlist"]),
        "every watchlist ticker is an uppercase string",
    )

    models = config["models"]
    for key in ["primary", "escalation", "temperature", "max_output_tokens"]:
        c.require(key in models, f"config.models has: {key}")
    c.equal(models["temperature"], 0.0, "config.models.temperature is 0.0 (deterministic)")

    thresholds = config["thresholds"]
    for key in [
        "confidence_floor",
        "escalate_below_confidence",
        "escalate_above_chars",
        "truncate_input_chars",
    ]:
        c.require(key in thresholds, f"config.thresholds has: {key}")

    weights = config["ranking"]["materiality_weight"]
    for key in ["material", "insufficient_info", "immaterial"]:
        c.require(key in weights, f"config.ranking.materiality_weight has: {key}")
    c.require("recency_half_life_hours" in config["ranking"], "config.ranking has recency_half_life_hours")

    for key in ["primary_input", "primary_output", "escalation_input", "escalation_output"]:
        c.require(key in config["pricing_usd_per_mtok"], f"config.pricing_usd_per_mtok has: {key}")

    # --- 3. Announcement contract (SPEC.md §5.1) ----------------------------
    from src.models import Announcement, Classification, Entities

    c.equal(list(Announcement.model_fields), ANNOUNCEMENT_FIELDS, "Announcement fields match SPEC §5.1 exactly")
    c.equal(
        set(typing.get_args(Announcement.model_fields["exchange"].annotation)),
        {"NZX", "ASX", "EDGAR"},
        "Announcement.exchange is Literal[NZX, ASX, EDGAR]",
    )

    ann = Announcement(**valid_announcement_kwargs())
    c.require(ann.published_at.tzinfo is not None, "Announcement.published_at is timezone-aware")

    # Required fields are required — no silent defaults (SPEC.md §0.7).
    for field in ANNOUNCEMENT_FIELDS:
        if field in ("issuer_price_sensitive_flag", "industry"):
            continue  # the two nullable fields (SPEC §5.1 / deploy-build: None where unsupplied)
        kwargs = valid_announcement_kwargs()
        del kwargs[field]
        c.raises(Exception, lambda k=kwargs: Announcement(**k), f"Announcement rejects missing {field}")

    c.require(
        Announcement(**{**valid_announcement_kwargs(), "issuer_price_sensitive_flag": None})
        .issuer_price_sensitive_flag
        is None,
        "Announcement.issuer_price_sensitive_flag accepts None (EDGAR supplies no flag)",
    )
    c.raises(
        Exception,
        lambda: Announcement(**{**valid_announcement_kwargs(), "unexpected_field": 1}),
        "Announcement rejects unknown fields",
    )
    c.raises(
        Exception,
        lambda: Announcement(**{**valid_announcement_kwargs(), "exchange": "LSE"}),
        "Announcement rejects an unknown exchange",
    )
    c.raises(
        Exception,
        lambda: Announcement(**{**valid_announcement_kwargs(), "doc_type": "not_a_category"}),
        "Announcement rejects a doc_type outside the canonical enum",
    )

    # --- 4. announcement_id hash (SPEC.md §5.1, amended v1.1) ---------------
    published = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    args = ("EDGAR", "AAPL", published, "Results of Operations", "0000320193-26-000001")
    expected = hashlib.sha256(
        f"EDGAR|AAPL|{published.isoformat()}|Results of Operations|0000320193-26-000001".encode("utf-8")
    ).hexdigest()
    got = Announcement.compute_id(*args)
    c.equal(got, expected, "compute_id is sha256 of exchange|ticker|iso|headline|native_id")
    c.equal(Announcement.compute_id(*args), got, "compute_id is deterministic across calls")
    c.require(
        Announcement.compute_id("EDGAR", "AAPL", published, "Results of Operations", "OTHER-ID") != got,
        "compute_id changes with native_id (same-second filings never collide)",
    )
    c.require(
        Announcement.compute_id("EDGAR", "MSFT", published, "Results of Operations", args[4]) != got,
        "compute_id changes with ticker",
    )
    c.equal(len(got), 64, "compute_id returns a 64-char sha256 hex digest")

    # --- 5. Classification contract (SPEC.md §5.2) --------------------------
    c.equal(
        list(Classification.model_fields),
        CLASSIFICATION_MODEL_FIELDS + CLASSIFICATION_RUNTIME_FIELDS,
        "Classification fields match SPEC §5.2 (model output + runtime metadata)",
    )
    c.equal(
        list(Entities.model_fields),
        ["amounts", "counterparties", "effective_dates"],
        "Entities fields match SPEC §5.2",
    )

    cls = Classification(**valid_classification_kwargs())
    c.equal(cls.guardrail_flags, [], "Classification.guardrail_flags defaults to empty")
    c.require(cls.model_id is None, "runtime metadata is unset until classify.py appends it")

    for field in CLASSIFICATION_MODEL_FIELDS:
        kwargs = valid_classification_kwargs()
        del kwargs[field]
        c.raises(Exception, lambda k=kwargs: Classification(**k), f"Classification rejects missing {field}")

    c.raises(
        Exception,
        lambda: Classification(**{**valid_classification_kwargs(), "materiality": "very_material"}),
        "Classification rejects a materiality outside the enum",
    )
    c.raises(
        Exception,
        lambda: Classification(**{**valid_classification_kwargs(), "categories": ["invented_category"]}),
        "Classification rejects an invented category",
    )
    c.raises(
        Exception,
        lambda: Classification(**{**valid_classification_kwargs(), "confidence": 1.4}),
        "Classification rejects confidence above 1.0",
    )
    c.raises(
        Exception,
        lambda: Classification(**{**valid_classification_kwargs(), "confidence": -0.1}),
        "Classification rejects confidence below 0.0",
    )
    c.raises(
        Exception,
        lambda: Classification(**{**valid_classification_kwargs(), "evidence_quote": "x" * 201}),
        "Classification rejects evidence_quote over 200 chars",
    )
    c.raises(
        Exception,
        lambda: Classification(**{**valid_classification_kwargs(), "rationale": "x" * 201}),
        "Classification rejects rationale over 200 chars",
    )

    # --- 6. Fixed vocabularies (SPEC.md §5.3) -------------------------------
    from src.models import Category, Materiality

    c.equal(list(typing.get_args(Category)), CATEGORIES, "Category enum matches SPEC §5.3 exactly, in order")
    c.equal(
        set(typing.get_args(Materiality)),
        {"material", "immaterial", "insufficient_info"},
        "Materiality enum matches SPEC §5.2",
    )
    for category in CATEGORIES:
        Classification(**{**valid_classification_kwargs(), "categories": [category]})
    c.note(f"all {len(CATEGORIES)} categories accepted by Classification")


if __name__ == "__main__":
    run("A1 skeleton + schemas", body)
