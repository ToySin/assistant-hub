"""Provider-agnostic LLM client for structured-extraction prompts.

The default is the Anthropic SDK so existing setups keep working with
just an `ANTHROPIC_API_KEY`. To point enrichment at a different model
host — local Ollama, a remote GPU box, OpenAI itself, OpenRouter, etc. —
set `ASSISTHUB_ENRICHMENT_PROVIDER=openai_compatible` and supply a
`ASSISTHUB_ENRICHMENT_BASE_URL`. Most local model servers (Ollama,
vLLM, llama.cpp) speak the OpenAI Chat Completions API on `/v1`.

Environment variables (all read at `get_client()` time):

  ASSISTHUB_ENRICHMENT_PROVIDER       anthropic | openai_compatible
                                      (default: anthropic)
  ASSISTHUB_ENRICHMENT_MODEL          model id (provider-specific).
                                      Default for anthropic:
                                      claude-haiku-4-5-20251001.
                                      Required for openai_compatible.
  ASSISTHUB_ENRICHMENT_BASE_URL       endpoint override
                                      (e.g. http://192.168.1.42:11434/v1
                                      for a remote Ollama box).
                                      Ignored by the anthropic provider.
  ASSISTHUB_ENRICHMENT_API_KEY_ENV    name of the env var holding the
                                      credential (default: provider's
                                      conventional one — ANTHROPIC_API_KEY
                                      for anthropic, OPENAI_API_KEY for
                                      openai_compatible). For local
                                      Ollama where no key is required,
                                      leave it unset; the client will
                                      send a placeholder.

Callers receive an object with `.ask(system, user, max_tokens) -> str`
and `.label() -> str` (used as `extracted_by` in graph provenance).
"""

from __future__ import annotations

import os
from typing import Protocol

DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"


class LLMClient(Protocol):
    def ask(self, system: str, user: str, max_tokens: int = 2048) -> str: ...
    def label(self) -> str: ...


def get_client() -> LLMClient:
    provider = os.environ.get("ASSISTHUB_ENRICHMENT_PROVIDER", "anthropic").strip().lower()

    if provider == "anthropic":
        return _make_anthropic()
    if provider in ("openai", "openai_compatible"):
        return _make_openai_compatible()
    raise RuntimeError(
        f"unknown ASSISTHUB_ENRICHMENT_PROVIDER='{provider}'. "
        "Use 'anthropic' or 'openai_compatible'."
    )


def _make_anthropic() -> "_AnthropicClient":
    model = os.environ.get("ASSISTHUB_ENRICHMENT_MODEL") or DEFAULT_ANTHROPIC_MODEL
    key_env = os.environ.get("ASSISTHUB_ENRICHMENT_API_KEY_ENV") or "ANTHROPIC_API_KEY"
    api_key = os.environ.get(key_env)
    if not api_key:
        raise RuntimeError(
            f"{key_env} is not set. Add it to the workspace's .env "
            "or export it in your shell."
        )
    return _AnthropicClient(api_key=api_key, model=model)


def _make_openai_compatible() -> "_OpenAICompatibleClient":
    model = os.environ.get("ASSISTHUB_ENRICHMENT_MODEL")
    if not model:
        raise RuntimeError(
            "ASSISTHUB_ENRICHMENT_MODEL is required when using "
            "ASSISTHUB_ENRICHMENT_PROVIDER=openai_compatible."
        )
    base_url = os.environ.get("ASSISTHUB_ENRICHMENT_BASE_URL") or None
    key_env = os.environ.get("ASSISTHUB_ENRICHMENT_API_KEY_ENV")
    if key_env:
        api_key = os.environ.get(key_env)
    else:
        api_key = os.environ.get("OPENAI_API_KEY")
    # Local model servers (Ollama, llama.cpp) ignore the API key but
    # the OpenAI SDK refuses an empty string. Send a placeholder.
    if not api_key:
        api_key = "local"
    return _OpenAICompatibleClient(api_key=api_key, model=model, base_url=base_url)


class _AnthropicClient:
    def __init__(self, api_key: str, model: str) -> None:
        from anthropic import Anthropic  # imported lazily so non-anthropic users don't need the SDK
        self._client = Anthropic(api_key=api_key)
        self._model = model

    def ask(self, system: str, user: str, max_tokens: int = 2048) -> str:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text.strip()

    def label(self) -> str:
        return f"anthropic/{self._model}"


class _OpenAICompatibleClient:
    def __init__(self, api_key: str, model: str, base_url: str | None) -> None:
        from openai import OpenAI  # imported lazily
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._model = model
        self._base_url = base_url

    def ask(self, system: str, user: str, max_tokens: int = 2048) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip()

    def label(self) -> str:
        host = ""
        if self._base_url:
            host = self._base_url.rstrip("/").split("//", 1)[-1]
            host = host.split("/")[0] + ":"
        return f"openai_compatible/{host}{self._model}"
