"""Trigger a GitHub Actions site rebuild after data update."""

import logging
import os

import requests

from shared.utils import _get_ssm_param

logger = logging.getLogger(__name__)


def _get_github_token() -> str:
    """Get GitHub token from env or SSM."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        ssm_param = os.environ.get("GITHUB_TOKEN_SSM_PARAM")
        if ssm_param:
            token = _get_ssm_param(ssm_param)
    return token or ""


def trigger_rebuild() -> bool:
    """Trigger the deploy workflow via GitHub Actions workflow_dispatch."""
    token = _get_github_token()
    if not token or token == "PLACEHOLDER":
        logger.warning("No GitHub token available -- skipping rebuild trigger")
        return False

    url = "https://api.github.com/repos/datj9/tech-bytes/actions/workflows/deploy.yml/dispatches"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        json={"ref": "master"},
        timeout=10,
    )
    if resp.status_code == 204:
        logger.info("Successfully triggered site rebuild")
        return True
    else:
        logger.error("Failed to trigger rebuild: %s %s", resp.status_code, resp.text)
        return False
