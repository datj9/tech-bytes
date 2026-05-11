"""Release Radar — track latest releases for key technologies via GitHub API."""

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import requests
import yaml

from shared.rebuild import trigger_rebuild
from shared.utils import get_github_headers, summarize, today_str, upload_to_s3

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

S3_KEY = "release-radar.json"

_CONFIG_FILENAME = "config/technologies.yml"


def _load_technologies() -> list[dict[str, str]]:
    """Load the technology list from config/technologies.yml.

    Search order:
    1. Project root (Lambda deploy package includes config/ at the root)
    2. Two levels up from this file (local dev: lambdas/release_radar/../../config/)
    """
    candidates = [
        Path(_CONFIG_FILENAME),
        Path(__file__).resolve().parent.parent.parent / _CONFIG_FILENAME,
    ]
    for path in candidates:
        resolved = path.resolve()
        if resolved.is_file():
            logger.info("Loading technologies from %s", resolved)
            with open(resolved, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            return data.get("technologies", [])

    logger.warning("No technologies config found, searched: %s", [str(p) for p in candidates])
    return []


SUMMARY_PROMPT = (
    "You are a technical writer. Summarize this software release into a short, "
    "clear paragraph (2-3 sentences). Focus on the most impactful changes for "
    "developers. Do not use markdown formatting."
)

DETAILS_PROMPT = (
    "You are a technical writer. Extract the key changes from this software release "
    "as a concise bullet-point list. Return only the bullet points (one per line, "
    "prefixed with '- '). Focus on the most developer-relevant changes. "
    "Maximum 5 bullet points."
)

GITHUB_API = "https://api.github.com"


def _fetch_releases(repo: str, count: int = 5) -> list[dict[str, Any]]:
    """Fetch the latest releases for a GitHub repo."""
    url = f"{GITHUB_API}/repos/{repo}/releases"
    try:
        resp = requests.get(url, headers=get_github_headers(), params={"per_page": count}, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("Failed to fetch releases for %s", repo)
        return []


def _process_release(release: dict[str, Any]) -> dict[str, Any]:
    """Summarize a single release using OpenAI."""
    tag = release.get("tag_name", "unknown")
    body = release.get("body", "") or ""
    name = release.get("name", tag)
    published = release.get("published_at", "")

    text_for_ai = f"Release: {name}\nTag: {tag}\n\n{body}"

    summary = summarize(text_for_ai, SUMMARY_PROMPT, max_tokens=200)
    details_raw = summarize(text_for_ai, DETAILS_PROMPT, max_tokens=300)
    details = [
        line.lstrip("- ").strip()
        for line in details_raw.strip().splitlines()
        if line.strip().startswith("-")
    ]

    return {
        "version": tag,
        "name": name,
        "published_at": published,
        "summary": summary,
        "details": details,
        "url": release.get("html_url", ""),
    }


def _process_technology(tech: dict[str, str]) -> dict[str, Any] | None:
    """Fetch and summarize releases for one technology."""
    name = tech["name"]
    repo = tech["repo"]
    category = tech.get("category", "Uncategorized")
    logger.info("Processing %s (%s) [%s]", name, repo, category)

    releases = _fetch_releases(repo)
    if not releases:
        logger.warning("No releases found for %s", name)
        return None

    processed: list[dict[str, Any]] = []
    for release in releases:
        try:
            processed.append(_process_release(release))
            time.sleep(0.5)  # respect rate limits
        except Exception:
            logger.exception(
                "Failed to process release %s for %s",
                release.get("tag_name", "?"),
                name,
            )
            continue

    return {
        "technology": name,
        "repo": repo,
        "category": category,
        "releases": processed,
    }


def handler(event: Any = None, context: Any = None) -> dict[str, Any]:
    """Lambda handler — fetch all technology releases, summarize, upload to S3."""
    logger.info("Release Radar starting")

    technologies = _load_technologies()
    if not technologies:
        logger.error("No technologies to process — check config/technologies.yml")
        return {"generated_at": today_str(), "source": "github_releases", "technologies": [], "categories": {}}

    results: list[dict[str, Any]] = []
    for tech in technologies:
        try:
            entry = _process_technology(tech)
            if entry:
                results.append(entry)
            time.sleep(1)  # breathing room between repos
        except Exception:
            logger.exception("Failed to process technology %s", tech["name"])
            continue

    # Build category grouping for the frontend
    categories: dict[str, list[dict[str, Any]]] = {}
    for entry in results:
        cat = entry.get("category", "Uncategorized")
        categories.setdefault(cat, []).append(entry)

    output = {
        "generated_at": today_str(),
        "source": "github_releases",
        "technologies": results,
        "categories": categories,
    }

    try:
        upload_to_s3(output, S3_KEY)
    except Exception:
        logger.exception("Failed to upload to S3")

    try:
        archive_key = f"data/archive/release-radar/{today_str()}.json"
        upload_to_s3(output, archive_key)
    except Exception:
        logger.exception("Failed to upload archive copy to S3")

    trigger_rebuild()

    logger.info("Release Radar complete — processed %d technologies", len(results))
    return output


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    result = handler()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0)
