"""AWS-only secret resolution.

On the free path, providers read API keys from env vars directly. On the AWS
path (STORAGE=s3), secrets live in SSM Parameter Store and the Lambda env only
holds the SSM parameter NAME. This module bridges the two: given an env var
name and the env var holding an SSM param name, return the secret value.

boto3 is imported lazily so the free path never needs it.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def _read_ssm(param_name: str) -> str:
    import boto3

    client = boto3.client("ssm")
    resp = client.get_parameter(Name=param_name, WithDecryption=True)
    return resp["Parameter"]["Value"]


def resolve_secret(env_name: str, ssm_env_name: str) -> str:
    """Resolve a secret: env var first, then SSM if the SSM param name is set."""
    value = os.environ.get(env_name)
    if value:
        return value

    ssm_param = os.environ.get(ssm_env_name)
    if not ssm_param:
        return ""

    try:
        return _read_ssm(ssm_param)
    except Exception:
        logger.warning("Could not read SSM parameter %s", ssm_param, exc_info=True)
        return ""
