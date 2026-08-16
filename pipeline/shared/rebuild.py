"""Trigger a site rebuild after data update.

In the free path (GitHub Pages via Actions), this is a no-op — the same workflow
that runs the pipeline also builds and deploys the site, so there's nothing to
trigger.

In the AWS path (STORAGE=s3), we fire a GitHub Actions `workflow_dispatch` on
the repo identified by $GITHUB_REPOSITORY (defaults to no-op if unset). The repo
slug is read from env, never hardcoded.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _get_github_token() -> str:
    """GitHub token from env (SSM fallback is the caller's responsibility)."""
    token = os.environ.get("GITHUB_TOKEN") or ""
    if token == "PLACEHOLDER":
        return ""
    return token


def _is_aws_path() -> bool:
    return os.environ.get("STORAGE", "local").lower() == "s3"


def trigger_rebuild() -> bool:
    """Best-effort site rebuild trigger.

    - Free path (STORAGE != s3): no-op, returns True (nothing to trigger).
    - AWS path (STORAGE=s3) without repo/token: warns and returns False.
    - AWS path with repo+token: POSTs a workflow_dispatch.
    """
    if not _is_aws_path():
        logger.info("Free path — rebuild is handled by the same workflow; no-op.")
        return True

    repo = os.environ.get("GITHUB_REPOSITORY")
    token = _get_github_token()
    workflow = os.environ.get("REBUILD_WORKFLOW", "deploy-aws.yml")
    ref = os.environ.get("REBUILD_REF", "master")

    if not repo:
        logger.warning(
            "AWS path selected but GITHUB_REPOSITORY is unset — skipping rebuild trigger. "
            "Set GITHUB_REPOSITORY=owner/name to enable."
        )
        return False
    if not token:
        logger.warning("No GITHUB_TOKEN available — skipping rebuild trigger.")
        return False

    import requests

    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={"ref": ref},
        timeout=10,
    )
    if resp.status_code == 204:
        logger.info("Triggered rebuild on %s@%s (%s)", repo, ref, workflow)
        return True

    logger.error("Rebuild trigger failed: %s %s", resp.status_code, resp.text)
    return False
