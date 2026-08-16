"""Config loader for Tech Bytes pipeline.

Single source of truth for: site branding, LLM provider selection, and source
definitions. Reads `config/techbytes.config.yml` (falls back to `.example`),
with env-var overrides for secrets and runtime selection.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config/techbytes.config.yml")
EXAMPLE_CONFIG_PATH = Path("config/techbytes.config.example.yml")

_VALID_PROVIDERS = {"openai", "anthropic", "local"}


def _find_config_file(explicit: Path | None) -> Path | None:
    """Locate the config file: explicit arg > env > default > example fallback."""
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    env_path = os.environ.get("TECHBYTES_CONFIG")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(DEFAULT_CONFIG_PATH)
    candidates.append(EXAMPLE_CONFIG_PATH)

    for path in candidates:
        resolved = path.resolve()
        if resolved.is_file():
            logger.info("Loaded config from %s", resolved)
            return resolved
    return None


def _apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """Apply env-var overrides for secrets and runtime provider selection."""
    llm = config.setdefault("llm", {})

    provider = os.environ.get("LLM_PROVIDER")
    if provider:
        llm["provider"] = provider

    model = os.environ.get("LLM_MODEL")
    if model:
        llm["model"] = model

    base_url = os.environ.get("LLM_BASE_URL")
    if base_url:
        llm["base_url"] = base_url

    return config


def _validate(config: dict[str, Any]) -> None:
    """Validate minimal config shape; raise ValueError with a clear message."""
    if not isinstance(config, dict):
        raise ValueError("Config root must be a mapping")

    llm = config.get("llm", {})
    provider = llm.get("provider", "openai")
    if provider not in _VALID_PROVIDERS:
        raise ValueError(
            f"llm.provider {provider!r} is invalid; must be one of {sorted(_VALID_PROVIDERS)}"
        )

    sources = config.get("sources", {})
    if not isinstance(sources, dict):
        raise ValueError("sources must be a mapping")

    for name, src_cfg in sources.items():
        if not isinstance(src_cfg, dict):
            raise ValueError(f"sources.{name} must be a mapping")


@lru_cache(maxsize=4)
def load_config(explicit_path: str | None = None) -> dict[str, Any]:
    """Load and validate the Tech Bytes config.

    Search order: explicit path arg > $TECHBYTES_CONFIG > config/techbytes.config.yml
    > config/techbytes.config.example.yml. Env vars override secrets and provider
    selection (LLM_PROVIDER, LLM_MODEL, LLM_BASE_URL).
    """
    path = _find_config_file(Path(explicit_path) if explicit_path else None)
    if path is None:
        raise FileNotFoundError(
            "No config found. Create config/techbytes.config.yml "
            "(see techbytes.config.example.yml for a full demo)."
        )

    with open(path, encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}

    config = _apply_env_overrides(config)
    _validate(config)
    return config


def source_config(config: dict[str, Any], name: str) -> dict[str, Any]:
    """Return a source's config sub-mapping (empty dict if absent/disabled)."""
    return config.get("sources", {}).get(name, {}) or {}


def is_source_enabled(config: dict[str, Any], name: str) -> bool:
    """Whether a source is enabled in config (defaults to False if absent)."""
    return bool(source_config(config, name).get("enabled", False))
