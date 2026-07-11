"""Shared utilities for Tech Bytes pipeline.

Cross-cutting concerns that don't belong to a specific source or abstraction:
- Structured JSON logging
- CloudWatch metric emission (no-op outside AWS)
- GitHub API header helper
- Date helper

LLM access lives in `pipeline.providers`; storage lives in `pipeline.storage`.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON for CloudWatch / log ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "function": record.funcName,
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)


def setup_logging() -> None:
    """Configure the root logger with JSON formatting."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Custom CloudWatch metrics (no-op outside AWS)
# ---------------------------------------------------------------------------

METRIC_NAMESPACE = "TechBytes"

# When True, metric emission is a no-op. We emit only when running on AWS Lambda
# (AWS_LAMBDA_FUNCTION_NAME set) OR when explicitly enabled ($TECHBYTES_EMIT_METRICS=1).
# This keeps boto3 unimported on the free local/GitHub Pages path.
_skip_metrics = (
    "AWS_LAMBDA_FUNCTION_NAME" not in os.environ
    and os.environ.get("TECHBYTES_EMIT_METRICS") != "1"
)


def emit_metric(name: str, value: float, unit: str = "Count") -> None:
    """Publish a custom metric to CloudWatch. No-op outside AWS."""
    if _skip_metrics:
        return
    try:
        import boto3

        client = boto3.client("cloudwatch")
        client.put_metric_data(
            Namespace=METRIC_NAMESPACE,
            MetricData=[{"MetricName": name, "Value": value, "Unit": unit}],
        )
    except Exception:
        logger.warning("Failed to emit metric %s=%s", name, value, exc_info=True)


# ---------------------------------------------------------------------------
# GitHub API helper
# ---------------------------------------------------------------------------

def get_github_headers() -> dict[str, str]:
    """Return GitHub API headers, including auth token if available.

    Token sources (first wins): $GITHUB_TOKEN, then SSM via $GITHUB_TOKEN_SSM_PARAM
    (AWS path only; boto3 imported lazily).
    """
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        ssm_param = os.environ.get("GITHUB_TOKEN_SSM_PARAM")
        if ssm_param:
            try:
                from pipeline.shared.secrets import _read_ssm

                token = _read_ssm(ssm_param)
            except Exception:
                logger.warning("Could not read GitHub token from SSM")
    if token and token != "PLACEHOLDER":
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ---------------------------------------------------------------------------
# Date helper
# ---------------------------------------------------------------------------

def today_str() -> str:
    """Return today's date as YYYY-MM-DD in UTC."""
    return datetime.now(UTC).strftime("%Y-%m-%d")
