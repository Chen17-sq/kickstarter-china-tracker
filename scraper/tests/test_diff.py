"""Tests for diff.py — snapshot diffing + changelog rendering."""
from __future__ import annotations

import pytest

from scraper.diff import changes_to_markdown, diff_snapshots


def _snap(projects):
    return {"projects": projects}


def _p(path, **kw):
    base = {"pathname": path, "title": f"Project {path}", "status": "live",
            "followers": 0, "backers": 0}
    base.update(kw)
    return base


# ── new / ended ───────────────────────────────────────────────────

def test_diff_detects_new_project():
    prev = _snap([_p("/a")])
    curr = _snap([_p("/a"), _p("/b", status="prelaunch", followers=80)])
    changes = diff_snapshots(prev, curr)
    new_changes = [c for c in changes if c.kind == "new"]
    assert len(new_changes) == 1
    assert new_changes[0].pathname == "/b"
    assert "prelaunch" in new_changes[0].detail
    assert "80" in new_changes[0].detail


def test_diff_detects_ended_project():
    """A project in prev but not curr → 'ended' (left discovery)."""
    prev = _snap([_p("/a"), _p("/b")])
    curr = _snap([_p("/a")])
    changes = diff_snapshots(prev, curr)
    ended = [c for c in changes if c.kind == "ended"]
    assert len(ended) == 1
    assert ended[0].pathname == "/b"


# ── status_change ─────────────────────────────────────────────────

def test_status_change_detected():
    prev = _snap([_p("/a", status="prelaunch")])
    curr = _snap([_p("/a", status="live")])
    changes = diff_snapshots(prev, curr)
    sc = [c for c in changes if c.kind == "status_change"]
    assert len(sc) == 1
    assert "prelaunch" in sc[0].detail and "live" in sc[0].detail


def test_no_status_change_when_status_same():
    prev = _snap([_p("/a", status="live", followers=10)])
    curr = _snap([_p("/a", status="live", followers=10)])
    changes = diff_snapshots(prev, curr)
    assert not any(c.kind == "status_change" for c in changes)


# ── followers_delta threshold (≥50) ───────────────────────────────

def test_followers_delta_above_threshold():
    prev = _snap([_p("/a", followers=100)])
    curr = _snap([_p("/a", followers=200)])  # +100
    changes = diff_snapshots(prev, curr)
    fd = [c for c in changes if c.kind == "followers_delta"]
    assert len(fd) == 1
    assert "+100 followers" in fd[0].detail


def test_followers_delta_below_threshold_skipped():
    prev = _snap([_p("/a", followers=100)])
    curr = _snap([_p("/a", followers=130)])  # +30 < 50 threshold
    changes = diff_snapshots(prev, curr)
    assert not any(c.kind == "followers_delta" for c in changes)


def test_followers_delta_at_threshold_included():
    """Exactly 50 should be included (≥50)."""
    prev = _snap([_p("/a", followers=100)])
    curr = _snap([_p("/a", followers=150)])
    changes = diff_snapshots(prev, curr)
    fd = [c for c in changes if c.kind == "followers_delta"]
    assert len(fd) == 1


def test_negative_followers_delta_skipped():
    """Unfollows don't generate a changelog entry (interesting but noisy)."""
    prev = _snap([_p("/a", followers=200)])
    curr = _snap([_p("/a", followers=100)])  # -100
    changes = diff_snapshots(prev, curr)
    assert not any(c.kind == "followers_delta" for c in changes)


# ── backers_delta threshold (≥100) ────────────────────────────────

def test_backers_delta_above_threshold():
    prev = _snap([_p("/a", backers=50)])
    curr = _snap([_p("/a", backers=200)])  # +150
    changes = diff_snapshots(prev, curr)
    bd = [c for c in changes if c.kind == "backers_delta"]
    assert len(bd) == 1
    assert "+150 backers" in bd[0].detail


def test_backers_delta_below_threshold_skipped():
    prev = _snap([_p("/a", backers=50)])
    curr = _snap([_p("/a", backers=120)])  # +70 < 100 threshold
    changes = diff_snapshots(prev, curr)
    assert not any(c.kind == "backers_delta" for c in changes)


# ── changes_to_markdown ───────────────────────────────────────────

def test_changes_to_markdown_groups_by_kind():
    prev = _snap([_p("/a"), _p("/c", status="prelaunch")])
    curr = _snap([_p("/b"), _p("/c", status="live")])  # new /b, ended /a, status_change /c
    changes = diff_snapshots(prev, curr)
    md = changes_to_markdown(changes)
    assert "## new" in md
    assert "## ended" in md
    assert "## status_change" in md
    # Project /a appears in 'ended', /b in 'new', /c in 'status_change'
    assert "/a" in md and "/b" in md and "/c" in md


def test_changes_to_markdown_caps_at_50_per_section():
    """Sanity: a 100-project mass-new event still renders without bloating."""
    prev = _snap([])
    curr = _snap([_p(f"/p{i}") for i in range(100)])
    changes = diff_snapshots(prev, curr)
    md = changes_to_markdown(changes)
    # Each new entry contains "Discovered (...)" — should appear ≤50 times
    assert md.count("Discovered") <= 50


def test_empty_diff_returns_no_changes():
    prev = _snap([_p("/a", followers=10), _p("/b", backers=5)])
    curr = _snap([_p("/a", followers=10), _p("/b", backers=5)])
    changes = diff_snapshots(prev, curr)
    assert changes == []


# ── defensive ─────────────────────────────────────────────────────

def test_handles_missing_pathname():
    """Projects without pathname should be silently ignored."""
    prev = {"projects": [{"title": "no path"}]}
    curr = {"projects": [{"title": "no path either"}]}
    # Should not raise
    changes = diff_snapshots(prev, curr)
    assert changes == []
