"""Tests for anomalies.py — vanished / reverted / stuck detectors."""
from __future__ import annotations

import pytest

from scraper.anomalies import detect, format_digest_lines


def _p(path, **kw):
    base = {
        "pathname": path,
        "title": f"Project {path}",
        "status": "live",
        "followers": 100,
        "pledged_usd": 5000.0,
    }
    base.update(kw)
    return base


def _snap(projects, generated_at="2026-05-15T02:00:00Z"):
    return {"generated_at": generated_at, "projects": projects}


# ── vanished ──────────────────────────────────────────────────────

def test_vanished_live_project_detected():
    """A 'live' project in prev but missing today is suspicious."""
    prev = _snap([_p("/a", status="live")])
    curr = _snap([])
    out = detect(curr, prev)
    assert len(out["vanished"]) == 1
    assert out["vanished"][0]["pathname"] == "/a"


def test_vanished_successful_project_ignored():
    """'successful' projects often unpublish after campaign ends — not an anomaly."""
    prev = _snap([_p("/done", status="successful")])
    curr = _snap([])
    out = detect(curr, prev)
    assert out["vanished"] == []


def test_vanished_failed_project_ignored():
    prev = _snap([_p("/sad", status="failed")])
    curr = _snap([])
    out = detect(curr, prev)
    assert out["vanished"] == []


def test_vanished_prelaunch_detected():
    """Prelaunch projects vanishing is genuinely odd — flag them."""
    prev = _snap([_p("/p", status="prelaunch")])
    curr = _snap([])
    out = detect(curr, prev)
    assert len(out["vanished"]) == 1


# ── reverted ──────────────────────────────────────────────────────

def test_reverted_follower_crash_detected():
    prev = _snap([_p("/a", followers=100)])
    curr = _snap([_p("/a", followers=30)])  # -70%
    out = detect(curr, prev)
    assert len(out["reverted"]) == 1
    r = out["reverted"][0]
    assert r["prev_followers"] == 100
    assert r["curr_followers"] == 30


def test_reverted_small_drop_ignored():
    prev = _snap([_p("/a", followers=100)])
    curr = _snap([_p("/a", followers=80)])  # -20%, under the 50% threshold
    out = detect(curr, prev)
    assert out["reverted"] == []


def test_reverted_low_baseline_ignored():
    """Projects with <10 followers yesterday don't generate reverted alerts —
    too noisy at the small end."""
    prev = _snap([_p("/a", followers=5)])
    curr = _snap([_p("/a", followers=1)])  # 80% drop but tiny absolute
    out = detect(curr, prev)
    assert out["reverted"] == []


def test_reverted_increase_ignored():
    """Growth is not an anomaly. (delta > 0 isn't reverted.)"""
    prev = _snap([_p("/a", followers=100)])
    curr = _snap([_p("/a", followers=200)])
    out = detect(curr, prev)
    assert out["reverted"] == []


# ── no prev snapshot ──────────────────────────────────────────────

def test_no_prev_returns_empty_lists():
    """First-ever run: nothing to compare against."""
    out = detect(_snap([_p("/a")]), None)
    assert out["vanished"] == []
    assert out["reverted"] == []
    assert out["stuck"] == []


def test_no_prev_doesnt_crash():
    out = detect(_snap([]), None)
    assert out is not None
    assert "_meta" in out


# ── digest formatting ─────────────────────────────────────────────

def test_format_digest_empty_returns_nothing():
    """No anomalies → no lines (don't pollute the digest with noise)."""
    out = {"vanished": [], "reverted": [], "stuck": []}
    assert format_digest_lines(out) == []


def test_format_digest_includes_each_class():
    out = {
        "vanished": [{"pathname": "/v1", "title": "Vanished thing",
                      "status": "live", "last_followers": 200}],
        "reverted": [{"pathname": "/r1", "title": "Reverted thing",
                      "prev_followers": 100, "curr_followers": 30}],
        "stuck": [{"pathname": "/s1", "title": "Stuck thing",
                   "pledged_usd": 5000.0, "days_unchanged": 7}],
    }
    lines = format_digest_lines(out)
    text = "\n".join(lines)
    assert "vanished" in text
    assert "Vanished thing" in text
    assert "reverted" in text
    assert "Reverted thing" in text
    assert "stuck" in text
    assert "Stuck thing" in text


def test_format_digest_caps_at_5_per_class():
    """Long lists shouldn't bloat the digest — truncate at 5 + 'and N more'."""
    out = {
        "vanished": [
            {"pathname": f"/v{i}", "title": f"Project v{i}",
             "status": "live", "last_followers": 100}
            for i in range(20)
        ],
        "reverted": [],
        "stuck": [],
    }
    lines = format_digest_lines(out)
    text = "\n".join(lines)
    # First 5 shown + "and 15 more" marker
    assert "and 15 more" in text or "…and 15 more" in text
