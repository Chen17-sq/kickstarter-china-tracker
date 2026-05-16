"""Tests for weekly.py — Sunday-morning digest computation + HTML rendering."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from scraper.weekly import (
    _load_snapshots_for_week,
    build_html,
    build_plaintext,
    compute_weekly_stats,
)


def _proj(path, status="prelaunch", followers=0, pledged=0.0, backers=0,
          title=None, pwl=False):
    return {
        "pathname": path,
        "title": title or f"Project {path}",
        "status": status,
        "followers": followers,
        "pledged_usd": pledged,
        "backers": backers,
        "project_we_love": pwl,
        "url": f"https://www.kickstarter.com{path}",
        "blurb_zh": "",
    }


def _snap(projects, when: dt.datetime):
    return (when, {
        "generated_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "projects": projects,
    })


def _wk(days_ago: int) -> dt.datetime:
    return dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago)


# ── _load_snapshots_for_week ────────────────────────────────────

def test_load_snapshots_skips_old(monkeypatch, tmp_path):
    """Anything older than 8 days is excluded from the window."""
    hist = tmp_path / "history"
    hist.mkdir()
    # 3 snapshots: -2d (in window), -10d (out), -1d (in)
    for days_ago in [2, 10, 1]:
        ts = (_wk(days_ago)).strftime("%Y-%m-%dT%H-%M-%SZ")
        (hist / f"{ts}.json").write_text('{"projects":[]}', encoding="utf-8")
    monkeypatch.setattr("scraper.weekly.HISTORY", hist)
    week = _load_snapshots_for_week()
    # -2d and -1d should be included, -10d excluded
    assert len(week) == 2


def test_load_snapshots_returns_oldest_first(monkeypatch, tmp_path):
    hist = tmp_path / "history"
    hist.mkdir()
    for days_ago in [1, 5, 3]:
        ts = (_wk(days_ago)).strftime("%Y-%m-%dT%H-%M-%SZ")
        (hist / f"{ts}.json").write_text(
            json.dumps({"projects": [], "day": days_ago}),
            encoding="utf-8",
        )
    monkeypatch.setattr("scraper.weekly.HISTORY", hist)
    week = _load_snapshots_for_week()
    # Sorted oldest-first → -5d, -3d, -1d
    assert len(week) == 3
    days = [snap.get("day") for _, snap in week]
    assert days == [5, 3, 1]


def test_load_no_history_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr("scraper.weekly.HISTORY", tmp_path / "nonexistent")
    assert _load_snapshots_for_week() == []


# ── compute_weekly_stats ────────────────────────────────────────

def test_empty_week_returns_meta_only():
    out = compute_weekly_stats([])
    assert out["new_in_discovery"] == []
    assert out["newly_live"] == []
    assert out["days_in_window"] == 0


def test_new_in_discovery_detected():
    """A pathname that appears mid-week but wasn't in the first snapshot."""
    week = [
        _snap([_proj("/a", followers=100)], _wk(7)),
        _snap([_proj("/a"), _proj("/b", followers=50)], _wk(4)),  # /b new
        _snap([_proj("/a"), _proj("/b"), _proj("/c", followers=200)], _wk(1)),  # /c new
    ]
    out = compute_weekly_stats(week)
    paths = {p["pathname"] for p in out["new_in_discovery"]}
    assert paths == {"/b", "/c"}
    # Sorted by followers desc → /c first
    assert out["new_in_discovery"][0]["pathname"] == "/c"


def test_status_transition_prelaunch_to_live():
    """A project that was prelaunch at week-start, live at week-end."""
    week = [
        _snap([_proj("/a", status="prelaunch")], _wk(7)),
        _snap([_proj("/a", status="live", pledged=5000.0, backers=20)], _wk(1)),
    ]
    out = compute_weekly_stats(week)
    assert len(out["newly_live"]) == 1
    assert out["newly_live"][0]["pathname"] == "/a"
    assert out["newly_live"][0]["_from"] == "prelaunch"
    assert out["newly_live"][0]["_to"] == "live"


def test_status_transition_to_successful():
    week = [
        _snap([_proj("/a", status="live", pledged=5000.0)], _wk(7)),
        _snap([_proj("/a", status="successful", pledged=50000.0, backers=200)], _wk(1)),
    ]
    out = compute_weekly_stats(week)
    assert len(out["newly_successful"]) == 1


def test_top_follower_gainers():
    week = [
        _snap([_proj("/a", followers=100), _proj("/b", followers=200), _proj("/c", followers=300)],
              _wk(7)),
        _snap([_proj("/a", followers=500), _proj("/b", followers=210), _proj("/c", followers=310)],
              _wk(1)),
    ]
    out = compute_weekly_stats(week)
    # /a gained +400, /c gained +10, /b gained +10
    assert out["top_follower_gainers"][0]["pathname"] == "/a"
    assert out["top_follower_gainers"][0]["delta_followers"] == 400


def test_top_usd_gainers():
    week = [
        _snap([_proj("/a", pledged=1000.0), _proj("/b", pledged=500.0)], _wk(7)),
        _snap([_proj("/a", pledged=8000.0), _proj("/b", pledged=600.0)], _wk(1)),
    ]
    out = compute_weekly_stats(week)
    assert out["top_usd_gainers"][0]["pathname"] == "/a"
    assert out["top_usd_gainers"][0]["delta_pledged_usd"] == pytest.approx(7000.0)


def test_total_live_usd_change_sums_only_live_projects():
    week = [
        _snap([
            _proj("/live1", status="live", pledged=1000.0),
            _proj("/done", status="successful", pledged=10000.0),
            _proj("/pre", status="prelaunch"),
        ], _wk(7)),
        _snap([
            _proj("/live1", status="live", pledged=3000.0),  # +2000
            _proj("/done", status="successful", pledged=10000.0),
            _proj("/pre", status="prelaunch"),
        ], _wk(1)),
    ]
    out = compute_weekly_stats(week)
    assert out["total_live_usd_change"] == pytest.approx(2000.0)


def test_pledged_usd_string_normalized():
    """Defensive: project data with pledged_usd as a STRING shouldn't crash.

    This is the bug that bit us in slide-04 — discover.py returned strings.
    Pin behavior so the weekly digest can't trip over the same thing."""
    week = [
        _snap([_proj("/a", pledged="1000.0")], _wk(7)),    # string
        _snap([_proj("/a", pledged=5000.0)], _wk(1)),
    ]
    out = compute_weekly_stats(week)
    # Should not crash, and the delta should be computed
    assert out["top_usd_gainers"][0]["delta_pledged_usd"] == pytest.approx(4000.0)


# ── build_html ──────────────────────────────────────────────────

def test_build_html_includes_populated_sections_only():
    """Sections with no items are omitted — keeps the email tight when a
    week has nothing to report in a category. The masthead, KPI line, and
    populated sections always render."""
    week = [
        _snap([_proj("/a")], _wk(7)),
        _snap([_proj("/a"), _proj("/b", followers=100)], _wk(1)),
    ]
    stats = compute_weekly_stats(week)
    subject, html = build_html(stats)
    assert "Week" in subject
    # Masthead always present
    assert "Weekly · 周报" in html
    # New-discovery section present (we created /b mid-week)
    assert "本周新发现" in html
    # NewlyLive section absent (no transitions in this fixture)
    assert "本周新上线" not in html


def test_build_html_subject_includes_counts():
    week = [
        _snap([_proj("/a", status="prelaunch")], _wk(7)),
        _snap([_proj("/a", status="live"), _proj("/b", followers=50)], _wk(1)),
    ]
    stats = compute_weekly_stats(week)
    subject, _ = build_html(stats)
    # Subject should mention the new project (+1 new) and the live transition (+1 live)
    assert "+1 new" in subject or "1 new" in subject
    assert "+1 live" in subject or "1 live" in subject


# ── build_plaintext ─────────────────────────────────────────────

def test_build_plaintext_contains_all_sections():
    week = [
        _snap([_proj("/a", followers=100, pledged=1000.0)], _wk(7)),
        _snap([
            _proj("/a", followers=500, pledged=5000.0, status="live"),
            _proj("/b", followers=200),
        ], _wk(1)),
    ]
    stats = compute_weekly_stats(week)
    text = build_plaintext(stats)
    assert "周报" in text
    assert "Week" in text
    assert "NEW IN DISCOVERY" in text
    assert "TOP FOLLOWER GAINERS" in text


def test_build_plaintext_includes_urls_for_screen_readers():
    """Plaintext alt must include URLs so accessibility users can navigate."""
    week = [
        _snap([_proj("/a")], _wk(7)),
        _snap([_proj("/a", followers=200), _proj("/b", followers=300,
                    title="New thing", pwl=True)], _wk(1)),
    ]
    stats = compute_weekly_stats(week)
    text = build_plaintext(stats)
    # The new project /b should have its URL in the plaintext output
    assert "kickstarter.com" in text
