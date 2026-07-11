"""Hacker News Digest — fetch top stories, summarize, write to storage.

Pipeline source (framework-agnostic). Run via `python -m pipeline.run hn_digest`.
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
from pipeline.shared.utils import emit_metric, setup_logging, today_str
from pipeline.storage import get_storage

setup_logging()
logger = logging.getLogger(__name__)

DATA_KEY = "data/hn-digest.json"
ARCHIVE_SLUG = "hn-digest"

HN_API = "https://hacker-news.firebaseio.com/v0"
TOP_STORIES_URL = f"{HN_API}/topstories.json"
ITEM_URL = f"{HN_API}/item/{{id}}.json"

DEFAULT_FETCH_COUNT = 30
DEFAULT_TOP_N = 15
PAGE_FETCH_TIMEOUT = 10

SUMMARY_PROMPT = (
    "You are a technical writer for a developer newsletter. Given the title and "
    "content of a Hacker News story, write a concise 2-3 sentence summary that "
    "explains what the story is about and why developers would find it interesting. "
    "Do not use markdown formatting."
)


def _fetch_top_story_ids(count: int) -> list[int]:
    try:
        resp = requests.get(TOP_STORIES_URL, timeout=10)
        resp.raise_for_status()
        return resp.json()[:count]
    except Exception:
        logger.exception("Failed to fetch top stories")
        return []


def _fetch_story(story_id: int) -> dict[str, Any] | None:
    try:
        resp = requests.get(ITEM_URL.format(id=story_id), timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("Failed to fetch story %d", story_id)
        return None


def _fetch_page_content(url: str) -> str:
    try:
        resp = requests.get(
            url,
            timeout=PAGE_FETCH_TIMEOUT,
            headers={"User-Agent": "TechBytes-HNDigest/1.0"},
        )
        resp.raise_for_status()
        return resp.text[:5000]
    except Exception:
        logger.warning("Failed to fetch page content from %s", url)
        return ""


def _summarize_story(story: dict[str, Any], provider: Any) -> dict[str, Any]:
    title = story.get("title", "Untitled")
    url = story.get("url", "")
    score = story.get("score", 0)
    author = story.get("by", "unknown")
    story_id = story.get("id", 0)
    comments = story.get("descendants", 0)
    hn_url = f"https://news.ycombinator.com/item?id={story_id}"

    context_parts = [f"Title: {title}"]
    if url:
        context_parts.append(f"URL: {url}")
        page_content = _fetch_page_content(url)
        if page_content:
            context_parts.append(f"Page content (truncated):\n{page_content}")
        time.sleep(0.3)

    context_text = "\n\n".join(context_parts)
    summary = provider.summarize(context_text, SUMMARY_PROMPT, max_tokens=200)

    return {
        "title": title,
        "url": url,
        "hn_url": hn_url,
        "score": score,
        "author": author,
        "comments": comments,
        "summary": summary,
    }


def handler(event: Any = None, context: Any = None) -> dict[str, Any]:
    """Fetch top HN stories, summarize, write to storage. Lambda-compatible."""
    logger.info("HN Digest starting")

    config = load_config()
    src_cfg = source_config(config, "hn_digest")
    fetch_count = int(src_cfg.get("fetch_count", DEFAULT_FETCH_COUNT))
    top_n = int(src_cfg.get("top_n", DEFAULT_TOP_N))

    story_ids = _fetch_top_story_ids(fetch_count)
    if not story_ids:
        logger.error("No story IDs fetched — aborting")
        return {"generated_at": today_str(), "source": "hacker_news", "stories": []}

    stories: list[dict[str, Any]] = []
    for sid in story_ids:
        story = _fetch_story(sid)
        if story:
            stories.append(story)
        time.sleep(0.2)

    stories.sort(key=lambda s: s.get("score", 0), reverse=True)
    top_stories = stories[:top_n]
    logger.info("Fetched %d stories, processing top %d", len(stories), len(top_stories))

    provider = get_provider(config)
    results: list[dict[str, Any]] = []
    for story in top_stories:
        try:
            results.append(_summarize_story(story, provider))
            time.sleep(0.5)
        except Exception:
            logger.exception("Failed to summarize story: %s", story.get("title", "?"))
            continue

    output = {"generated_at": today_str(), "source": "hacker_news", "stories": results}

    storage = get_storage()
    try:
        storage.write_json(DATA_KEY, output, archive_slug=ARCHIVE_SLUG)
    except Exception:
        logger.exception("Failed to write hn-digest data")

    trigger_rebuild()

    emit_metric("StoriesProcessed", len(results))
    emit_metric("LLMSummarizations", len(results))

    logger.info("HN Digest complete — processed %d stories", len(results))
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
