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
from shared.utils import emit_metric, get_github_headers, setup_logging, summarize, today_str, upload_to_s3

setup_logging()
logger = logging.getLogger(__name__)

S3_KEY = "data/release-radar.json"

_CONFIG_FILENAME = "config/technologies.yml"

# The site renders an entry's icon as:
#   categoryIcons[category.icon] ?? categoryIcons[category.name] ?? '📋'
# so `icon` must be a KEY string into index.astro's `categoryIcons` map, NOT an
# emoji literal. config/technologies.yml has no icon/slug field, so we map the
# techs that have a dedicated legacy icon key by name; everything else falls back
# to the category name (itself a valid key for all known categories).
# Valid legacy per-tech keys in categoryIcons: nodejs, react, go, python, rust,
# typescript, deno, bun.
TECH_ICON_KEYS: dict[str, str] = {
    "Node.js": "nodejs",
    "React": "react",
    "Go": "go",
    "Python": "python",
    "Rust": "rust",
    "TypeScript": "typescript",
    "Deno": "deno",
    "Bun": "bun",
}


def _icon_key(name: str, category: str) -> str:
    """Return the categoryIcons KEY string for an entry (never a raw emoji).

    Prefer a dedicated per-tech legacy key; otherwise fall back to the category
    name, which index.astro maps to a category emoji.
    """
    return TECH_ICON_KEYS.get(name, category)

# A single delimiter lets us collapse the prose summary and the bullet details
# into ONE OpenAI call (see SUMMARY_PROMPT below) instead of two.
_DETAILS_DELIMITER = "---DETAILS---"


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


# Bug 1 fix: a single prompt produces BOTH a prose summary and bullet details in
# one OpenAI call. The two sections are separated by _DETAILS_DELIMITER so we can
# split them deterministically. This halves the call count vs. two prompts, and
# combined with summarizing only the latest release per tech (see _process_technology)
# brings the total from ~220 calls down to ~22 — well under the 300s Lambda timeout.
SUMMARY_PROMPT = (
    "You are a technical writer summarizing a software release for developers. "
    "Produce TWO sections separated by a line containing exactly '---DETAILS---'.\n"
    "Section 1 (before the delimiter): a short, clear prose summary of 2-3 sentences "
    "focusing on the most impactful changes. Do not use markdown.\n"
    "Section 2 (after the delimiter): a concise bullet-point list of the key changes, "
    "one per line, each prefixed with '- '. Maximum 5 bullets, most developer-relevant first."
)

GITHUB_API = "https://api.github.com"


def _fetch_releases(repo: str, count: int = 3) -> list[dict[str, Any]]:
    """Fetch the latest releases for a GitHub repo.

    We fetch a few (default 3) as fallback so we can skip releases with an empty
    body, but only the newest non-empty one is summarized (see _process_technology).
    """
    url = f"{GITHUB_API}/repos/{repo}/releases"
    try:
        resp = requests.get(url, headers=get_github_headers(), params={"per_page": count}, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("Failed to fetch releases for %s", repo)
        return []


def _split_summary_details(raw: str) -> tuple[str, str]:
    """Split a combined OpenAI response into (prose summary, bullet details string).

    `details` is returned as a newline-joined STRING (one cleaned bullet per line),
    matching the site's `Release.details: string` contract — NOT a list.
    """
    if _DETAILS_DELIMITER in raw:
        summary_part, details_part = raw.split(_DETAILS_DELIMITER, 1)
    else:
        # No delimiter (model didn't comply) — treat the whole thing as the summary.
        summary_part, details_part = raw, ""

    summary = summary_part.strip()
    bullets = [
        line.lstrip("-* ").strip()
        for line in details_part.strip().splitlines()
        if line.strip().lstrip("-* ").strip()
    ]
    details = "\n".join(f"- {b}" for b in bullets)
    return summary, details


def _process_release(release: dict[str, Any]) -> dict[str, Any]:
    """Summarize a single release using ONE OpenAI call.

    Output keys match the site contract (site/src/pages/index.astro -> Release):
    version, date (from published_at), summary (string), details (string).
    """
    tag = release.get("tag_name", "unknown")
    body = release.get("body", "") or ""
    name = release.get("name", tag)
    published = release.get("published_at", "") or ""
    # Site expects a YYYY-MM-DD date; published_at is an ISO datetime.
    date = published.split("T", 1)[0] if published else ""

    text_for_ai = f"Release: {name}\nTag: {tag}\n\n{body}"
    raw = summarize(text_for_ai, SUMMARY_PROMPT, max_tokens=400)
    summary, details = _split_summary_details(raw)

    return {
        "version": tag,
        "date": date,
        "summary": summary,
        "details": details,
    }


def _process_technology(tech: dict[str, str]) -> dict[str, Any] | None:
    """Fetch releases for one technology and summarize ONLY the latest one.

    Bug 1 fix: a daily digest only needs the newest release per technology, so we
    summarize at most one. We still fetch a couple as fallback and pick the newest
    release that has a non-empty body (to avoid summarizing an empty changelog).
    Returns a category-shaped dict for the frontend, or None if nothing usable.
    """
    name = tech["name"]
    repo = tech["repo"]
    category = tech.get("category", "Uncategorized")
    logger.info("Processing %s (%s) [%s]", name, repo, category)

    releases = _fetch_releases(repo)
    if not releases:
        logger.warning("No releases found for %s", name)
        return None

    # Newest first from the API; prefer the latest release with a real body,
    # otherwise fall back to the very latest.
    latest = next((r for r in releases if (r.get("body") or "").strip()), releases[0])

    try:
        processed = _process_release(latest)
    except Exception:
        logger.exception("Failed to process release %s for %s", latest.get("tag_name", "?"), name)
        return None

    return {
        "name": name,
        "icon": _icon_key(name, category),
        "category": category,
        "releases": [processed],
    }


def handler(event: Any = None, context: Any = None) -> dict[str, Any]:
    """Lambda handler — fetch each technology's latest release, summarize, upload to S3."""
    logger.info("Release Radar starting")

    technologies = _load_technologies()
    if not technologies:
        logger.error("No technologies to process — check config/technologies.yml")
        return {"updated_at": today_str(), "categories": []}

    categories: list[dict[str, Any]] = []
    openai_calls = 0
    for tech in technologies:
        try:
            entry = _process_technology(tech)
            if entry:
                categories.append(entry)
                # One OpenAI call per summarized release (latest-only => 1 per tech).
                openai_calls += len(entry.get("releases", []))
            # Small breathing room between repos; with ~22 calls this is negligible.
            time.sleep(0.2)
        except Exception:
            logger.exception("Failed to process technology %s", tech["name"])
            continue

    output = {
        "updated_at": today_str(),
        "categories": categories,
    }

    s3_successes = 0
    s3_failures = 0

    try:
        upload_to_s3(output, S3_KEY)
        s3_successes += 1
    except Exception:
        logger.exception("Failed to upload to S3")
        s3_failures += 1

    try:
        archive_key = f"data/archive/release-radar/{today_str()}.json"
        upload_to_s3(output, archive_key)
        s3_successes += 1
    except Exception:
        logger.exception("Failed to upload archive copy to S3")
        s3_failures += 1

    trigger_rebuild()

    # Emit custom metrics
    emit_metric("TechnologiesProcessed", len(categories))
    emit_metric("OpenAISummarizations", openai_calls)
    emit_metric("S3UploadsSucceeded", s3_successes)
    emit_metric("S3UploadsFailed", s3_failures)

    logger.info("Release Radar complete — processed %d technologies", len(categories))
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
