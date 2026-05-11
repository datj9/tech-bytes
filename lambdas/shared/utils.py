"""Shared utilities for Tech Bytes Lambda functions."""

import json
import logging
import os
from datetime import datetime, timezone
from functools import lru_cache

import boto3
from openai import OpenAI

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"

_ssm_client = None


def _get_ssm_client():
    global _ssm_client
    if _ssm_client is None:
        _ssm_client = boto3.client("ssm")
    return _ssm_client


@lru_cache(maxsize=8)
def _get_ssm_param(param_name: str) -> str:
    """Read a parameter from SSM Parameter Store (cached per Lambda invocation)."""
    resp = _get_ssm_client().get_parameter(Name=param_name, WithDecryption=True)
    return resp["Parameter"]["Value"]


def get_openai_client() -> OpenAI:
    """Return an OpenAI client, reading the API key from SSM or env var."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        ssm_param = os.environ.get("OPENAI_KEY_SSM_PARAM")
        if ssm_param:
            api_key = _get_ssm_param(ssm_param)
    if not api_key:
        raise ValueError("No OpenAI API key found in env or SSM")
    return OpenAI(api_key=api_key)


def summarize(text: str, prompt: str, max_tokens: int = 500) -> str:
    """Call OpenAI gpt-4o-mini to summarize text with a given system prompt."""
    client = get_openai_client()
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return response.choices[0].message.content or ""
    except Exception:
        logger.exception("OpenAI summarization failed")
        return ""


def upload_to_s3(data: dict, key: str) -> None:
    """Upload a JSON dict to the S3 bucket specified by DATA_BUCKET_NAME."""
    bucket = os.environ.get("DATA_BUCKET_NAME")
    if not bucket:
        raise ValueError("DATA_BUCKET_NAME environment variable is not set")

    s3 = boto3.client("s3")
    body = json.dumps(data, indent=2, ensure_ascii=False)
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )
    logger.info("Uploaded %s to s3://%s/%s", key, bucket, key)


def get_github_headers() -> dict[str, str]:
    """Return GitHub API headers, including auth token if available."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        ssm_param = os.environ.get("GITHUB_TOKEN_SSM_PARAM")
        if ssm_param:
            try:
                token = _get_ssm_param(ssm_param)
            except Exception:
                logger.warning("Could not read GitHub token from SSM")
    if token and token != "PLACEHOLDER":
        headers["Authorization"] = f"Bearer {token}"
    return headers


def today_str() -> str:
    """Return today's date as YYYY-MM-DD in UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
