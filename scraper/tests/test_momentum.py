"""Tests for momentum.py — Δ computation + top movers + projection."""
from __future__ import annotations

import datetime as dt

import pytest

from scraper.momentum import (
    compute_deltas,
    conversion_per_backer,
    conversion_per_watcher,
    projected_total,
    top_movers_from_rows,
)

# ── conversion_per_watcher ────────────────────────────────────────

def test_cpw_basic():
    p = {"followers": 1000, "pledged_usd": 50_000}
    assert conversion_per_watcher(p) == 50.0


def test_cpw_zero_followers_returns_none():
    """Avoid division by zero — should return None, not crash."""
    assert conversion_per_watcher({"followers": 0, "pledged_usd": 5000}) is None
    assert conversion_per_watcher({"followers": None, "pledged_usd": 5000}) is None


def test_cpw_bad_types_returns_none():
    assert conversion_per_watcher({"followers": "n/a", "pledged_usd": 5000}) is None


# ── conversion_per_backer ─────────────────────────────────────────

def test_cpb_basic():
    p = {"backers": 100, "pledged_usd": 50_000}
    assert conversion_per_backer(p) == 500.0


def test_cpb_zero_backers_returns_none():
    assert conversion_per_backer({"backers": 0, "pledged_usd": 100}) is None


# ── top_movers_from_rows ──────────────────────────────────────────

def test_top_movers_picks_positives():
    rows = [
        {"pathname": "/a", "delta_followers": 50},
        {"pathname": "/b", "delta_followers": -10},  # negative → excluded
        {"pathname": "/c", "delta_followers": 200},
        {"pathname": "/d", "delta_followers": 0},   # zero → excluded
        {"pathname": "/e", "delta_followers": 100},
    ]
    movers = top_movers_from_rows(rows, "delta_followers", n=3)
    assert [m["pathname"] for m in movers] == ["/c", "/e", "/a"]


def test_top_movers_handles_missing_key():
    """Rows without the requested key should be silently skipped."""
    rows = [
        {"pathname": "/a", "delta_followers": 100},
        {"pathname": "/b"},  # no delta_followers
    ]
    movers = top_movers_from_rows(rows, "delta_followers", n=3)
    assert len(movers) == 1
    assert movers[0]["pathname"] == "/a"


# ── projected_total ───────────────────────────────────────────────

def test_projected_total_non_live_returns_none():
    """Only live projects get a projection."""
    p = {
        "status": "prelaunch",
        "launched_at": 100, "deadline": 200, "pledged_usd": 5000,
    }
    assert projected_total(p) is None


def test_projected_total_extrapolates_linearly():
    """5 days in, raised $5k, 30-day campaign → projected $30k.

    Day1 spike effects mean the real total is usually lower, but the
    function explicitly says "treat as upper bound" so we test the math
    not the realism."""
    now = dt.datetime.now(dt.UTC).timestamp()
    launched = now - 5 * 86400
    deadline = launched + 30 * 86400
    p = {
        "status": "live",
        "launched_at": launched,
        "deadline": deadline,
        "pledged_usd": 5000.0,
    }
    proj = projected_total(p)
    assert proj is not None
    # 5 days in → $1000/day → 30 days × $1000 = $30K
    assert 29_000 < proj < 31_000, f"got {proj}"


def test_projected_total_too_early_returns_none():
    """Less than 0.5 day in → too early to project linearly."""
    now = dt.datetime.now(dt.UTC).timestamp()
    p = {
        "status": "live",
        "launched_at": now - 3600,  # 1 hour in
        "deadline": now + 30 * 86400,
        "pledged_usd": 100.0,
    }
    assert projected_total(p) is None


def test_projected_total_invalid_dates_returns_none():
    """Defensive: bad date inputs shouldn't crash."""
    p = {"status": "live", "launched_at": 0, "deadline": 0, "pledged_usd": 100}
    assert projected_total(p) is None


# ── compute_deltas (in-memory, no fs) ─────────────────────────────

def test_compute_deltas_no_prev_returns_empty(monkeypatch):
    """If no prev snapshot exists, no deltas are computed and rows are unchanged."""
    monkeypatch.setattr("scraper.momentum.find_prev_snapshot", lambda: (None, None))
    rows = [{"pathname": "/a", "followers": 100}]
    summary = compute_deltas(rows)
    assert summary["prev_at"] is None
    assert summary["top_followers"] == []
    assert "delta_followers" not in rows[0]


def test_compute_deltas_basic(monkeypatch):
    """Two projects, one with +50 followers, one with +10 backers."""
    prev_snap = {
        "generated_at": "2026-05-14T02:00:00Z",
        "projects": [
            {"pathname": "/a", "followers": 100, "backers": 0, "pledged_usd": 0},
            {"pathname": "/b", "followers": 200, "backers": 5, "pledged_usd": 100.0},
        ],
    }
    prev_ts = dt.datetime(2026, 5, 14, 2, 0, 0, tzinfo=dt.UTC)
    monkeypatch.setattr("scraper.momentum.find_prev_snapshot", lambda: (prev_snap, prev_ts))
    rows = [
        {"pathname": "/a", "followers": 150, "backers": 0, "pledged_usd": 0},  # +50 followers
        {"pathname": "/b", "followers": 200, "backers": 15, "pledged_usd": 250.0},  # +10 backers, +$150
    ]
    summary = compute_deltas(rows)
    assert rows[0]["delta_followers"] == 50
    assert rows[1]["delta_backers"] == 10
    assert rows[1]["delta_pledged_usd"] == pytest.approx(150.0)
    # Top followers ranking
    assert summary["top_followers"][0] == ("/a", 50)
    assert summary["top_backers"][0] == ("/b", 10)


def test_compute_deltas_new_project_no_delta(monkeypatch):
    """Project not in prev → no delta fields added (graceful skip)."""
    prev_snap = {"generated_at": "2026-05-14T02:00:00Z", "projects": []}
    prev_ts = dt.datetime(2026, 5, 14, 2, 0, 0, tzinfo=dt.UTC)
    monkeypatch.setattr("scraper.momentum.find_prev_snapshot", lambda: (prev_snap, prev_ts))
    rows = [{"pathname": "/new", "followers": 50}]
    summary = compute_deltas(rows)
    assert "delta_followers" not in rows[0]
    assert summary["top_followers"] == []


def test_compute_deltas_handles_bad_types(monkeypatch):
    """Non-numeric fields shouldn't crash."""
    prev_snap = {
        "generated_at": "2026-05-14T02:00:00Z",
        "projects": [{"pathname": "/a", "followers": "n/a", "pledged_usd": "—"}],
    }
    prev_ts = dt.datetime(2026, 5, 14, 2, 0, 0, tzinfo=dt.UTC)
    monkeypatch.setattr("scraper.momentum.find_prev_snapshot", lambda: (prev_snap, prev_ts))
    rows = [{"pathname": "/a", "followers": "weird", "pledged_usd": None}]
    # Should not raise
    summary = compute_deltas(rows)
    assert summary["prev_at"] == "2026-05-14T02:00:00Z"
