"""OpenAI LLM provider."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIProvider:
    """OpenAI Chat Completions provider.

    The `openai` package is imported lazily so non-OpenAI users don't pay the
    install/import cost.
    """

    def __init__(self, llm_cfg: dict[str, Any]) -> None:
        from openai import OpenAI

        from pipeline.shared.secrets import resolve_secret

        api_key = resolve_secret("OPENAI_API_KEY", "OPENAI_KEY_SSM_PARAM")
        if not api_key:
            raise ValueError(
                "OpenAI provider selected but OPENAI_API_KEY is not set. "
                "Either set the env var or switch llm.provider in your config."
            )

        base_url = llm_cfg.get("base_url") or None
        self._client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        self._model = llm_cfg.get("model") or DEFAULT_MODEL

    def summarize(self, text: str, system_prompt: str, max_tokens: int = 500) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return response.choices[0].message.content or ""
        except Exception:
            logger.exception("OpenAI summarization failed")
            return ""
