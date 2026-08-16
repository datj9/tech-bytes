"""GitHub Trending — discover trending repos by scraping github.com/trending.

Scrapes the public https://github.com/trending HTML (weekly + monthly). README
enrichment is best-effort and never required: if no GitHub token is configured,
summaries are still produced from the trending page's own name/description/language.

Pipeline source (framework-agnostic). Run via `python -m pipeline.run gh_trending`.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from bs4 import BeautifulSoup

from pipeline.providers import get_provider
from pipeline.shared.config import load_config
from pipeline.shared.rebuild import trigger_rebuild
from pipeline.shared.utils import emit_metric, get_github_headers, setup_logging, today_str
from pipeline.storage import get_storage

setup_logging()
logger = logging.getLogger(__name__)

DATA_KEY = "data/gh-trending.json"
ARCHIVE_SLUG = "gh-trending"

GITHUB_BASE = "https://github.com"
GITHUB_API = "https://api.github.com"
TRENDING_URL = f"{GITHUB_BASE}/trending"

USER_AGENT = "TechBytes-GHTrending/1.0"
FETCH_TIMEOUT = 15
README_TIMEOUT = 10

SUMMARY_PROMPT = (
    "You are a technical writer for a developer newsletter. Given a GitHub repository's "
    "name, description, and README content, write a concise paragraph (2-3 sentences) "
    "explaining what the project does and why developers would find it interesting. "
    "Do not use markdown formatting."
)


def _fetch_trending(since: str) -> str:
    """Fetch trending page HTML for `since` in {daily,weekly,monthly}."""
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
    import re

    match = re.search(r"[\d,]+", text)
    if not match:
        return 0
    try:
        return int(match.group(0).replace(",", ""))
    except ValueError:
        return 0


def _parse_trending(html: str) -> list[dict[str, Any]]:
    """Parse trending repo rows out of github.com/trending HTML."""
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
    """Fetch a repo's README via the GitHub API (best-effort)."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/readme"
    try:
        resp = requests.get(
            url,
            headers={**get_github_headers(), "Accept": "application/vnd.github.raw+json"},
            timeout=README_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.text[:3000]
        return ""
    except Exception:
        logger.warning("Failed to fetch README for %s/%s", owner, repo)
        return ""


def _process_repo(repo: dict[str, Any], provider: Any) -> dict[str, Any]:
    """Enrich a parsed repo with a best-effort README and an LLM summary."""
    name = repo.get("name", "")
    description = repo.get("description", "") or ""
    language = repo.get("language", "")

    readme = ""
    if "/" in name:
        owner, repo_name = name.split("/", 1)
        readme = _fetch_readme(owner, repo_name)
        time.sleep(0.3)

    context_parts = [f"Repository: {name}", f"Description: {description}"]
    if language:
        context_parts.append(f"Language: {language}")
    if readme:
        context_parts.append(f"README (truncated):\n{readme}")

    context_text = "\n\n".join(context_parts)
    summary = provider.summarize(context_text, SUMMARY_PROMPT, max_tokens=200)

    return {
        "name": name,
        "url": repo.get("url", ""),
        "description": description,
        "language": language,
        "stars": repo.get("stars", 0),
        "stars_this_period": repo.get("stars_this_period", 0),
        "summary": summary,
    }


def _process_repos(repos: list[dict[str, Any]], provider: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for repo in repos:
        try:
            results.append(_process_repo(repo, provider))
            time.sleep(0.5)
        except Exception:
            logger.exception("Failed to process repo %s", repo.get("name", "?"))
            continue
    return results


def handler(event: Any = None, context: Any = None) -> dict[str, Any]:
    """Scrape GitHub trending, summarize, write to storage. Lambda-compatible."""
    logger.info("GitHub Trending starting")

    provider = get_provider(load_config())

    logger.info("Fetching weekly trending")
    weekly_repos = _parse_trending(_fetch_trending("weekly"))
    weekly_results = _process_repos(weekly_repos, provider)

    time.sleep(2)

    logger.info("Fetching monthly trending")
    monthly_repos = _parse_trending(_fetch_trending("monthly"))
    monthly_results = _process_repos(monthly_repos, provider)

    total_repos = len(weekly_results) + len(monthly_results)

    output = {
        "updated_at": today_str(),
        "weekly": weekly_results,
        "monthly": monthly_results,
    }

    storage = get_storage()
    try:
        storage.write_json(DATA_KEY, output, archive_slug=ARCHIVE_SLUG)
    except Exception:
        logger.exception("Failed to write gh-trending data")

    trigger_rebuild()

    emit_metric("ReposProcessed", total_repos)
    emit_metric("LLMSummarizations", total_repos)

    logger.info(
        "GitHub Trending complete — %d weekly, %d monthly repos",
        len(weekly_results),
        len(monthly_results),
    )
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
