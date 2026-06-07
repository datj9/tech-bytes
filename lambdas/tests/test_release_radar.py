"""Tests for the release_radar transform/schema.

These tests exercise the pure transform logic only — no network calls and no
OpenAI. `summarize` is monkeypatched to return a deterministic combined
summary+details string, so the output schema can be asserted offline.

The contract under test is the shape consumed by the site
(site/src/pages/index.astro -> Release / Category / ReleaseData):
    { "updated_at": str, "categories": [ {name, icon, category, releases:[...]} ] }
where each release is {version, date, summary, details} and `details` is a
newline-joined STRING (not a list).
"""

import release_radar.handler as rr

FAKE_SUMMARY = "Short prose summary of the release for developers."
FAKE_AI_RESPONSE = f"{FAKE_SUMMARY}\n---DETAILS---\n- First key change\n- Second key change"


def _fake_summarize(text: str, prompt: str, max_tokens: int = 400) -> str:
    """Stand-in for shared.utils.summarize — deterministic, no network."""
    return FAKE_AI_RESPONSE


def _fake_release(tag: str = "v1.2.3", body: str = "Lots of great changes") -> dict:
    return {
        "tag_name": tag,
        "name": f"Release {tag}",
        "body": body,
        "published_at": "2026-06-01T12:34:56Z",
        "html_url": "https://example.com/release",
    }


def test_split_summary_details_splits_on_delimiter() -> None:
    summary, details = rr._split_summary_details(FAKE_AI_RESPONSE)
    assert summary == FAKE_SUMMARY
    assert details == "- First key change\n- Second key change"
    assert isinstance(details, str)


def test_split_summary_details_without_delimiter_is_all_summary() -> None:
    summary, details = rr._split_summary_details("Just a summary, no bullets.")
    assert summary == "Just a summary, no bullets."
    assert details == ""


def test_process_release_schema(monkeypatch) -> None:
    monkeypatch.setattr(rr, "summarize", _fake_summarize)
    out = rr._process_release(_fake_release(tag="22.15.0"))

    assert set(out.keys()) == {"version", "date", "summary", "details"}
    assert out["version"] == "22.15.0"
    # published_at ISO datetime is mapped to a YYYY-MM-DD date.
    assert out["date"] == "2026-06-01"
    assert out["summary"] == FAKE_SUMMARY
    assert isinstance(out["details"], str)
    assert out["details"].startswith("- ")


def test_process_technology_emits_category_shape(monkeypatch) -> None:
    monkeypatch.setattr(rr, "summarize", _fake_summarize)
    monkeypatch.setattr(rr, "_fetch_releases", lambda repo, count=3: [_fake_release()])

    entry = rr._process_technology({"name": "React", "repo": "facebook/react", "category": "Frontend"})

    assert entry is not None
    assert entry["name"] == "React"
    assert entry["category"] == "Frontend"
    # `icon` is a KEY string into index.astro's categoryIcons map, NOT an emoji.
    # React has a dedicated per-tech legacy key.
    assert entry["icon"] == "react"
    assert entry["icon"] == rr.TECH_ICON_KEYS["React"]
    assert isinstance(entry["releases"], list)
    # Latest-only: at most one release is summarized.
    assert len(entry["releases"]) == 1
    assert isinstance(entry["releases"][0]["details"], str)


def test_process_technology_no_tech_key_falls_back_to_category_name(monkeypatch) -> None:
    monkeypatch.setattr(rr, "summarize", _fake_summarize)
    monkeypatch.setattr(rr, "_fetch_releases", lambda repo, count=3: [_fake_release()])

    # Vite has no dedicated per-tech key -> icon falls back to the category NAME,
    # which index.astro's categoryIcons maps to the "Build Tools" emoji.
    entry = rr._process_technology({"name": "Vite", "repo": "vitejs/vite", "category": "Build Tools"})

    assert entry is not None
    assert entry["icon"] == "Build Tools"
    # Always a key string, never a raw emoji literal.
    assert entry["icon"] not in {"🚀", "⚛️", "📦", "🔷", "🎨", "🔧", "🏗️", "📋"}


def test_process_technology_prefers_release_with_body(monkeypatch) -> None:
    monkeypatch.setattr(rr, "summarize", _fake_summarize)
    # Newest first: latest has empty body, second has a real body -> pick the second.
    releases = [
        _fake_release(tag="v2.0.0", body="   "),
        _fake_release(tag="v1.9.0", body="Real changelog content"),
    ]
    monkeypatch.setattr(rr, "_fetch_releases", lambda repo, count=3: releases)

    entry = rr._process_technology({"name": "Tech", "repo": "x/y", "category": "Runtimes"})
    assert entry is not None
    assert entry["releases"][0]["version"] == "v1.9.0"


def test_process_technology_no_releases_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(rr, "_fetch_releases", lambda repo, count=3: [])
    entry = rr._process_technology({"name": "Empty", "repo": "x/y", "category": "Runtimes"})
    assert entry is None


def test_handler_output_schema(monkeypatch) -> None:
    monkeypatch.setattr(rr, "summarize", _fake_summarize)
    monkeypatch.setattr(rr, "_fetch_releases", lambda repo, count=3: [_fake_release()])
    monkeypatch.setattr(
        rr,
        "_load_technologies",
        lambda: [
            {"name": "Node.js", "repo": "nodejs/node", "category": "Runtimes"},
            {"name": "React", "repo": "facebook/react", "category": "Frontend"},
        ],
    )
    # Stub out side effects (S3 upload, rebuild trigger, metrics).
    monkeypatch.setattr(rr, "upload_to_s3", lambda data, key: None)
    monkeypatch.setattr(rr, "trigger_rebuild", lambda: None)
    monkeypatch.setattr(rr, "emit_metric", lambda name, value, *a, **k: None)

    out = rr.handler()

    # Top-level shape: updated_at (string) + categories (LIST).
    assert "updated_at" in out
    assert isinstance(out["updated_at"], str) and out["updated_at"]
    assert "categories" in out
    assert isinstance(out["categories"], list)
    assert len(out["categories"]) == 2

    # Legacy keys from the old broken schema must be gone.
    assert "generated_at" not in out
    assert "technologies" not in out

    for cat in out["categories"]:
        assert isinstance(cat, dict)
        assert {"name", "icon", "releases"} <= set(cat.keys())
        assert isinstance(cat["releases"], list)
        for rel in cat["releases"]:
            assert {"version", "date", "summary", "details"} <= set(rel.keys())
            assert isinstance(rel["details"], str)


def test_handler_no_technologies_returns_empty_schema(monkeypatch) -> None:
    monkeypatch.setattr(rr, "_load_technologies", lambda: [])
    out = rr.handler()
    assert out["categories"] == []
    assert isinstance(out["updated_at"], str)
