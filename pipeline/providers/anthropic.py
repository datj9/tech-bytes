"""Anthropic LLM provider."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"


class AnthropicProvider:
    """Anthropic Messages API provider.

    The `anthropic` package is imported lazily so non-Anthropic users don't pay
    the install/import cost.
    """

    def __init__(self, llm_cfg: dict[str, Any]) -> None:
        from anthropic import Anthropic

        from pipeline.shared.secrets import resolve_secret

        api_key = resolve_secret("ANTHROPIC_API_KEY", "ANTHROPIC_KEY_SSM_PARAM")
        if not api_key:
            raise ValueError(
                "Anthropic provider selected but ANTHROPIC_API_KEY is not set. "
                "Either set the env var or switch llm.provider in your config."
            )

        base_url = llm_cfg.get("base_url") or None
        self._client = Anthropic(api_key=api_key, base_url=base_url) if base_url else Anthropic(api_key=api_key)
        self._model = llm_cfg.get("model") or DEFAULT_MODEL

    def summarize(self, text: str, system_prompt: str, max_tokens: int = 500) -> str:
        try:
            response = self._client.messages.create(
                model=self._model,
                system=system_prompt,
                messages=[{"role": "user", "content": text}],
                max_tokens=max_tokens,
                temperature=0.3,
            )
            # Anthropic returns content as a list of content blocks; join text blocks.
            parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
            return "".join(parts)
        except Exception:
            logger.exception("Anthropic summarization failed")
            return ""
