"""providers.py — one client interface over Claude, OpenAI and GLM (Zhipu).

Each provider exposes the SAME shape classify.py already expects: a client with
`.messages.create(model, max_tokens, temperature, system, messages)` returning an
object with `.content[0].text` and `.usage.input_tokens/.output_tokens`.

Claude is the native Anthropic client. OpenAI and GLM are adapted from the openai
SDK — GLM through an OpenAI-compatible `base_url`. Keeping the interface identical
means classify.py and every existing check stay unchanged; only the injected client
(and, via config, the model id + pricing) differ per provider.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

from dotenv import load_dotenv

from src.fetch import ROOT

load_dotenv(ROOT / ".env")


class _OpenAICompatClient:
    """Adapts the openai SDK (OpenAI or any OpenAI-compatible endpoint) to the
    anthropic-style `.messages.create` interface.

    Robust to the two ways newer models diverge: some reject a non-default
    `temperature`, and some require `max_completion_tokens` instead of
    `max_tokens`. We try the standard call and fall back on the specific 400s.
    """

    def __init__(self, api_key_env: str, base_url: str | None = None, extra_body: dict | None = None):
        from openai import OpenAI

        key = os.environ.get(api_key_env)
        if not key:
            raise RuntimeError(f"{api_key_env} is not set — add it to .env before running this provider")
        # High max_retries so the SDK rides out 429s (it honours Retry-After) instead
        # of surfacing them as failures under a tight tokens-per-minute cap.
        self._client = OpenAI(api_key=key, base_url=base_url or None, max_retries=8, timeout=120.0)
        # Provider-specific body params (e.g. GLM reasoning models need
        # {"thinking": {"type": "disabled"}} or they spend the whole token budget
        # thinking and return empty content).
        self._extra_body = extra_body or None
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, *, model, max_tokens, temperature, system, messages):
        oai_messages = [{"role": "system", "content": system}, *messages]
        kwargs = dict(model=model, messages=oai_messages, response_format={"type": "json_object"})
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body
        attempts = [
            {**kwargs, "max_tokens": max_tokens, "temperature": temperature},
            {**kwargs, "max_completion_tokens": max_tokens, "temperature": temperature},
            {**kwargs, "max_completion_tokens": max_tokens},  # model rejects temperature
        ]
        last: Exception | None = None
        for call_kwargs in attempts:
            try:
                resp = self._client.chat.completions.create(**call_kwargs)
                text = resp.choices[0].message.content
                return SimpleNamespace(
                    content=[SimpleNamespace(text=text)],
                    usage=SimpleNamespace(
                        input_tokens=resp.usage.prompt_tokens,
                        output_tokens=resp.usage.completion_tokens,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 — try the next param shape
                last = exc
                msg = str(exc).lower()
                if not any(t in msg for t in ("max_tokens", "max_completion_tokens", "temperature", "unsupported")):
                    raise
        raise last  # type: ignore[misc]


class _AnthropicCachingClient:
    """The native Anthropic client with prompt caching on the system prompt.

    The classifier re-sends an identical ~2.1k-token system prompt on every
    filing; without caching each call pays full input price for it. Marking the
    system block `cache_control: ephemeral` makes the first call a one-time cache
    write (1.25x) and every call within the 5-min window a cheap cache read
    (0.1x) — see classify._call, which folds those usage fields into the cost.

    NOTE: Anthropic only caches a block once it clears the model's minimum
    (2048 tokens for Haiku); classify_v3.md is ~2117, a thin margin — if that
    prompt is trimmed below 2048 the cache silently stops engaging on Haiku.

    Exposes the same `.messages.create(...)` shape classify.py expects, so the
    call site is unchanged; only the system arg is wrapped in a cached block.
    """

    def __init__(self):
        from anthropic import Anthropic

        self._client = Anthropic()
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, *, model, max_tokens, temperature, system, messages):
        return self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
        )


def provider_config(provider: str, config: dict) -> dict:
    pconf = (config.get("providers") or {}).get(provider)
    if pconf is None and provider == "claude":
        # Back-compat: Claude reads the top-level models/pricing blocks.
        return {
            "kind": "anthropic",
            "model": config["models"]["primary"],
            "pricing": {
                "input": config["pricing_usd_per_mtok"]["primary_input"],
                "output": config["pricing_usd_per_mtok"]["primary_output"],
            },
        }
    if pconf is None:
        raise ValueError(f"unknown provider {provider!r}; add it under `providers:` in config.yaml")
    return pconf


def build_client(provider: str, config: dict):
    pconf = provider_config(provider, config)
    kind = pconf.get("kind", "anthropic")
    if kind == "anthropic":
        return _AnthropicCachingClient()
    if kind == "openai":
        return _OpenAICompatClient(pconf.get("api_key_env", "OPENAI_API_KEY"),
                                   pconf.get("base_url"), pconf.get("extra_body"))
    raise ValueError(f"unknown provider kind {kind!r} for {provider!r}")
