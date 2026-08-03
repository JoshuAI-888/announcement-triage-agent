"""config_schema.py — the runtime_config.json contract (Phase 0 of the deploy build).

`runtime_config.json` is the single, UI-editable source of truth the dashboard writes
and every runner reads. It is an OVERLAY on `config.yaml`: `apply_overrides()` merges it
onto the base config for `src.run` / the eval harness, so config.yaml stays the immutable
base and runtime_config carries the operator's live choices.

Three jobs live here, and both the Python runners AND the Node config UI must agree with
them (the Node side mirrors `config/runtime_config.schema.json`, generated from this model):
  1. validate — reject anything malformed BEFORE it is committed (pydantic, extra="forbid").
  2. NO GOLD FIELDS — a hard boundary. The configuration surface must never carry a gold
     label, slice tag, or a path into data/gold/. Prohibition #1 / stop-condition S4.
  3. eval fingerprint — a stable hash of everything that makes an eval valid (prompt +
     provider + model + pricing). When it drifts from the fingerprint in eval_summary.json,
     the dashboard's trust numbers are stale and must be re-earned by a re-eval.

Pure stdlib + pydantic (already a dependency). No new dependency (SPEC §3 unchanged).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_CONFIG_PATH = ROOT / "runtime_config.json"

Provider = Literal["claude", "openai", "glm"]
PromptVersion = Literal["v1", "v2", "v3", "custom"]
NewsMode = Literal["search", "resolved", "off"]
PollFrequency = Literal["daily", "hourly"]

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# --- the no-gold-field boundary (prohibition #1 / S4) ------------------------
# Any config key or string value matching these is refused at the boundary, so the
# configuration surface can never be used to smuggle in an owner label.
GOLD_FORBIDDEN_KEY = re.compile(r"(gold|label_|slice_tag|labeller|pass_number|difficulty)", re.I)
GOLD_FORBIDDEN_VALUE = re.compile(r"data[\\/]+gold", re.I)


class GoldFieldError(ValueError):
    """Raised when a runtime_config payload references gold labels/paths."""


def assert_no_gold_fields(raw: object, _path: str = "$") -> None:
    """Recursively refuse any key or value that reaches into the gold set."""
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(k, str) and GOLD_FORBIDDEN_KEY.search(k):
                raise GoldFieldError(f"forbidden gold-related key at {_path}.{k!r}")
            assert_no_gold_fields(v, f"{_path}.{k}")
    elif isinstance(raw, list):
        for i, v in enumerate(raw):
            assert_no_gold_fields(v, f"{_path}[{i}]")
    elif isinstance(raw, str):
        if GOLD_FORBIDDEN_VALUE.search(raw):
            raise GoldFieldError(f"forbidden gold path in value at {_path}: {raw!r}")


# --- the schema -------------------------------------------------------------

class RunCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Provider = "claude"
    prompt_version: PromptVersion = "v3"
    # When prompt_version == "custom", this holds the operator-edited classifier prompt.
    # Editing it changes the eval fingerprint → trust numbers go stale until a re-eval.
    classification_prompt_override: Optional[str] = Field(default=None, max_length=20000)


class EvalCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Provider = "claude"
    concurrency: int = Field(default=12, ge=1, le=32)


class ScheduleCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    poll_time_nzt: str = "06:00"
    poll_frequency: PollFrequency = "daily"
    intraday_alerts: bool = False

    @field_validator("poll_time_nzt")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("poll_time_nzt must be HH:MM (24h)")
        return v


class DraftCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    prompt: str = Field(max_length=8000)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        if not _EMAIL.match(v):
            raise ValueError("draft.email must be a valid email address")
        return v


class ThresholdsCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confidence_floor: float = Field(default=0.65, ge=0.0, le=1.0)
    escalate_below_confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    escalate_above_chars: int = Field(default=20000, ge=0)


class RankingCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recency_half_life_hours: float = Field(default=12.0, gt=0.0)
    materiality_weight: dict[str, float] = Field(
        default_factory=lambda: {"material": 1.0, "insufficient_info": 0.4, "immaterial": 0.0}
    )
    watchlist_weight_default: float = Field(default=1.0, ge=0.0)


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)  # bumped on every committed edit — optimistic concurrency + audit
    run: RunCfg = Field(default_factory=RunCfg)
    eval: EvalCfg = Field(default_factory=EvalCfg)
    schedule: ScheduleCfg
    draft: DraftCfg
    thresholds: ThresholdsCfg = Field(default_factory=ThresholdsCfg)
    ranking: RankingCfg = Field(default_factory=RankingCfg)
    watchlist: list[str] = Field(min_length=1)
    news_mode: NewsMode = "search"
    items_shown: int = Field(default=20, ge=1, le=100)
    theme: str = "milford"

    @field_validator("watchlist")
    @classmethod
    def _upper_unique(cls, v: list[str]) -> list[str]:
        if any(t != t.upper() for t in v):
            raise ValueError("watchlist tickers must be uppercase")
        if len(set(v)) != len(v):
            raise ValueError("watchlist has duplicate tickers")
        return v


# --- load / validate --------------------------------------------------------

def validate(raw: dict) -> RuntimeConfig:
    """Validate a payload: no gold fields, then full schema. Raises on any violation."""
    assert_no_gold_fields(raw)
    return RuntimeConfig.model_validate(raw)


def load_runtime_config(path: Path | None = None) -> RuntimeConfig:
    path = path or RUNTIME_CONFIG_PATH
    return validate(json.loads(path.read_text(encoding="utf-8")))


# --- overlay onto config.yaml ----------------------------------------------

def apply_overrides(base_config: dict, rc: RuntimeConfig) -> dict:
    """Return a NEW merged config: config.yaml base with runtime_config choices applied.

    Only the operator-editable surface is overlaid; everything else in config.yaml
    (adapter, pricing, doc_type map, normalise) is left untouched.
    """
    import copy

    cfg = copy.deepcopy(base_config)
    cfg["watchlist"] = list(rc.watchlist)
    cfg.setdefault("thresholds", {}).update({
        "confidence_floor": rc.thresholds.confidence_floor,
        "escalate_below_confidence": rc.thresholds.escalate_below_confidence,
        "escalate_above_chars": rc.thresholds.escalate_above_chars,
    })
    cfg.setdefault("ranking", {}).update({
        "recency_half_life_hours": rc.ranking.recency_half_life_hours,
        "materiality_weight": dict(rc.ranking.materiality_weight),
        "watchlist_weight_default": rc.ranking.watchlist_weight_default,
    })
    cfg.setdefault("eval", {})["concurrency"] = rc.eval.concurrency
    cfg["prompt_version"] = rc.run.prompt_version

    # Daily-run provider selection must actually take effect: swap the primary model id
    # AND its pricing to the chosen provider, so classify.py targets the right model and
    # costs it correctly (build_client alone only picks the client class). For a non-Claude
    # provider we also pin escalation to the same model — cross-provider escalation to a
    # Claude model through a non-Claude client is not supported.
    provider = rc.run.provider
    pconf = (cfg.get("providers", {}) or {}).get(provider, {})
    if pconf.get("model"):
        cfg.setdefault("models", {})["primary"] = pconf["model"]
        if provider != "claude":
            cfg["models"]["escalation"] = pconf["model"]
        pricing = pconf.get("pricing") or {}
        pm = cfg.setdefault("pricing_usd_per_mtok", {})
        if "input" in pricing:
            pm["primary_input"] = pricing["input"]
        if "output" in pricing:
            pm["primary_output"] = pricing["output"]

    cfg["_runtime"] = {
        "run_provider": rc.run.provider,
        "eval_provider": rc.eval.provider,
        "classification_prompt_override": rc.run.classification_prompt_override,
        "news_mode": rc.news_mode,
        "items_shown": rc.items_shown,
        "theme": rc.theme,
        "draft_email": rc.draft.email,
        "draft_prompt": rc.draft.prompt,
        "schedule": rc.schedule.model_dump(),
    }
    return cfg


# --- eval fingerprint (the trust-staleness signal) --------------------------

def fingerprint_from(prompt_version: str, prompt_override: str | None, provider: str,
                     base_config: dict) -> str:
    """Stable 16-hex hash of everything that makes an eval valid.

    Shared by `eval_fingerprint` (from a RuntimeConfig) and the eval harness (from its
    raw prompt_version/provider args), so both sides agree bit-for-bit. If this differs
    from the fingerprint stored in evals/eval_summary.json, the last eval no longer
    describes the configured system → the dashboard marks trust STALE.
    """
    pconf = (base_config.get("providers", {}) or {}).get(provider, {})
    override = prompt_override or ""
    material = {
        "prompt_version": prompt_version,
        "prompt_override_sha": hashlib.sha256(override.encode("utf-8")).hexdigest() if override else "",
        "provider": provider,
        "model": pconf.get("model"),
        "pricing": pconf.get("pricing"),
    }
    blob = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def eval_fingerprint(rc: RuntimeConfig, base_config: dict) -> str:
    """The eval fingerprint for the DAILY system: run.provider + run.prompt (+ override).

    Keyed on run.provider — the classifier the morning brief actually uses — NOT
    eval.provider, so switching the production provider flips the dashboard's trust
    to STALE until an eval re-measures that provider. A Run-eval whose evaluated
    provider matches run.provider stamps the same hash and clears the banner; one that
    measures a different provider leaves it stale (it didn't validate the daily system).
    """
    return fingerprint_from(rc.run.prompt_version, rc.run.classification_prompt_override,
                            rc.run.provider, base_config)
