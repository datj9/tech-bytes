"""Email Digest — weekly summary of Tech Bytes content via AWS SES."""

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3

from shared.utils import get_openai_client, today_str, MODEL, _get_ssm_param

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SENDER = "digest@bytes.finaldivision.com"
SUBSCRIBERS_SSM_PARAM = "/tech-bytes/subscribers"
SITE_URL = "https://bytes.finaldivision.com"

S3_DATA_KEYS = [
    "data/release-radar.json",
    "data/hn-digest.json",
    "data/gh-trending.json",
]

DIGEST_PROMPT = (
    "You are a technical writer for a developer newsletter called Tech Bytes Weekly. "
    "Given JSON data from three sources — release radar (software releases), "
    "Hacker News digest (top stories), and GitHub trending (trending repos) — write "
    "a 2-3 paragraph weekly summary that highlights the most interesting and impactful "
    "items across all three sources. Be concise, engaging, and developer-focused. "
    "Do not use markdown formatting. Write in plain text suitable for an email."
)


def _week_of_date() -> str:
    """Return the Monday of the current week as a formatted date string."""
    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.strftime("%B %d, %Y")


def _read_s3_json(bucket: str, key: str) -> dict[str, Any]:
    """Read and parse a JSON file from S3."""
    s3 = boto3.client("s3")
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(resp["Body"].read().decode("utf-8"))
    except Exception:
        logger.exception("Failed to read s3://%s/%s", bucket, key)
        return {}


def _get_subscribers() -> list[str]:
    """Read the subscriber list from SSM parameter (comma-separated emails)."""
    try:
        raw = _get_ssm_param(SUBSCRIBERS_SSM_PARAM)
        return [email.strip() for email in raw.split(",") if email.strip()]
    except Exception:
        logger.exception("Failed to read subscribers from SSM")
        return []


def _extract_top_releases(data: dict[str, Any], count: int = 3) -> list[dict[str, str]]:
    """Extract the top N most notable releases from release radar data."""
    releases: list[dict[str, str]] = []
    for tech in data.get("technologies", []):
        tech_releases = tech.get("releases", [])
        if tech_releases:
            latest = tech_releases[0]
            releases.append({
                "technology": tech.get("technology", "Unknown"),
                "version": latest.get("version", ""),
                "summary": latest.get("summary", ""),
                "url": latest.get("url", ""),
            })
    return releases[:count]


def _extract_top_stories(data: dict[str, Any], count: int = 5) -> list[dict[str, Any]]:
    """Extract the top N HN stories by score."""
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
    """Extract the top N trending repos from weekly data."""
    weekly_repos = data.get("weekly", {}).get("repos", [])
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
    releases: list[dict[str, str]],
    stories: list[dict[str, Any]],
    repos: list[dict[str, Any]],
) -> str:
    """Use OpenAI to generate a cohesive weekly summary."""
    combined = json.dumps(
        {"releases": releases, "hn_stories": stories, "trending_repos": repos},
        indent=2,
    )
    client = get_openai_client()
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": DIGEST_PROMPT},
                {"role": "user", "content": combined},
            ],
            max_tokens=600,
            temperature=0.4,
        )
        return response.choices[0].message.content or ""
    except Exception:
        logger.exception("OpenAI digest summary failed")
        return ""


def _build_html(
    week_date: str,
    ai_summary: str,
    releases: list[dict[str, str]],
    stories: list[dict[str, Any]],
    repos: list[dict[str, Any]],
) -> str:
    """Build the HTML email body with inline CSS."""
    releases_html = ""
    for r in releases:
        url_tag = f'<a href="{r["url"]}" style="color: #2563eb; text-decoration: none;">{r["version"]}</a>' if r["url"] else r["version"]
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

    ai_summary_html = ai_summary.replace("\n\n", "</p><p style=\"color: #374151; font-size: 15px; line-height: 1.6; margin: 0 0 16px;\">")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Tech Bytes Weekly - Week of {week_date}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
  <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color: #f3f4f6;">
    <tr>
      <td align="center" style="padding: 24px 16px;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="600" style="max-width: 600px; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">

          <!-- Header -->
          <tr>
            <td style="background: linear-gradient(135deg, #1e40af 0%, #7c3aed 100%); padding: 32px 24px; text-align: center;">
              <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 700; letter-spacing: -0.5px;">Tech Bytes Weekly</h1>
              <p style="margin: 8px 0 0; color: #c7d2fe; font-size: 15px;">Week of {week_date}</p>
            </td>
          </tr>

          <!-- AI Summary -->
          <tr>
            <td style="padding: 24px;">
              <p style="color: #374151; font-size: 15px; line-height: 1.6; margin: 0 0 16px;">{ai_summary_html}</p>
            </td>
          </tr>

          <!-- Notable Releases -->
          <tr>
            <td style="padding: 0 24px;">
              <h2 style="margin: 0 0 12px; color: #111827; font-size: 20px; font-weight: 700; border-bottom: 2px solid #2563eb; padding-bottom: 8px;">Notable Releases</h2>
              <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                {releases_html}
              </table>
            </td>
          </tr>

          <!-- Spacer -->
          <tr><td style="padding: 12px;"></td></tr>

          <!-- Top HN Stories -->
          <tr>
            <td style="padding: 0 24px;">
              <h2 style="margin: 0 0 12px; color: #111827; font-size: 20px; font-weight: 700; border-bottom: 2px solid #f59e0b; padding-bottom: 8px;">Top Hacker News Stories</h2>
              <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                {stories_html}
              </table>
            </td>
          </tr>

          <!-- Spacer -->
          <tr><td style="padding: 12px;"></td></tr>

          <!-- Trending Repos -->
          <tr>
            <td style="padding: 0 24px;">
              <h2 style="margin: 0 0 12px; color: #111827; font-size: 20px; font-weight: 700; border-bottom: 2px solid #10b981; padding-bottom: 8px;">Trending Repos</h2>
              <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                {repos_html}
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding: 32px 24px; background-color: #f9fafb; text-align: center; border-top: 1px solid #e5e7eb;">
              <p style="margin: 0 0 8px; color: #6b7280; font-size: 13px;">
                Read more at <a href="{SITE_URL}" style="color: #2563eb; text-decoration: none;">{SITE_URL}</a>
              </p>
              <p style="margin: 0 0 8px; color: #6b7280; font-size: 13px;">
                <a href="{SITE_URL}/releases" style="color: #2563eb; text-decoration: none;">Releases</a> &middot;
                <a href="{SITE_URL}/hn" style="color: #2563eb; text-decoration: none;">Hacker News</a> &middot;
                <a href="{SITE_URL}/trending" style="color: #2563eb; text-decoration: none;">Trending</a>
              </p>
              <p style="margin: 16px 0 0; color: #9ca3af; font-size: 12px;">
                You're receiving this because you subscribed to Tech Bytes Weekly.
                <br>
                <a href="{SITE_URL}/unsubscribe" style="color: #9ca3af; text-decoration: underline;">Unsubscribe</a>
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
    """Send the digest email via SES."""
    ses = boto3.client("ses")
    for recipient in recipients:
        try:
            ses.send_email(
                Source=SENDER,
                Destination={"ToAddresses": [recipient]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                    },
                },
            )
            logger.info("Sent digest to %s", recipient)
        except Exception:
            logger.exception("Failed to send email to %s", recipient)


def handler(event: Any = None, context: Any = None) -> dict[str, Any]:
    """Lambda handler — build weekly digest and send via SES."""
    logger.info("Email Digest starting")

    bucket = os.environ.get("DATA_BUCKET_NAME")
    if not bucket:
        logger.error("DATA_BUCKET_NAME not set")
        return {"status": "error", "message": "DATA_BUCKET_NAME not set"}

    # Read latest data from S3
    release_data = _read_s3_json(bucket, "data/release-radar.json")
    hn_data = _read_s3_json(bucket, "data/hn-digest.json")
    gh_data = _read_s3_json(bucket, "data/gh-trending.json")

    # Extract highlights
    top_releases = _extract_top_releases(release_data, count=3)
    top_stories = _extract_top_stories(hn_data, count=5)
    top_repos = _extract_top_repos(gh_data, count=3)

    if not top_releases and not top_stories and not top_repos:
        logger.warning("No content available for digest — skipping")
        return {"status": "skipped", "message": "No content available"}

    # Generate AI summary
    ai_summary = _generate_ai_summary(top_releases, top_stories, top_repos)

    # Build email
    week_date = _week_of_date()
    subject = f"Tech Bytes Weekly — Week of {week_date}"
    html_body = _build_html(week_date, ai_summary, top_releases, top_stories, top_repos)

    # Get subscribers and send
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

    result = handler()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0)
