"""Tests for sanity.py — the last gate before subscribers' inboxes.

These tests freeze the behavior of each blocking condition so future
refactors don't silently weaken the gate. The gate is the difference
between "send 0 emails today" and "send 6 wrong emails today".
"""
from __future__ import annotations
import pytest

from scraper.sanity import validate_for_send, format_alert_body


def _proj(**kw):
    base = {
        "pathname": "/projects/x/proj",
        "title": "Test Project",
        "status": "live",
        "pledged_usd": 5000.0,
        "backers": 50,
        "followers": 100,
    }
    base.update(kw)
    return base


def _snapshot(projects, generated_at="2026-05-15T02:00:00Z"):
    return {"generated_at": generated_at, "projects": projects}


# Distinct timestamps so the prev<curr ordering check in sanity passes
YESTERDAY = "2026-05-14T02:00:00Z"
TODAY = "2026-05-15T02:00:00Z"


# ── Hard blockers ─────────────────────────────────────────────────

def test_zero_projects_blocks():
    """An empty snapshot is a catastrophic discover failure."""
    ok, issues = validate_for_send(_snapshot([]))
    assert ok is False
    assert any("zero projects" in i for i in issues)


def test_outlier_pledged_blocks():
    """A single project with >$100M pledged is a currency bug."""
    projects = [_proj(pathname=f"/projects/x/{i}", pledged_usd=5000.0)
                for i in range(20)]
    # Inject one outlier (likely cents-as-dollars × 100)
    projects.append(_proj(
        pathname="/projects/x/outlier",
        title="Misconverted-currency project",
        pledged_usd=500_000_000.0,
    ))
    ok, issues = validate_for_send(_snapshot(projects))
    assert ok is False
    assert any("100M" in i or "outlier" in i.lower() or "currency" in i.lower() for i in issues)


def test_negative_pledged_blocks():
    projects = [_proj(pathname=f"/projects/x/{i}") for i in range(20)]
    projects.append(_proj(pathname="/projects/x/bad", pledged_usd=-500.0))
    ok, issues = validate_for_send(_snapshot(projects))
    assert ok is False
    assert any("negative" in i.lower() or "NaN" in i for i in issues)


def test_duplicate_pathnames_block():
    projects = [_proj(pathname="/projects/x/dupe") for _ in range(10)]
    ok, issues = validate_for_send(_snapshot(projects))
    assert ok is False
    assert any("duplicate" in i.lower() for i in issues)


def test_low_followers_coverage_blocks():
    """If fewer than 30% of projects have followers data, watchers
    GraphQL was probably blocked. Block until we know."""
    projects = []
    for i in range(20):
        # All have followers=0 → 0% coverage
        projects.append(_proj(pathname=f"/projects/x/{i}", followers=0))
    ok, issues = validate_for_send(_snapshot(projects))
    assert ok is False
    assert any("followers" in i.lower() and "coverage" in i.lower() for i in issues)


def test_majority_followers_present_passes():
    """If >30% of projects have followers, gate doesn't fire on followers
    alone."""
    projects = []
    for i in range(20):
        # 80% coverage — well above 30% threshold
        projects.append(_proj(
            pathname=f"/projects/x/{i}",
            followers=100 if i < 16 else 0,
        ))
    ok, issues = validate_for_send(_snapshot(projects))
    # Should pass — even if `prev` snapshot is None and Δ checks skip
    assert ok is True, f"unexpected issues: {issues}"


# ── prev comparison checks ────────────────────────────────────────

def test_project_count_drop_blocks():
    """If today's project count is <30% of yesterday's, discover seeds
    likely got 403'd."""
    yesterday = [_proj(pathname=f"/projects/x/{i}") for i in range(100)]
    today = [_proj(pathname=f"/projects/x/{i}") for i in range(20)]  # 20% of 100
    ok, issues = validate_for_send(_snapshot(today, TODAY), _snapshot(yesterday, YESTERDAY))
    assert ok is False
    assert any("count dropped" in i.lower() or "30%" in i for i in issues)


def test_small_count_drop_doesnt_block():
    """A 10% project count drop is normal day-to-day variation."""
    yesterday = [_proj(pathname=f"/projects/x/{i}") for i in range(100)]
    today = [_proj(pathname=f"/projects/x/{i}") for i in range(90)]  # 10% drop
    ok, issues = validate_for_send(_snapshot(today, TODAY), _snapshot(yesterday, YESTERDAY))
    assert ok is True, f"unexpected issues: {issues}"


def test_no_prev_snapshot_doesnt_crash():
    """First-ever run — prev_snapshot is None. Should fall through gracefully."""
    today = [_proj(pathname=f"/projects/x/{i}") for i in range(50)]
    ok, issues = validate_for_send(_snapshot(today), None)
    assert ok is True, f"unexpected issues: {issues}"


# ── Informational "followers identical" warning is non-blocking ──

def test_followers_identical_is_warning_not_block():
    """When watchers fetch fails entirely and we restore from prev snapshot,
    followers will be identical to yesterday. This is a WARNING, not a block."""
    yesterday = [_proj(pathname=f"/projects/x/{i}", followers=100+i) for i in range(50)]
    today = [_proj(pathname=f"/projects/x/{i}", followers=100+i) for i in range(50)]
    ok, issues = validate_for_send(_snapshot(today, TODAY), _snapshot(yesterday, YESTERDAY))
    # Should still broadcast — issue list may contain the warning
    if issues:
        # All non-blocking issues must be the "broadcasting anyway" kind
        for i in issues:
            assert "broadcasting anyway" in i, f"unexpected blocking issue: {i}"
    assert ok is True


# ── Alert body formatting ─────────────────────────────────────────

def test_format_alert_body_includes_issues_and_meta():
    body = format_alert_body(
        issues=["project count dropped 100 → 20 (20%)"],
        snapshot_meta={"generated_at": "2026-05-15T02:00:00Z", "projects": [{}, {}]},
    )
    assert "BLOCKED" in body
    assert "project count dropped" in body
    assert "2026-05-15T02:00:00Z" in body
    assert "What was sent" in body
    assert "What to do" in body
    # Owner-actionable URLs / commands
    assert "ks.aldrich.fyi" in body or "https://" in body
