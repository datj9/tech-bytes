"""LLM provider abstraction.

Providers implement a single `summarize(text, system_prompt, max_tokens)` method.
`get_provider(config)` picks one based on `llm.provider` in the config.

Supported providers:
- openai    — OpenAI API (gpt-4o-mini default). Key: $OPENAI_API_KEY
- anthropic — Anthropic API (claude-sonnet-4-6 default). Key: $ANTHROPIC_API_KEY
- local     — any OpenAI-compatible base_url (Ollama, LM Studio, Groq, OpenRouter).
              Key: $LLM_API_KEY (optional for local servers). base_url required.
"""

from __future__ import annotations

from typing import Any

from pipeline.providers.anthropic import AnthropicProvider
from pipeline.providers.base import LLMProvider
from pipeline.providers.local import LocalProvider
from pipeline.providers.openai import OpenAIProvider


def get_provider(config: dict[str, Any]) -> LLMProvider:
    """Factory: pick an LLM provider by `llm.provider` in config.

    Provider selection: config `llm.provider` (already env-overridden by the
    config loader if $LLM_PROVIDER was set).
    """
    llm_cfg = config.get("llm", {}) or {}
    provider_name = (llm_cfg.get("provider") or "openai").lower()

    if provider_name == "openai":
        return OpenAIProvider(llm_cfg)
    if provider_name == "anthropic":
        return AnthropicProvider(llm_cfg)
    if provider_name == "local":
        return LocalProvider(llm_cfg)

    raise ValueError(
        f"Unknown LLM provider {provider_name!r}; expected openai|anthropic|local"
    )


__all__ = [
    "AnthropicProvider",
    "LLMProvider",
    "LocalProvider",
    "OpenAIProvider",
    "get_provider",
]
