"""Local / OpenAI-compatible LLM provider.

Use this for any server that speaks the OpenAI Chat Completions API:
- Ollama        (http://localhost:11434/v1)
- LM Studio     (http://localhost:1234/v1)
- Groq          (https://api.groq.com/openai/v1)
- OpenRouter    (https://openrouter.ai/api/v1)

Set `llm.base_url` in config or $LLM_BASE_URL. Set `llm.model` to whatever
model the server serves. $LLM_API_KEY is optional (local servers often don't
need one; pass any non-empty value if the client requires it).
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class LocalProvider:
    """OpenAI-compatible provider pointed at a configurable base_url."""

    def __init__(self, llm_cfg: dict[str, Any]) -> None:
        from openai import OpenAI

        base_url = llm_cfg.get("base_url") or os.environ.get("LLM_BASE_URL")
        if not base_url:
            raise ValueError(
                "Local provider requires llm.base_url (or $LLM_BASE_URL). "
                "Point it at your OpenAI-compatible server, e.g. http://localhost:11434/v1"
            )

        model = llm_cfg.get("model")
        if not model:
            raise ValueError(
                "Local provider requires llm.model (the model name your server serves)."
            )

        # Many local servers don't need a key, but the OpenAI client wants a non-empty string.
        api_key = os.environ.get("LLM_API_KEY") or "local"
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

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
            logger.exception("Local provider summarization failed")
            return ""
