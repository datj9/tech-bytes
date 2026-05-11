"""GitHub Trending — discover trending repos via GitHub Search API."""

import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from shared.rebuild import trigger_rebuild
from shared.utils import get_github_headers, summarize, today_str, upload_to_s3

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

S3_KEY = "gh-trending.json"

GITHUB_API = "https://api.github.com"
SEARCH_URL = f"{GITHUB_API}/search/repositories"

PER_PAGE = 15

SUMMARY_PROMPT = (
    "You are a technical writer for a developer newsletter. Given a GitHub repository's "
    "name, description, and README content, write a concise paragraph (2-3 sentences) "
    "explaining what the project does and why developers would find it interesting. "
    "Do not use markdown formatting."
)


def _date_n_days_ago(days: int) -> str:
    """Return a date string N days ago in YYYY-MM-DD format."""
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%d")


def _search_repos(created_after: str, per_page: int = PER_PAGE) -> list[dict[str, Any]]:
    """Search GitHub for repos created after a given date, sorted by stars."""
    params = {
        "q": f"created:>{created_after}",
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    }
    try:
        resp = requests.get(SEARCH_URL, headers=get_github_headers(), params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])
    except Exception:
        logger.exception("Failed to search repos (created_after=%s)", created_after)
        return []


def _fetch_readme(owner: str, repo: str) -> str:
    """Fetch the README content for a repo via GitHub API."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/readme"
    try:
        resp = requests.get(
            url,
            headers={**HEADERS, "Accept": "application/vnd.github.raw+json"},
            timeout=10,
        )
        if resp.status_code == 200:
            # Truncate to avoid excessive token usage
            return resp.text[:3000]
        return ""
    except Exception:
        logger.warning("Failed to fetch README for %s/%s", owner, repo)
        return ""


def _process_repo(repo: dict[str, Any]) -> dict[str, Any]:
    """Build a summary entry for a single repo."""
    full_name = repo.get("full_name", "")
    owner = repo.get("owner", {}).get("login", "")
    name = repo.get("name", "")
    description = repo.get("description", "") or ""
    stars = repo.get("stargazers_count", 0)
    language = repo.get("language", "")
    url = repo.get("html_url", "")
    created_at = repo.get("created_at", "")

    # Fetch README for richer context
    readme = _fetch_readme(owner, name)
    time.sleep(0.3)  # rate-limit

    # Build context for AI summarization
    context_parts = [
        f"Repository: {full_name}",
        f"Description: {description}",
    ]
    if language:
        context_parts.append(f"Language: {language}")
    if readme:
        context_parts.append(f"README (truncated):\n{readme}")

    context_text = "\n\n".join(context_parts)
    summary = summarize(context_text, SUMMARY_PROMPT, max_tokens=200)

    return {
        "name": full_name,
        "description": description,
        "url": url,
        "stars": stars,
        "language": language or "Unknown",
        "created_at": created_at,
        "summary": summary,
    }


def _process_repos(repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Process a list of repos into summary entries."""
    results: list[dict[str, Any]] = []
    for repo in repos:
        try:
            entry = _process_repo(repo)
            results.append(entry)
            time.sleep(0.5)  # respect rate limits
        except Exception:
            logger.exception(
                "Failed to process repo %s", repo.get("full_name", "?")
            )
            continue
    return results


def handler(event: Any = None, context: Any = None) -> dict[str, Any]:
    """Lambda handler — find trending GitHub repos, summarize, upload to S3."""
    logger.info("GitHub Trending starting")

    # Weekly trending
    weekly_date = _date_n_days_ago(7)
    logger.info("Fetching weekly trending (created after %s)", weekly_date)
    weekly_repos = _search_repos(weekly_date)
    weekly_results = _process_repos(weekly_repos)

    time.sleep(2)  # breathing room between search API calls

    # Monthly trending
    monthly_date = _date_n_days_ago(30)
    logger.info("Fetching monthly trending (created after %s)", monthly_date)
    monthly_repos = _search_repos(monthly_date)
    monthly_results = _process_repos(monthly_repos)

    output = {
        "generated_at": today_str(),
        "source": "github_search",
        "weekly": {
            "period": f"{weekly_date} to {today_str()}",
            "repos": weekly_results,
        },
        "monthly": {
            "period": f"{monthly_date} to {today_str()}",
            "repos": monthly_results,
        },
    }

    try:
        upload_to_s3(output, S3_KEY)
    except Exception:
        logger.exception("Failed to upload to S3")

    try:
        archive_key = f"data/archive/gh-trending/{today_str()}.json"
        upload_to_s3(output, archive_key)
    except Exception:
        logger.exception("Failed to upload archive copy to S3")

    trigger_rebuild()

    logger.info(
        "GitHub Trending complete — %d weekly, %d monthly repos",
        len(weekly_results),
        len(monthly_results),
    )
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
