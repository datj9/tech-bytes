"""Tests for the LLM provider factory and storage selector."""


import pytest

from pipeline.providers import get_provider
from pipeline.providers.anthropic import AnthropicProvider
from pipeline.providers.base import LLMProvider
from pipeline.providers.local import LocalProvider
from pipeline.providers.openai import OpenAIProvider
from pipeline.storage import LocalFsStorage, S3Storage, get_storage
from pipeline.storage.local_fs import _normalize_key as _norm_local

# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

def test_get_provider_openai(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    provider = get_provider({"llm": {"provider": "openai"}})
    assert isinstance(provider, OpenAIProvider)
    assert isinstance(provider, LLMProvider)


def test_get_provider_anthropic(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    provider = get_provider({"llm": {"provider": "anthropic"}})
    assert isinstance(provider, AnthropicProvider)


def test_get_provider_local(monkeypatch) -> None:
    provider = get_provider(
        {"llm": {"provider": "local", "base_url": "http://localhost:11434/v1", "model": "llama3"}}
    )
    assert isinstance(provider, LocalProvider)


def test_get_provider_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_provider({"llm": {"provider": "bedrock"}})


def test_openai_missing_key_raises(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        get_provider({"llm": {"provider": "openai"}})


def test_anthropic_default_model(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    provider = get_provider({"llm": {"provider": "anthropic"}})
    assert provider._model == "claude-sonnet-4-6"


def test_openai_default_model(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    provider = get_provider({"llm": {"provider": "openai"}})
    assert provider._model == "gpt-4o-mini"


def test_local_requires_base_url(monkeypatch) -> None:
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="base_url"):
        get_provider({"llm": {"provider": "local", "model": "llama3"}})


def test_local_requires_model() -> None:
    with pytest.raises(ValueError, match="model"):
        get_provider({"llm": {"provider": "local", "base_url": "http://x/v1"}})


# ---------------------------------------------------------------------------
# Storage factory
# ---------------------------------------------------------------------------

def test_get_storage_defaults_to_local(monkeypatch) -> None:
    monkeypatch.delenv("STORAGE", raising=False)
    storage = get_storage()
    assert isinstance(storage, LocalFsStorage)


def test_get_storage_explicit_local(monkeypatch) -> None:
    monkeypatch.setenv("STORAGE", "local")
    assert isinstance(get_storage(), LocalFsStorage)


def test_get_storage_s3_requires_bucket(monkeypatch) -> None:
    monkeypatch.setenv("STORAGE", "s3")
    monkeypatch.delenv("DATA_BUCKET_NAME", raising=False)
    with pytest.raises(ValueError, match="DATA_BUCKET_NAME"):
        get_storage()


def test_get_storage_s3(monkeypatch) -> None:
    monkeypatch.setenv("STORAGE", "s3")
    monkeypatch.setenv("DATA_BUCKET_NAME", "my-bucket")
    storage = get_storage()
    assert isinstance(storage, S3Storage)
    assert storage._bucket == "my-bucket"


# ---------------------------------------------------------------------------
# Local filesystem storage behaviour
# ---------------------------------------------------------------------------

def test_local_fs_write_and_read(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    storage = LocalFsStorage()
    storage.write_json("release-radar.json", {"updated_at": "2026-01-01", "categories": []})
    out = storage.read_json("release-radar.json")
    assert out["updated_at"] == "2026-01-01"


def test_local_fs_key_prefix_strip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    storage = LocalFsStorage()
    storage.write_json("data/release-radar.json", {"x": 1})
    # Both key shapes resolve to the same file.
    assert storage.read_json("release-radar.json") == {"x": 1}
    assert storage.read_json("data/release-radar.json") == {"x": 1}


def test_local_fs_archive(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    storage = LocalFsStorage()
    storage.write_json("hn-digest.json", {"stories": []}, archive_slug="hn-digest")
    # Main file exists.
    assert storage.read_json("hn-digest.json") == {"stories": []}
    # Archive dir has a dated file.
    archived = storage.list("archive/hn-digest")
    assert len(archived) == 1
    assert archived[0].endswith(".json")


def test_local_fs_read_missing_returns_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    storage = LocalFsStorage()
    assert storage.read_json("nope.json") == {}


def test_normalize_key_strips_data_prefix() -> None:
    assert _norm_local("data/release-radar.json") == "release-radar.json"
    assert _norm_local("release-radar.json") == "release-radar.json"
