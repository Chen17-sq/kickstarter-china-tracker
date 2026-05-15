"""Tests for the sleeper streak-bonus mechanism."""
from __future__ import annotations

import json

import pytest

from scraper import sleepers
from scraper.sleepers import STREAK_BONUS_PER_DAY, select_sleepers


def _p(**kw):
    base = {
        "pathname": "/projects/x/test",
        "title": "AI-powered widget",  # triggers AI 硬件 novelty
        "blurb": "",
        "blurb_zh": "",
        "status": "live",
        "percent_funded": 0,
        "pledged_usd": 0,
        "delta_pledged_usd": 0,
        "delta_backers": 0,
        "delta_followers": 0,
        "followers": 0,
        "project_we_love": False,
    }
    base.update(kw)
    return base


def _read_streaks_file(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@pytest.fixture
def isolated_streaks(tmp_path, monkeypatch):
    """Redirect STREAK_PATH to a temp file so tests don't pollute real data."""
    fake_path = tmp_path / "streaks.json"
    monkeypatch.setattr(sleepers, "STREAK_PATH", fake_path)
    return fake_path


def test_streak_starts_at_1_for_new_pick(isolated_streaks):
    """First time a project shows up as sleeper, streak = 1, no bonus."""
    p = _p(pathname="/a", title="AI-powered toaster")
    picks = select_sleepers([p], exclude_pathnames=set(), n=5)
    assert len(picks) == 1
    # Streak count is 1 but bonus is +0 (bonus = (days-1) * 30 if days >= 2)
    assert "连续" not in picks[0]["_sleeper_reason"]
    # File should record streak=1 for this project
    streaks = _read_streaks_file(isolated_streaks)
    assert streaks == {"/a": 1}


def test_streak_increments_on_second_day(isolated_streaks):
    """Second run with same project → streak=2 → bonus +30, reason gets tag."""
    p = _p(pathname="/a", title="AI-powered toaster")

    # Day 1
    picks_d1 = select_sleepers([p], exclude_pathnames=set(), n=5)
    score_d1 = picks_d1[0]["_sleeper_score"]

    # Day 2 — same project shows up again
    picks_d2 = select_sleepers([p], exclude_pathnames=set(), n=5)
    assert len(picks_d2) == 1
    assert picks_d2[0]["_sleeper_score"] == score_d1 + STREAK_BONUS_PER_DAY
    assert "连续 2 天上榜" in picks_d2[0]["_sleeper_reason"]


def test_streak_caps_at_3_days(isolated_streaks):
    """Streak bonus caps at 3 days extra (so a 10-day streak doesn't dominate)."""
    p = _p(pathname="/a", title="AI-powered toaster")

    # Day 1
    picks = select_sleepers([p], exclude_pathnames=set(), n=5)
    base_score = picks[0]["_sleeper_score"]

    # Days 2 through 10 (run 9 more times)
    for _ in range(9):
        picks = select_sleepers([p], exclude_pathnames=set(), n=5)

    # After 10 days, bonus should be capped at 3 days * 30 = 90
    assert picks[0]["_sleeper_score"] == base_score + STREAK_BONUS_PER_DAY * 3
    assert "连续 10 天上榜" in picks[0]["_sleeper_reason"]


def test_streak_resets_when_project_drops_out(isolated_streaks):
    """If a project doesn't qualify in a run, its streak resets.

    Achieved by: select_sleepers only writes today_streaks for projects
    it picked; old streak entries don't carry over.
    """
    p = _p(pathname="/a", title="AI-powered widget")

    # Day 1: project qualifies
    select_sleepers([p], exclude_pathnames=set(), n=5)
    assert _read_streaks_file(isolated_streaks) == {"/a": 1}

    # Day 2: same project but with all novelty stripped → won't qualify
    p_boring = _p(pathname="/a", title="Just a thing")
    picks = select_sleepers([p_boring], exclude_pathnames=set(), n=5)
    # Project didn't qualify → not in this run's streak file → effectively reset
    assert picks == []
    streaks = _read_streaks_file(isolated_streaks)
    assert "/a" not in streaks

    # Day 3: comes back interesting → streak starts at 1 again
    select_sleepers([p], exclude_pathnames=set(), n=5)
    assert _read_streaks_file(isolated_streaks) == {"/a": 1}


def test_excluded_pathnames_dont_get_streak(isolated_streaks):
    """If a project is on the front page (Top 10), don't track it as sleeper.

    Top 10 status is volatile — projects bobble in/out daily. We don't want
    the streak counter to artificially favor stuff that dipped out of Top 10
    once.
    """
    p = _p(pathname="/a", title="AI-powered widget")
    picks = select_sleepers([p], exclude_pathnames={"/a"}, n=5)
    assert picks == []
    assert _read_streaks_file(isolated_streaks) == {}


def test_streak_persists_across_separate_select_calls(isolated_streaks):
    """Streaks survive separate process invocations (file persistence)."""
    p1 = _p(pathname="/a", title="AI-powered toaster")
    p2 = _p(pathname="/b", title="humanoid robot kit")

    # Run 1: both qualify
    select_sleepers([p1, p2], exclude_pathnames=set(), n=5)

    # Run 2: same projects, fresh function call
    picks = select_sleepers([p1, p2], exclude_pathnames=set(), n=5)
    titles_with_streak = [pi["_sleeper_reason"] for pi in picks]
    assert all("连续 2 天" in t for t in titles_with_streak)
