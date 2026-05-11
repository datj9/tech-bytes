"""Hacker News Digest — fetch top stories, summarize, and upload to S3."""

import json
import logging
import sys
import time
from typing import Any

import requests

from shared.utils import summarize, today_str, upload_to_s3

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

S3_KEY = "hn-digest.json"

HN_API = "https://hacker-news.firebaseio.com/v0"
TOP_STORIES_URL = f"{HN_API}/topstories.json"
ITEM_URL = f"{HN_API}/item/{{id}}.json"

FETCH_COUNT = 30
TOP_N = 15
PAGE_FETCH_TIMEOUT = 10

SUMMARY_PROMPT = (
    "You are a technical writer for a developer newsletter. Given the title and "
    "content of a Hacker News story, write a concise 2-3 sentence summary that "
    "explains what the story is about and why developers would find it interesting. "
    "Do not use markdown formatting."
)


def _fetch_top_story_ids(count: int = FETCH_COUNT) -> list[int]:
    """Fetch the top story IDs from Hacker News."""
    try:
        resp = requests.get(TOP_STORIES_URL, timeout=10)
        resp.raise_for_status()
        ids = resp.json()
        return ids[:count]
    except Exception:
        logger.exception("Failed to fetch top stories")
        return []


def _fetch_story(story_id: int) -> dict[str, Any] | None:
    """Fetch a single story's details."""
    url = ITEM_URL.format(id=story_id)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("Failed to fetch story %d", story_id)
        return None


def _fetch_page_content(url: str) -> str:
    """Attempt to fetch the text content of a story URL."""
    try:
        resp = requests.get(
            url,
            timeout=PAGE_FETCH_TIMEOUT,
            headers={"User-Agent": "TechBytes-HNDigest/1.0"},
        )
        resp.raise_for_status()
        # Return raw text, truncated to avoid excessive token usage
        text = resp.text[:5000]
        return text
    except Exception:
        logger.warning("Failed to fetch page content from %s", url)
        return ""


def _summarize_story(story: dict[str, Any]) -> dict[str, Any]:
    """Build a summary for a single HN story."""
    title = story.get("title", "Untitled")
    url = story.get("url", "")
    score = story.get("score", 0)
    author = story.get("by", "unknown")
    story_id = story.get("id", 0)
    comments = story.get("descendants", 0)
    hn_url = f"https://news.ycombinator.com/item?id={story_id}"

    # Build context for the AI summary
    context_parts = [f"Title: {title}"]
    if url:
        context_parts.append(f"URL: {url}")
        page_content = _fetch_page_content(url)
        if page_content:
            context_parts.append(f"Page content (truncated):\n{page_content}")
        time.sleep(0.3)  # rate-limit page fetches

    context_text = "\n\n".join(context_parts)
    summary = summarize(context_text, SUMMARY_PROMPT, max_tokens=200)

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
    """Lambda handler — fetch top HN stories, summarize, upload to S3."""
    logger.info("HN Digest starting")

    # Fetch top story IDs
    story_ids = _fetch_top_story_ids(FETCH_COUNT)
    if not story_ids:
        logger.error("No story IDs fetched — aborting")
        return {"generated_at": today_str(), "source": "hacker_news", "stories": []}

    # Fetch story details
    stories: list[dict[str, Any]] = []
    for sid in story_ids:
        story = _fetch_story(sid)
        if story:
            stories.append(story)
        time.sleep(0.2)  # small delay between API calls

    # Sort by score descending and take top N
    stories.sort(key=lambda s: s.get("score", 0), reverse=True)
    top_stories = stories[:TOP_N]

    logger.info("Fetched %d stories, processing top %d", len(stories), len(top_stories))

    # Summarize each story
    results: list[dict[str, Any]] = []
    for story in top_stories:
        try:
            entry = _summarize_story(story)
            results.append(entry)
            time.sleep(0.5)  # respect OpenAI rate limits
        except Exception:
            logger.exception("Failed to summarize story: %s", story.get("title", "?"))
            continue

    output = {
        "generated_at": today_str(),
        "source": "hacker_news",
        "stories": results,
    }

    try:
        upload_to_s3(output, S3_KEY)
    except Exception:
        logger.exception("Failed to upload to S3")

    logger.info("HN Digest complete — processed %d stories", len(results))
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
