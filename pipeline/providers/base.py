"""LLM provider protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """A summarizing LLM provider.

    Implementations map the (text, system_prompt) pair onto their native API
    and return the model's text response (empty string on failure).
    """

    def summarize(self, text: str, system_prompt: str, max_tokens: int = 500) -> str:
        """Summarize `text` per `system_prompt`. Returns model output text."""
        ...
