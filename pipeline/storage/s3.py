"""S3 storage backend (AWS / Lambda path).

boto3 is imported lazily so the local path never needs it installed.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def _normalize_key(key: str) -> str:
    """Ensure keys live under the S3 `data/` prefix."""
    key = key.lstrip("/")
    if not key.startswith("data/"):
        key = f"data/{key}"
    return key


class S3Storage:
    """S3-backed storage. Requires $DATA_BUCKET_NAME."""

    def __init__(self) -> None:
        bucket = os.environ.get("DATA_BUCKET_NAME")
        if not bucket:
            raise ValueError(
                "S3 storage selected (STORAGE=s3) but DATA_BUCKET_NAME is not set."
            )
        self._bucket = bucket

    def _client(self):
        import boto3

        return boto3.client("s3")

    def write_json(self, key: str, data: dict[str, Any], *, archive_slug: str | None = None) -> None:
        s3 = self._client()
        full_key = _normalize_key(key)
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        s3.put_object(Bucket=self._bucket, Key=full_key, Body=body, ContentType="application/json")
        logger.info("Uploaded s3://%s/%s", self._bucket, full_key)

        if archive_slug:
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            archive_key = _normalize_key(f"archive/{archive_slug}/{today}.json")
            s3.put_object(
                Bucket=self._bucket, Key=archive_key, Body=body, ContentType="application/json"
            )
            logger.info("Uploaded archive s3://%s/%s", self._bucket, archive_key)

    def read_json(self, key: str) -> dict[str, Any]:
        s3 = self._client()
        full_key = _normalize_key(key)
        try:
            resp = s3.get_object(Bucket=self._bucket, Key=full_key)
            return json.loads(resp["Body"].read().decode("utf-8"))
        except Exception:
            logger.exception("Failed to read s3://%s/%s", self._bucket, full_key)
            return {}

    def list(self, prefix: str) -> list[str]:
        s3 = self._client()
        full_prefix = _normalize_key(prefix)
        if not full_prefix.endswith("/"):
            full_prefix += "/"
        paginator = s3.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self._bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys
