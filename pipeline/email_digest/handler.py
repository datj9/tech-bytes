"""Email Digest — weekly summary of Tech Bytes content via AWS SES.

This source is the most AWS-coupled: SES for sending, SSM for subscribers, and
reads from storage. It's disabled by default in the starter config. Enable only
on the AWS path (STORAGE=s3 + configured SES/SSM).

Pipeline source. Run via `python -m pipeline.run email_digest`.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from pipeline.providers import get_provider
from pipeline.shared.config import load_config
from pipeline.shared.utils import setup_logging, today_str
from pipeline.storage import get_storage

setup_logging()
logger = logging.getLogger(__name__)

# All configurable values read from env so forkers can set their own.
SENDER = os.environ.get("EMAIL_SENDER", "digest@example.com")
SUBSCRIBERS_SSM_PARAM = os.environ.get("SUBSCRIBERS_SSM_PARAM", "/tech-bytes/subscribers")
SITE_URL = os.environ.get("SITE_URL", "")
SITE_TITLE = os.environ.get("SITE_TITLE", "Tech Bytes")

DATA_KEYS = {
    "releases": "data/release-radar.json",
    "stories": "data/hn-digest.json",
    "repos": "data/gh-trending.json",
}

DIGEST_PROMPT = (
    "You are a technical writer for a developer newsletter. Given JSON data from "
    "three sources — release radar (software releases), Hacker News digest (top "
    "stories), and GitHub trending (trending repos) — write a 2-3 paragraph weekly "
    "summary that highlights the most interesting and impactful items across all "
    "three sources. Be concise, engaging, and developer-focused. Do not use markdown "
    "formatting. Write in plain text suitable for an email."
)


def _week_of_date() -> str:
    now = datetime.now(UTC)
    monday = now - timedelta(days=now.weekday())
    return monday.strftime("%B %d, %Y")


def _get_subscribers() -> list[str]:
    """Read subscriber list from SSM (comma-separated). AWS path only."""
    try:
        import boto3

        client = boto3.client("ssm")
        resp = client.get_parameter(Name=SUBSCRIBERS_SSM_PARAM, WithDecryption=True)
        raw = resp["Parameter"]["Value"]
        return [email.strip() for email in raw.split(",") if email.strip()]
    except Exception:
        logger.exception("Failed to read subscribers from SSM %s", SUBSCRIBERS_SSM_PARAM)
        return []


def _extract_top_releases(data: dict[str, Any], count: int = 3) -> list[dict[str, Any]]:
    """Extract top N releases across all categories."""
    releases: list[dict[str, Any]] = []
    for category in data.get("categories", []):
        cat_releases = category.get("releases", [])
        if cat_releases:
            latest = cat_releases[0]
            releases.append(
                {
                    "technology": category.get("name", "Unknown"),
                    "version": latest.get("version", ""),
                    "summary": latest.get("summary", ""),
                    "url": latest.get("url", ""),
                }
            )
    return releases[:count]


def _extract_top_stories(data: dict[str, Any], count: int = 5) -> list[dict[str, Any]]:
    stories = data.get("stories", [])
    sorted_stories = sorted(stories, key=lambda s: s.get("score", 0), reverse=True)
    return [
        {
            "title": s.get("title", ""),
            "url": s.get("url", "") or s.get("hn_url", ""),
            "hn_url": s.get("hn_url", ""),
            "score": s.get("score", 0),
            "summary": s.get("summary", ""),
        }
        for s in sorted_stories[:count]
    ]


def _extract_top_repos(data: dict[str, Any], count: int = 3) -> list[dict[str, Any]]:
    weekly_repos = data.get("weekly", [])
    sorted_repos = sorted(weekly_repos, key=lambda r: r.get("stars", 0), reverse=True)
    return [
        {
            "name": r.get("name", ""),
            "url": r.get("url", ""),
            "stars": r.get("stars", 0),
            "language": r.get("language", "Unknown"),
            "summary": r.get("summary", ""),
        }
        for r in sorted_repos[:count]
    ]


def _generate_ai_summary(
    provider: Any,
    releases: list[dict[str, Any]],
    stories: list[dict[str, Any]],
    repos: list[dict[str, Any]],
) -> str:
    import json

    combined = json.dumps(
        {"releases": releases, "hn_stories": stories, "trending_repos": repos},
        indent=2,
    )
    return provider.summarize(combined, DIGEST_PROMPT, max_tokens=600)


def _build_html(
    site_title: str,
    site_url: str,
    week_date: str,
    ai_summary: str,
    releases: list[dict[str, Any]],
    stories: list[dict[str, Any]],
    repos: list[dict[str, Any]],
) -> str:
    releases_html = ""
    for r in releases:
        url_tag = (
            f'<a href="{r["url"]}" style="color: #2563eb; text-decoration: none;">{r["version"]}</a>'
            if r.get("url")
            else r.get("version", "")
        )
        releases_html += f"""
        <tr>
          <td style="padding: 12px 16px; border-bottom: 1px solid #e5e7eb;">
            <strong style="color: #111827;">{r["technology"]}</strong> {url_tag}
            <br>
            <span style="color: #6b7280; font-size: 14px;">{r["summary"]}</span>
          </td>
        </tr>"""

    stories_html = ""
    for s in stories:
        stories_html += f"""
        <tr>
          <td style="padding: 12px 16px; border-bottom: 1px solid #e5e7eb;">
            <a href="{s["url"]}" style="color: #2563eb; text-decoration: none; font-weight: 600;">{s["title"]}</a>
            <span style="color: #9ca3af; font-size: 12px; margin-left: 8px;">{s["score"]} points</span>
            <br>
            <span style="color: #6b7280; font-size: 14px;">{s["summary"]}</span>
            <br>
            <a href="{s["hn_url"]}" style="color: #9ca3af; font-size: 12px; text-decoration: none;">Discussion</a>
          </td>
        </tr>"""

    repos_html = ""
    for r in repos:
        stars_formatted = f'{r["stars"]:,}'
        repos_html += f"""
        <tr>
          <td style="padding: 12px 16px; border-bottom: 1px solid #e5e7eb;">
            <a href="{r["url"]}" style="color: #2563eb; text-decoration: none; font-weight: 600;">{r["name"]}</a>
            <span style="color: #9ca3af; font-size: 12px; margin-left: 8px;">{stars_formatted} stars &middot; {r["language"]}</span>
            <br>
            <span style="color: #6b7280; font-size: 14px;">{r["summary"]}</span>
          </td>
        </tr>"""

    ai_summary_html = ai_summary.replace(
        "\n\n",
        '</p><p style="color: #374151; font-size: 15px; line-height: 1.6; margin: 0 0 16px;">',
    )

    footer_url_line = ""
    if site_url:
        footer_url_line = (
            f'<p style="margin: 0 0 8px; color: #6b7280; font-size: 13px;">'
            f'Read more at <a href="{site_url}" style="color: #2563eb; text-decoration: none;">{site_url}</a>'
            f"</p>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{site_title} Weekly - Week of {week_date}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
  <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color: #f3f4f6;">
    <tr>
      <td align="center" style="padding: 24px 16px;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="600" style="max-width: 600px; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">

          <tr>
            <td style="background: linear-gradient(135deg, #1e40af 0%, #7c3aed 100%); padding: 32px 24px; text-align: center;">
              <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 700; letter-spacing: -0.5px;">{site_title} Weekly</h1>
              <p style="margin: 8px 0 0; color: #c7d2fe; font-size: 15px;">Week of {week_date}</p>
            </td>
          </tr>

          <tr>
            <td style="padding: 24px;">
              <p style="color: #374151; font-size: 15px; line-height: 1.6; margin: 0 0 16px;">{ai_summary_html}</p>
            </td>
          </tr>

          <tr>
            <td style="padding: 0 24px;">
              <h2 style="margin: 0 0 12px; color: #111827; font-size: 20px; font-weight: 700; border-bottom: 2px solid #2563eb; padding-bottom: 8px;">Notable Releases</h2>
              <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                {releases_html}
              </table>
            </td>
          </tr>

          <tr><td style="padding: 12px;"></td></tr>

          <tr>
            <td style="padding: 0 24px;">
              <h2 style="margin: 0 0 12px; color: #111827; font-size: 20px; font-weight: 700; border-bottom: 2px solid #f59e0b; padding-bottom: 8px;">Top Hacker News Stories</h2>
              <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                {stories_html}
              </table>
            </td>
          </tr>

          <tr><td style="padding: 12px;"></td></tr>

          <tr>
            <td style="padding: 0 24px;">
              <h2 style="margin: 0 0 12px; color: #111827; font-size: 20px; font-weight: 700; border-bottom: 2px solid #10b981; padding-bottom: 8px;">Trending Repos</h2>
              <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                {repos_html}
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding: 32px 24px; background-color: #f9fafb; text-align: center; border-top: 1px solid #e5e7eb;">
              {footer_url_line}
              <p style="margin: 16px 0 0; color: #9ca3af; font-size: 12px;">
                You're receiving this because you subscribed to {site_title} Weekly.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _send_email(recipients: list[str], subject: str, html_body: str) -> None:
    """Send via SES. AWS path only."""
    import boto3

    ses = boto3.client("ses")
    for recipient in recipients:
        try:
            ses.send_email(
                Source=SENDER,
                Destination={"ToAddresses": [recipient]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": html_body, "Charset": "UTF-8"}},
                },
            )
            logger.info("Sent digest to %s", recipient)
        except Exception:
            logger.exception("Failed to send email to %s", recipient)


def handler(event: Any = None, context: Any = None) -> dict[str, Any]:
    """Build weekly digest and send via SES. Lambda-compatible."""
    logger.info("Email Digest starting")

    config = load_config()
    storage = get_storage()

    release_data = storage.read_json(DATA_KEYS["releases"])
    hn_data = storage.read_json(DATA_KEYS["stories"])
    gh_data = storage.read_json(DATA_KEYS["repos"])

    top_releases = _extract_top_releases(release_data, count=3)
    top_stories = _extract_top_stories(hn_data, count=5)
    top_repos = _extract_top_repos(gh_data, count=3)

    if not top_releases and not top_stories and not top_repos:
        logger.warning("No content available for digest — skipping")
        return {"status": "skipped", "message": "No content available"}

    provider = get_provider(config)
    ai_summary = _generate_ai_summary(provider, top_releases, top_stories, top_repos)

    week_date = _week_of_date()
    subject = f"{SITE_TITLE} Weekly — Week of {week_date}"
    html_body = _build_html(
        SITE_TITLE, SITE_URL, week_date, ai_summary, top_releases, top_stories, top_repos
    )

    subscribers = _get_subscribers()
    if not subscribers:
        logger.warning("No subscribers found — skipping send")
        return {
            "status": "no_subscribers",
            "message": "No subscribers configured",
            "generated_at": today_str(),
        }

    _send_email(subscribers, subject, html_body)

    logger.info(
        "Email Digest complete — sent to %d subscribers (%d releases, %d stories, %d repos)",
        len(subscribers),
        len(top_releases),
        len(top_stories),
        len(top_repos),
    )
    return {
        "status": "sent",
        "generated_at": today_str(),
        "recipients": len(subscribers),
        "releases": len(top_releases),
        "stories": len(top_stories),
        "repos": len(top_repos),
    }


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    import json

    result = handler()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0)
