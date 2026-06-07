"""Tests for the gh_trending HTML parser.

These tests exercise the pure `_parse_trending` parser only — no network calls,
no OpenAI. The synthetic fixture mirrors the real github.com/trending DOM and
includes edge cases (missing language span, missing description paragraph,
missing stars-this-period span).
"""

from pathlib import Path

import pytest

from gh_trending.handler import _parse_trending

FIXTURE = Path(__file__).parent / "fixtures" / "trending_sample.html"


@pytest.fixture(scope="module")
def repos() -> list[dict]:
    """Parse the synthetic trending fixture once for the module."""
    html = FIXTURE.read_text(encoding="utf-8")
    return _parse_trending(html)


def test_parses_all_articles(repos: list[dict]) -> None:
    assert len(repos) == 3


def test_normal_repo_all_fields(repos: list[dict]) -> None:
    repo = repos[0]
    assert repo["name"] == "chopratejas/headroom"
    assert repo["url"] == "https://github.com/chopratejas/headroom"
    assert repo["description"].startswith("Compress tool outputs")
    assert repo["language"] == "Python"
    assert repo["stars"] == 16268
    assert repo["stars_this_period"] == 13308


def test_name_derived_from_href_not_text(repos: list[dict]) -> None:
    # The anchor text contains "chopratejas /" + newline + "headroom"; the name
    # must come from the href, free of whitespace/newlines.
    assert repos[0]["name"] == "chopratejas/headroom"
    assert "\n" not in repos[0]["name"]
    assert " " not in repos[0]["name"]


def test_missing_language_defaults_to_empty(repos: list[dict]) -> None:
    repo = repos[1]
    assert repo["name"] == "acme/no-language"
    assert repo["language"] == ""
    # Other fields still extracted.
    assert repo["description"] == "A repo that has a description but no detected language."
    assert repo["stars"] == 2500
    assert repo["stars_this_period"] == 420


def test_missing_description_defaults_to_empty(repos: list[dict]) -> None:
    repo = repos[2]
    assert repo["name"] == "widgets/no-description"
    assert repo["description"] == ""
    assert repo["language"] == "Rust"
    assert repo["stars"] == 987


def test_missing_stars_this_period_defaults_to_zero(repos: list[dict]) -> None:
    # Repo 3 has no "stars this week/month" span.
    assert repos[2]["stars_this_period"] == 0


def test_empty_html_returns_empty_list() -> None:
    assert _parse_trending("") == []
    assert _parse_trending("<html><body>no rows</body></html>") == []
