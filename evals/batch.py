"""batch.py — provider Batch APIs for the eval harness (≈50% cheaper, async).

Submits every gold item as one batch per provider, polls to completion, and returns
raw completions keyed by custom_id (= "{run}:{announcement_id}"). The harness then
parses + verifies each result exactly as in the live path. Escalation is adaptive
and cannot be batched, so batch runs are single-model.

Two backends behind one `.run(requests) -> {custom_id: BatchResult}` interface:
- AnthropicBatch      — Message Batches API (native SDK)
- OpenAICompatBatch   — the OpenAI Batch API (JSONL upload); also serves GLM via a
                        Zhipu base_url, if the endpoint implements /files + /batches
"""

from __future__ import annotations

import io
import json
import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class BatchResult:
    custom_id: str
    text: Optional[str]
    input_tokens: int
    output_tokens: int
    error: Optional[str] = None


def _log(msg: str) -> None:
    print(msg, flush=True)


class AnthropicBatch:
    def __init__(self, client=None):
        if client is None:
            from anthropic import Anthropic

            client = Anthropic()
        self.client = client

    def run(self, requests: list[dict], poll_interval: float = 10, timeout: float = 86400,
            log: Callable[[str], None] = _log) -> dict[str, BatchResult]:
        batch_reqs = [
            {
                "custom_id": r["custom_id"],
                "params": {
                    "model": r["model"], "max_tokens": r["max_tokens"], "temperature": r["temperature"],
                    "system": r["system"], "messages": [{"role": "user", "content": r["user"]}],
                },
            }
            for r in requests
        ]
        batch = self.client.messages.batches.create(requests=batch_reqs)
        log(f"anthropic batch {batch.id} submitted ({len(batch_reqs)} requests)")
        start = time.monotonic()
        while True:
            b = self.client.messages.batches.retrieve(batch.id)
            if b.processing_status == "ended":
                break
            if time.monotonic() - start > timeout:
                raise TimeoutError(f"anthropic batch {batch.id} timed out")
            time.sleep(poll_interval)
        out: dict[str, BatchResult] = {}
        for r in self.client.messages.batches.results(batch.id):
            cid = r.custom_id
            if r.result.type == "succeeded":
                msg = r.result.message
                out[cid] = BatchResult(cid, msg.content[0].text, msg.usage.input_tokens, msg.usage.output_tokens)
            else:
                out[cid] = BatchResult(cid, None, 0, 0, error=str(getattr(r.result, "error", r.result.type)))
        return out


class OpenAICompatBatch:
    def __init__(self, client, extra_body: dict | None = None):
        self.client = client  # a raw openai.OpenAI (not our _OpenAICompatClient wrapper)
        self.extra_body = extra_body

    def run(self, requests: list[dict], poll_interval: float = 10, timeout: float = 86400,
            log: Callable[[str], None] = _log) -> dict[str, BatchResult]:
        lines = []
        for r in requests:
            body = {
                "model": r["model"],
                "messages": [{"role": "system", "content": r["system"]}, {"role": "user", "content": r["user"]}],
                "max_tokens": r["max_tokens"], "temperature": r["temperature"],
                "response_format": {"type": "json_object"},
            }
            if r.get("extra_body"):
                body.update(r["extra_body"])
            lines.append(json.dumps({"custom_id": r["custom_id"], "method": "POST",
                                     "url": "/v1/chat/completions", "body": body}))
        buf = io.BytesIO(("\n".join(lines)).encode("utf-8"))
        buf.name = "batch.jsonl"
        f = self.client.files.create(file=buf, purpose="batch")
        batch = self.client.batches.create(input_file_id=f.id, endpoint="/v1/chat/completions",
                                            completion_window="24h")
        log(f"batch {batch.id} submitted ({len(lines)} requests)")
        start = time.monotonic()
        while True:
            b = self.client.batches.retrieve(batch.id)
            if b.status in ("completed", "failed", "expired", "cancelled"):
                break
            if time.monotonic() - start > timeout:
                raise TimeoutError(f"batch {batch.id} timed out")
            time.sleep(poll_interval)
        if b.status != "completed":
            raise RuntimeError(f"batch {b.id} ended with status {b.status}")
        content = self.client.files.content(b.output_file_id).read()
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        out: dict[str, BatchResult] = {}
        for line in content.splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            cid = rec["custom_id"]
            resp = rec.get("response") or {}
            if resp.get("status_code") == 200:
                bd = resp["body"]
                text = bd["choices"][0]["message"]["content"]
                us = bd["usage"]
                out[cid] = BatchResult(cid, text, us["prompt_tokens"], us["completion_tokens"])
            else:
                out[cid] = BatchResult(cid, None, 0, 0, error=json.dumps(rec.get("error") or resp)[:300])
        return out


def build_backend(provider: str, config: dict):
    from src.providers import provider_config

    pconf = provider_config(provider, config)
    kind = pconf.get("kind", "anthropic")
    if kind == "anthropic":
        return AnthropicBatch()
    if kind == "openai":
        import os

        from openai import OpenAI

        key = os.environ.get(pconf.get("api_key_env", "OPENAI_API_KEY"))
        if not key:
            raise RuntimeError(f"{pconf.get('api_key_env')} not set in .env")
        client = OpenAI(api_key=key, base_url=pconf.get("base_url") or None, max_retries=8, timeout=120.0)
        return OpenAICompatBatch(client, pconf.get("extra_body"))
    raise ValueError(f"no batch backend for provider kind {kind!r}")
