"""GitHub Trending — discover trending repos by scraping github.com/trending.

Scrapes the public https://github.com/trending HTML (weekly + monthly), which is
the reliable source for real trending data. README enrichment is best-effort and
never required: if no GitHub token is configured (or the request fails), summaries
are still produced from the trending page's own name/description/language.
"""

import json
import logging
import re
import sys
import time
from typing import Any

import requests
from bs4 import BeautifulSoup

from shared.rebuild import trigger_rebuild
from shared.utils import (
    emit_metric,
    get_github_headers,
    setup_logging,
    summarize,
    today_str,
    upload_to_s3,
)

setup_logging()
logger = logging.getLogger(__name__)

S3_KEY = "data/gh-trending.json"

GITHUB_BASE = "https://github.com"
GITHUB_API = "https://api.github.com"
TRENDING_URL = f"{GITHUB_BASE}/trending"

USER_AGENT = "TechBytes-GHTrending/1.0 (+https://bytes.finaldivision.com)"
FETCH_TIMEOUT = 15
README_TIMEOUT = 10

SUMMARY_PROMPT = (
    "You are a technical writer for a developer newsletter. Given a GitHub repository's "
    "name, description, and README content, write a concise paragraph (2-3 sentences) "
    "explaining what the project does and why developers would find it interesting. "
    "Do not use markdown formatting."
)


def _fetch_trending(since: str) -> str:
    """Fetch the raw HTML of the GitHub trending page for a given period.

    `since` is one of "weekly" / "monthly" (also accepts "daily"). Returns the
    page HTML, or an empty string on any failure (logged, never raised).
    """
    try:
        resp = requests.get(
            TRENDING_URL,
            params={"since": since},
            headers={"User-Agent": USER_AGENT},
            timeout=FETCH_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.text
    except Exception:
        logger.exception("Failed to fetch trending page (since=%s)", since)
        return ""


def _first_int(text: str) -> int:
    """Extract the first integer (with optional thousands commas) from text."""
    match = re.search(r"[\d,]+", text)
    if not match:
        return 0
    try:
        return int(match.group(0).replace(",", ""))
    except ValueError:
        return 0


def _parse_trending(html: str) -> list[dict[str, Any]]:
    """Parse trending repo rows out of a github.com/trending HTML page.

    Returns a list of dicts with name/url/description/language/stars/
    stars_this_period. Missing optional fields default gracefully.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    repos: list[dict[str, Any]] = []

    for article in soup.select("article.Box-row"):
        heading = article.select_one("h2.lh-condensed a[href]")
        if heading is None:
            continue
        href = heading.get("href", "")
        if not href:
            continue

        name = href.strip("/")
        url = f"{GITHUB_BASE}{href}"

        description_el = article.select_one("p.col-9")
        description = description_el.get_text(strip=True) if description_el else ""

        language_el = article.select_one('[itemprop="programmingLanguage"]')
        language = language_el.get_text(strip=True) if language_el else ""

        stars = 0
        stars_link = article.select_one(f'a[href="{href}/stargazers"]')
        if stars_link is not None:
            stars = _first_int(stars_link.get_text())

        stars_this_period = 0
        for span in article.select("span.float-sm-right"):
            text = span.get_text(strip=True)
            if "stars this" in text or "star this" in text:
                stars_this_period = _first_int(text)
                break

        repos.append(
            {
                "name": name,
                "url": url,
                "description": description,
                "language": language,
                "stars": stars,
                "stars_this_period": stars_this_period,
            }
        )

    return repos


def _fetch_readme(owner: str, repo: str) -> str:
    """Fetch a repo's README via the GitHub API (best-effort).

    Returns the raw README text (truncated), or an empty string on any failure
    — including 401/403 when unauthenticated. Never raises.
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/readme"
    try:
        resp = requests.get(
            url,
            headers={**get_github_headers(), "Accept": "application/vnd.github.raw+json"},
            timeout=README_TIMEOUT,
        )
        if resp.status_code == 200:
            # Truncate to avoid excessive token usage
            return resp.text[:3000]
        return ""
    except Exception:
        logger.warning("Failed to fetch README for %s/%s", owner, repo)
        return ""


def _process_repo(repo: dict[str, Any]) -> dict[str, Any]:
    """Enrich a parsed repo with a best-effort README and an OpenAI summary."""
    name = repo.get("name", "")
    description = repo.get("description", "") or ""
    language = repo.get("language", "")

    # Best-effort README enrichment — works without a token, just returns "".
    readme = ""
    if "/" in name:
        owner, repo_name = name.split("/", 1)
        readme = _fetch_readme(owner, repo_name)
        time.sleep(0.3)  # be gentle with the GitHub API

    context_parts = [
        f"Repository: {name}",
        f"Description: {description}",
    ]
    if language:
        context_parts.append(f"Language: {language}")
    if readme:
        context_parts.append(f"README (truncated):\n{readme}")

    context_text = "\n\n".join(context_parts)
    summary = summarize(context_text, SUMMARY_PROMPT, max_tokens=200)

    return {
        "name": name,
        "url": repo.get("url", ""),
        "description": description,
        "language": language,
        "stars": repo.get("stars", 0),
        "stars_this_period": repo.get("stars_this_period", 0),
        "summary": summary,
    }


def _process_repos(repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich a list of parsed repos into final summary entries."""
    results: list[dict[str, Any]] = []
    for repo in repos:
        try:
            results.append(_process_repo(repo))
            time.sleep(0.5)  # respect OpenAI rate limits
        except Exception:
            logger.exception("Failed to process repo %s", repo.get("name", "?"))
            continue
    return results


def handler(event: Any = None, context: Any = None) -> dict[str, Any]:
    """Lambda handler — scrape GitHub trending, summarize, upload to S3."""
    logger.info("GitHub Trending starting")

    logger.info("Fetching weekly trending")
    weekly_repos = _parse_trending(_fetch_trending("weekly"))
    weekly_results = _process_repos(weekly_repos)

    time.sleep(2)  # breathing room between scrapes

    logger.info("Fetching monthly trending")
    monthly_repos = _parse_trending(_fetch_trending("monthly"))
    monthly_results = _process_repos(monthly_repos)

    total_repos = len(weekly_results) + len(monthly_results)
    # Each repo gets one summarize() call in _process_repo.
    openai_calls = total_repos

    output = {
        "updated_at": today_str(),
        "weekly": weekly_results,
        "monthly": monthly_results,
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
        archive_key = f"data/archive/gh-trending/{today_str()}.json"
        upload_to_s3(output, archive_key)
        s3_successes += 1
    except Exception:
        logger.exception("Failed to upload archive copy to S3")
        s3_failures += 1

    trigger_rebuild()

    # Emit custom metrics
    emit_metric("ReposProcessed", total_repos)
    emit_metric("OpenAISummarizations", openai_calls)
    emit_metric("S3UploadsSucceeded", s3_successes)
    emit_metric("S3UploadsFailed", s3_failures)

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
