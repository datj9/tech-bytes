"""Storage abstraction for pipeline output.

`get_storage()` picks a backend by $STORAGE:
- local (default) — writes JSON under data/ (the site's existing read path)
- s3              — writes to the bucket in $DATA_BUCKET_NAME (Lambda/CDK path)
"""

from __future__ import annotations

import os

from pipeline.storage.base import Storage
from pipeline.storage.local_fs import LocalFsStorage
from pipeline.storage.s3 import S3Storage


def get_storage() -> Storage:
    """Factory: pick a storage backend by $STORAGE (default: local)."""
    backend = (os.environ.get("STORAGE") or "local").lower()
    if backend == "s3":
        return S3Storage()
    return LocalFsStorage()


__all__ = ["LocalFsStorage", "S3Storage", "Storage", "get_storage"]
