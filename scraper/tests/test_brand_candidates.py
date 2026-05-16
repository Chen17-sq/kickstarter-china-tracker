"""Tests for brand_candidates.py — unknown high-signal creator surfacing."""
from __future__ import annotations

from scraper.brand_candidates import (
    CHINA_COUNTRIES,
    FOLLOWERS_THRESHOLD,
    PLEDGED_USD_THRESHOLD,
    detect,
    format_digest_lines,
)


def _p(**kw):
    """Build a project dict shaped like run.py's unknown_for_review."""
    base = {
        "pathname": "/projects/some-creator/some-slug",
        "title": "Project Title",
        "location": "Shenzhen, China",
        "country": "CN",
        "creator_slug": "some-creator",
        "status": "prelaunch",
        "followers": 50,
        "pledged_usd": 0,
        "project_we_love": False,
        "url": "https://www.kickstarter.com/projects/some-creator/some-slug",
        "china_confidence": "未知",
    }
    base.update(kw)
    return base


# ── threshold logic ──────────────────────────────────────────────

def test_high_follower_qualifies():
    p = _p(pathname="/projects/c1/p1", followers=FOLLOWERS_THRESHOLD + 10)
    out = detect([p])
    assert len(out["candidates"]) == 1
    reasons = out["candidates"][0]["reasons"]
    assert any("followers" in r for r in reasons)


def test_high_pledged_qualifies():
    p = _p(pathname="/projects/c2/p2", pledged_usd=PLEDGED_USD_THRESHOLD + 100)
    out = detect([p])
    assert len(out["candidates"]) == 1
    assert any("pledged" in r for r in out["candidates"][0]["reasons"])


def test_staff_pick_qualifies():
    p = _p(pathname="/projects/c3/p3", project_we_love=True)
    out = detect([p])
    assert len(out["candidates"]) == 1
    assert any("staff pick" in r for r in out["candidates"][0]["reasons"])


def test_low_signal_does_not_qualify():
    p = _p(pathname="/projects/c4/p4", followers=10, pledged_usd=0)
    out = detect([p])
    assert out["candidates"] == []


# ── confidence + country filters ─────────────────────────────────

def test_non_unknown_confidence_excluded():
    """Only 未知 projects should surface. 高 / 中 / 否 are already classified."""
    p = _p(pathname="/projects/c5/p5", followers=500, china_confidence="高")
    out = detect([p])
    assert out["candidates"] == []


def test_non_china_country_excluded():
    """If KS reports a non-Greater-China country, skip — too much noise."""
    p = _p(pathname="/projects/c6/p6", followers=500, country="US")
    out = detect([p])
    assert out["candidates"] == []


def test_empty_country_included():
    """KS sometimes returns empty country; we should still surface those."""
    p = _p(pathname="/projects/c7/p7", followers=500, country="")
    out = detect([p])
    assert len(out["candidates"]) == 1


def test_each_china_country_token_passes():
    for cc in CHINA_COUNTRIES:
        p = _p(pathname=f"/projects/c-{cc}/p", followers=500, country=cc)
        out = detect([p])
        assert len(out["candidates"]) == 1, f"{cc} should qualify"


# ── creator dedup ────────────────────────────────────────────────

def test_same_creator_only_appears_once():
    """If a creator has multiple campaigns today, dedup to first occurrence."""
    ps = [
        _p(pathname="/projects/foo/p1", followers=500),
        _p(pathname="/projects/foo/p2", followers=600),
        _p(pathname="/projects/foo/p3", project_we_love=True),
    ]
    out = detect(ps)
    assert len(out["candidates"]) == 1
    assert out["candidates"][0]["creator_slug"] == "foo"


def test_different_creators_all_appear():
    ps = [
        _p(pathname="/projects/foo/p1", followers=500),
        _p(pathname="/projects/bar/p2", followers=600),
        _p(pathname="/projects/baz/p3", project_we_love=True),
    ]
    out = detect(ps)
    assert len(out["candidates"]) == 3
    slugs = sorted(c["creator_slug"] for c in out["candidates"])
    assert slugs == ["bar", "baz", "foo"]


# ── sort order ───────────────────────────────────────────────────

def test_staff_picks_sort_first():
    ps = [
        _p(pathname="/projects/normal/p1", followers=5000),    # high but no PWL
        _p(pathname="/projects/staffpick/p2", project_we_love=True, followers=100),  # PWL
    ]
    out = detect(ps)
    assert out["candidates"][0]["creator_slug"] == "staffpick"


# ── digest formatting ────────────────────────────────────────────

def test_format_digest_empty_returns_nothing():
    out = {"candidates": []}
    assert format_digest_lines(out) == []


def test_format_digest_renders_each_candidate():
    out = {
        "candidates": [
            {"creator_slug": "foo", "title": "Foo product", "location": "Shenzhen, China",
             "followers": 500, "pledged_usd": 0, "project_we_love": True, "reasons": ["test"]}
        ],
        "_meta": {},
    }
    lines = format_digest_lines(out)
    text = "\n".join(lines)
    assert "foo" in text
    assert "Foo product" in text
    assert "500" in text


def test_format_digest_caps_at_8():
    """Long lists shouldn't bloat the digest — truncate at 8 + 'and N more'."""
    out = {
        "candidates": [
            {"creator_slug": f"creator{i}", "title": f"Project {i}",
             "location": "", "followers": 500, "pledged_usd": 0,
             "project_we_love": False, "reasons": ["test"]}
            for i in range(20)
        ],
    }
    lines = format_digest_lines(out)
    text = "\n".join(lines)
    assert "and 12 more" in text or "…and 12 more" in text


# ── defensive ────────────────────────────────────────────────────

def test_empty_input_returns_empty():
    out = detect([])
    assert out["candidates"] == []
    assert "_meta" in out


def test_bad_pledged_usd_does_not_crash():
    p = _p(pathname="/projects/x/p", followers=500, pledged_usd="garbage")
    out = detect([p])
    # follower threshold qualifies it; pledged_usd defaults to 0.0
    assert len(out["candidates"]) == 1
