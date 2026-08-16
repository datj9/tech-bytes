"""Storage backend protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Storage(Protocol):
    """A read/write JSON storage backend.

    Keys are logical (e.g. "release-radar.json" or "data/release-radar.json").
    Backends normalize the key to their own namespace. `write_json` writes both
    a primary object and (optionally) an archived copy keyed by date.
    """

    def write_json(self, key: str, data: dict[str, Any], *, archive_slug: str | None = None) -> None:
        """Persist `data` at `key`. If `archive_slug` is given, also write a
        dated copy under `<archive_slug>/<YYYY-MM-DD>.json`."""
        ...

    def read_json(self, key: str) -> dict[str, Any]:
        """Read and parse JSON at `key`. Returns {} on any failure."""
        ...

    def list(self, prefix: str) -> list[str]:
        """List keys under `prefix`."""
        ...
