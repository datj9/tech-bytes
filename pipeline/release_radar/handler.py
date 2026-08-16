"""Release Radar — track latest releases for tracked technologies via GitHub API.

Pipeline source (framework-agnostic). Run via `python -m pipeline.run release_radar`.
The Lambda entrypoint (`handler`) is preserved as a thin wrapper for the optional
AWS path.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from pipeline.providers import get_provider
from pipeline.shared.config import load_config, source_config
from pipeline.shared.rebuild import trigger_rebuild
from pipeline.shared.utils import emit_metric, get_github_headers, setup_logging, today_str
from pipeline.storage import get_storage

setup_logging()
logger = logging.getLogger(__name__)

DATA_KEY = "data/release-radar.json"
ARCHIVE_SLUG = "release-radar"

# A single delimiter lets us collapse the prose summary and the bullet details
# into ONE LLM call (see SUMMARY_PROMPT below) instead of two.
_DETAILS_DELIMITER = "---DETAILS---"

SUMMARY_PROMPT = (
    "You are a technical writer summarizing a software release for developers. "
    "Produce TWO sections separated by a line containing exactly '---DETAILS---'.\n"
    "Section 1 (before the delimiter): a short, clear prose summary of 2-3 sentences "
    "focusing on the most impactful changes. Do not use markdown.\n"
    "Section 2 (after the delimiter): a concise bullet-point list of the key changes, "
    "one per line, each prefixed with '- '. Maximum 5 bullets, most developer-relevant first."
)

GITHUB_API = "https://api.github.com"


def _load_technologies() -> list[dict[str, str]]:
    """Flatten the release_radar config into a list of items with category/icon.

    Returns dicts shaped {name, repo, category, icon} where `icon` is the emoji
    literal from the category config (the site reads it directly now).
    """
    config = load_config()
    src = source_config(config, "release_radar")
    items: list[dict[str, str]] = []
    for category in src.get("categories", []) or []:
        label = category.get("label", "Uncategorized")
        icon = category.get("icon", "📋")
        for item in category.get("items", []) or []:
            items.append(
                {
                    "name": item["name"],
                    "repo": item["repo"],
                    "category": label,
                    "icon": icon,
                }
            )
    return items


def _fetch_releases(repo: str, count: int = 3) -> list[dict[str, Any]]:
    """Fetch the latest releases for a GitHub repo (best-effort)."""
    url = f"{GITHUB_API}/repos/{repo}/releases"
    try:
        resp = requests.get(url, headers=get_github_headers(), params={"per_page": count}, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("Failed to fetch releases for %s", repo)
        return []


def _split_summary_details(raw: str) -> tuple[str, str]:
    """Split a combined LLM response into (prose summary, bullet details string).

    `details` is returned as a newline-joined STRING (one cleaned bullet per line),
    matching the site's `Release.details: string` contract — NOT a list.
    """
    if _DETAILS_DELIMITER in raw:
        summary_part, details_part = raw.split(_DETAILS_DELIMITER, 1)
    else:
        summary_part, details_part = raw, ""

    summary = summary_part.strip()
    bullets = [
        line.lstrip("-* ").strip()
        for line in details_part.strip().splitlines()
        if line.strip().lstrip("-* ").strip()
    ]
    details = "\n".join(f"- {b}" for b in bullets)
    return summary, details


def _process_release(release: dict[str, Any], provider: Any) -> dict[str, Any]:
    """Summarize a single release using ONE LLM call."""
    tag = release.get("tag_name", "unknown")
    body = release.get("body", "") or ""
    name = release.get("name", tag)
    published = release.get("published_at", "") or ""
    date = published.split("T", 1)[0] if published else ""

    text_for_ai = f"Release: {name}\nTag: {tag}\n\n{body}"
    raw = provider.summarize(text_for_ai, SUMMARY_PROMPT, max_tokens=400)
    summary, details = _split_summary_details(raw)

    return {
        "version": tag,
        "date": date,
        "summary": summary,
        "details": details,
    }


def _process_technology(tech: dict[str, str], provider: Any) -> dict[str, Any] | None:
    """Fetch releases for one technology and summarize ONLY the latest one.

    Returns a category-shaped dict for the frontend, or None if nothing usable.
    """
    name = tech["name"]
    repo = tech["repo"]
    category = tech.get("category", "Uncategorized")
    icon = tech.get("icon", "📋")
    logger.info("Processing %s (%s) [%s]", name, repo, category)

    releases = _fetch_releases(repo)
    if not releases:
        logger.warning("No releases found for %s", name)
        return None

    latest = next((r for r in releases if (r.get("body") or "").strip()), releases[0])

    try:
        processed = _process_release(latest, provider)
    except Exception:
        logger.exception("Failed to process release %s for %s", latest.get("tag_name", "?"), name)
        return None

    return {
        "name": name,
        "icon": icon,
        "category": category,
        "releases": [processed],
    }


def handler(event: Any = None, context: Any = None) -> dict[str, Any]:
    """Fetch each technology's latest release, summarize, write to storage.

    Lambda-compatible: `handler(event, context)`. Also called by `pipeline.run`.
    """
    logger.info("Release Radar starting")

    technologies = _load_technologies()
    if not technologies:
        logger.error("No technologies configured — check config/techbytes.config.yml")
        return {"updated_at": today_str(), "categories": []}

    provider = get_provider(load_config())
    categories: list[dict[str, Any]] = []
    llm_calls = 0

    for tech in technologies:
        try:
            entry = _process_technology(tech, provider)
            if entry:
                categories.append(entry)
                llm_calls += len(entry.get("releases", []))
            time.sleep(0.2)
        except Exception:
            logger.exception("Failed to process technology %s", tech["name"])
            continue

    output = {"updated_at": today_str(), "categories": categories}

    storage = get_storage()
    try:
        storage.write_json(DATA_KEY, output, archive_slug=ARCHIVE_SLUG)
    except Exception:
        logger.exception("Failed to write release-radar data")

    trigger_rebuild()

    emit_metric("TechnologiesProcessed", len(categories))
    emit_metric("LLMSummarizations", llm_calls)

    logger.info("Release Radar complete — processed %d technologies", len(categories))
    return output


if __name__ == "__main__":
    import json as _json
    import sys

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    result = handler()
    print(_json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0)
