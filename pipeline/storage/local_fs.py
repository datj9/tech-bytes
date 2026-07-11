"""Local filesystem storage backend (default).

Writes JSON files under `data/` relative to the repo root — the same path the
Astro site reads at build time.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _repo_root() -> Path:
    """Resolve the repo root: $DATA_DIR > walk up from cwd to find `data/` or `config/`."""
    env_dir = os.environ.get("DATA_DIR")
    if env_dir:
        return Path(env_dir).resolve()

    cwd = Path.cwd()
    for candidate in [cwd, *cwd.parents]:
        if (candidate / "data").is_dir() or (candidate / "config").is_dir():
            return candidate
    return cwd


def _normalize_key(key: str) -> str:
    """Strip a leading `data/` so callers can pass either shape."""
    if key.startswith("data/"):
        return key[len("data/"):]
    return key


class LocalFsStorage:
    """Default storage: writes JSON files under <repo>/data/."""

    def __init__(self) -> None:
        self._root = _repo_root() / "data"
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        rel = _normalize_key(key)
        path = (self._root / rel).resolve()
        # Guard against path traversal outside data/.
        if not str(path).startswith(str(self._root)):
            raise ValueError(f"Key {key!r} escapes the data/ root")
        return path

    def write_json(self, key: str, data: dict[str, Any], *, archive_slug: str | None = None) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Wrote %s (%d bytes)", path, path.stat().st_size)

        if archive_slug:
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            archive_key = f"archive/{archive_slug}/{today}.json"
            archive_path = self._path_for(archive_key)
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            archive_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("Wrote archive %s", archive_path)

    def read_json(self, key: str) -> dict[str, Any]:
        path = self._path_for(key)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.warning("No local file at %s", path)
            return {}
        except Exception:
            logger.exception("Failed to read %s", path)
            return {}

    def list(self, prefix: str) -> list[str]:
        rel = _normalize_key(prefix)
        search_dir = self._root / rel
        if not search_dir.is_dir():
            return []
        return [
            str(p.relative_to(self._root))
            for p in sorted(search_dir.rglob("*.json"))
        ]
