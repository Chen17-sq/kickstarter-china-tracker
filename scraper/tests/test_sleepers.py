"""Tests for sleepers.py — novelty scoring + diversity caps + reason composition.

Failure modes these tests guard against:
* Someone adds a novelty pattern and accidentally breaks one of the existing
  ones (e.g., overly broad regex catching "fairy tale" → "AI 标签" false hit).
* Refactoring _score_one breaks the metric phrasing fallback path.
* Diversity cap silently regresses to 1 or 2 instead of 3, leaving us with
  too few picks on slow days.
* Phrasing is no longer deterministic across renders (different idx returned
  for same pathname on different runs → email + report show different lines).
"""
from __future__ import annotations
import pytest

from scraper.sleepers import (
    _novelty_hits,
    _score_one,
    _pick_phrasing,
    _HIDDEN_HOT,
    select_sleepers,
)


# ── Novelty matching tests ─────────────────────────────────────────

def _p(**kw):
    """Build a minimal project dict for scoring tests. Sensible defaults."""
    base = {
        "pathname": "/projects/x/test",
        "title": "",
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


def test_novelty_ai_hardware_powered():
    hits = _novelty_hits(_p(title="AI-powered toothbrush"))
    assert len(hits) >= 1
    labels = [h[1] for h in hits]
    assert "AI 硬件" in labels


def test_novelty_ai_glasses():
    hits = _novelty_hits(_p(title="MyGlasses AI: smart glasses for runners"))
    labels = [h[1] for h in hits]
    assert "AI 硬件" in labels


def test_novelty_robotics_humanoid():
    hits = _novelty_hits(_p(title="Mini humanoid robot kit"))
    labels = [h[1] for h in hits]
    assert "机器人" in labels


def test_novelty_worlds_first_zh():
    hits = _novelty_hits(_p(title="全球首款指纹拉链锁"))
    labels = [h[1] for h in hits]
    assert "全球首款" in labels


def test_novelty_worlds_first_en():
    hits = _novelty_hits(_p(blurb="The world's first folding e-bike under $300"))
    labels = [h[1] for h in hits]
    assert "全球首款" in labels


def test_novelty_graphene():
    hits = _novelty_hits(_p(blurb="Graphene + aerogel insulation in a sleeping bag"))
    labels = [h[1] for h in hits]
    assert "新材料" in labels


def test_novelty_mems_audio():
    hits = _novelty_hits(_p(blurb="MEMS driver in-ear monitor with tribrid setup"))
    labels = [h[1] for h in hits]
    assert "新声学" in labels


def test_novelty_open_source_zh():
    hits = _novelty_hits(_p(blurb_zh="完全开源的 ARM 开发板"))
    labels = [h[1] for h in hits]
    assert "开源" in labels


def test_novelty_no_false_positive_on_innocent_text():
    """Plain product description must not trigger any novelty hit."""
    hits = _novelty_hits(_p(title="Stainless steel water bottle", blurb="A reusable bottle for daily use"))
    assert hits == [], f"unexpected novelty hits on innocent text: {hits}"


def test_novelty_ai_word_boundary():
    """'PAID' or 'RAID' or 'SAID' should NOT trigger the bare 'ai' pattern."""
    hits = _novelty_hits(_p(blurb="PAID upgrade · RAID array · maid service"))
    labels = [h[1] for h in hits]
    assert "AI 标签" not in labels and "AI 硬件" not in labels


def test_novelty_deduplicates_by_label():
    """Multiple AI mentions only generate one 'AI 硬件' hit, not 3."""
    hits = _novelty_hits(_p(
        title="AI-powered AI-driven AI agent platform",
        blurb="AI-native AI assistant",
    ))
    ai_label_hits = [h for h in hits if h[1] == "AI 硬件"]
    assert len(ai_label_hits) == 1


# ── Score composition tests ───────────────────────────────────────

def test_score_composes_novelty_and_metric():
    """A project that hits both novelty + metric → reason = novelty + metric."""
    p = _p(
        title="AI-powered laser engraver",
        status="live",
        delta_backers=80,
    )
    score, reason = _score_one(p)
    assert score >= 140 + 60  # novelty + early_traction
    assert "AI 硬件" in reason
    assert "·" in reason  # composite separator


def test_score_novelty_only():
    p = _p(title="AI-powered something", status="prelaunch", followers=10)
    score, reason = _score_one(p)
    # Pure novelty, no metric bucket hit
    assert score >= 140
    assert reason == "AI 硬件"


def test_score_metric_only():
    """No novelty keywords → metric phrasing alone."""
    p = _p(
        title="Premium wallet",
        status="live",
        percent_funded=150,
    )
    score, reason = _score_one(p)
    assert score >= 40
    assert "AI" not in reason
    assert "机器人" not in reason
    # Should hit just_crossed bucket
    assert "150" in reason or "刚过" in reason or "达成" in reason


def test_score_filters_out_uninteresting():
    """A boring live project with no edge gets 0 score."""
    p = _p(title="Plain water bottle", status="live", percent_funded=50)
    score, reason = _score_one(p)
    assert score == 0
    assert reason == ""


def test_score_hidden_hot():
    """500%+ funded but <$100K → hidden_hot bucket."""
    p = _p(
        title="Cute keychain",
        status="live",
        percent_funded=600,
        pledged_usd=40_000,
    )
    score, reason = _score_one(p)
    assert score >= 100
    assert "$" in reason or "K" in reason


# ── Deterministic phrasing tests ──────────────────────────────────

def test_phrasing_deterministic_across_calls():
    """Same seed must always pick the same phrasing — otherwise email and
    markdown rendered in different processes would disagree."""
    seed = "/projects/example/widget"
    p1 = _pick_phrasing(seed, _HIDDEN_HOT)
    p2 = _pick_phrasing(seed, _HIDDEN_HOT)
    p3 = _pick_phrasing(seed, _HIDDEN_HOT)
    assert p1 == p2 == p3


def test_phrasing_varies_across_seeds():
    """Different projects should sometimes get different phrasings."""
    # Use 30 seeds to make at least one variation extremely likely
    from scraper.sleepers import _PHRASING_CTX
    _PHRASING_CTX.update(funded=500, pledged=50_000)
    seen = set()
    for i in range(30):
        seen.add(_pick_phrasing(f"/projects/x/proj-{i}", _HIDDEN_HOT))
    assert len(seen) >= 2, "phrasing should vary across different seeds"


# ── Diversity cap tests ───────────────────────────────────────────

def test_select_sleepers_respects_status_cap():
    """Max 3 per status bucket."""
    projects = []
    # 10 hidden_hot live projects, all distinct pathnames
    for i in range(10):
        projects.append(_p(
            pathname=f"/projects/x/live-{i}",
            title=f"Live project {i}",
            status="live",
            percent_funded=600,
            pledged_usd=30_000 + i,
        ))
    picks = select_sleepers(projects, exclude_pathnames=set(), n=10)
    live_count = sum(1 for p in picks if p["status"] == "live")
    assert live_count <= 3, f"got {live_count} live picks, cap is 3"


def test_select_sleepers_respects_novelty_cap():
    """Max 3 per novelty label."""
    projects = []
    for i in range(10):
        projects.append(_p(
            pathname=f"/projects/x/ai-{i}",
            title=f"AI-powered widget {i}",  # all hit 'AI 硬件'
            status="live" if i % 3 == 0 else "prelaunch" if i % 3 == 1 else "successful",
            delta_backers=80,
        ))
    picks = select_sleepers(projects, exclude_pathnames=set(), n=10)
    ai_count = sum(1 for p in picks if p["_sleeper_reason"].startswith("AI 硬件"))
    assert ai_count <= 3, f"got {ai_count} AI硬件 picks, cap is 3"


def test_select_sleepers_excludes_front_paths():
    """Pathnames in exclude_pathnames must not appear in output."""
    projects = [
        _p(pathname=f"/projects/x/{i}", title=f"AI widget {i}", status="live", delta_backers=80)
        for i in range(5)
    ]
    excluded = {"/projects/x/0", "/projects/x/1"}
    picks = select_sleepers(projects, exclude_pathnames=excluded, n=10)
    pick_paths = {p["pathname"] for p in picks}
    assert excluded.isdisjoint(pick_paths)


def test_select_sleepers_returns_n_when_available():
    """When there are clearly N+ qualifying projects, return exactly N."""
    # Build N qualifying projects with different novelty labels to bypass
    # the per-novelty cap
    labels_titles = [
        ("AI 硬件", "AI-powered widget"),
        ("机器人", "humanoid robot"),
        ("全球首款", "world's first foldable laptop"),
        ("新材料", "graphene cookware"),
        ("新声学", "MEMS driver headphones"),
        ("可穿戴", "smart ring wearable"),
        ("电动出行", "e-bike folding"),
    ]
    # Use 3 different statuses to bypass the per-status cap
    statuses = ["live", "prelaunch", "successful"]
    projects = []
    for i, (lbl, title) in enumerate(labels_titles):
        projects.append(_p(
            pathname=f"/projects/x/{i}",
            title=title,
            status=statuses[i % 3],
            delta_backers=80,
        ))
    picks = select_sleepers(projects, exclude_pathnames=set(), n=5)
    assert len(picks) == 5


def test_select_sleepers_sorts_by_score_desc():
    """Higher-score projects must come first."""
    projects = [
        _p(pathname="/a", title="AI-powered AI agent", status="live", delta_backers=80),  # AI 硬件 + early_traction
        _p(pathname="/b", title="Pretty notebook", status="live", percent_funded=150),    # just_crossed only
    ]
    picks = select_sleepers(projects, exclude_pathnames=set(), n=2)
    assert len(picks) == 2
    assert picks[0]["_sleeper_score"] >= picks[1]["_sleeper_score"]


# ── Reason rendering tests ────────────────────────────────────────

def test_reason_uses_novelty_label_in_composite():
    """Composite reason always starts with the novelty label."""
    p = _p(title="World's first AI-powered toaster", status="live",
           percent_funded=600, pledged_usd=30_000)
    score, reason = _score_one(p)
    # AI 硬件 outranks 全球首款 in priority (140 > 100)
    # But composite format is "<novelty> · <metric>"
    assert reason.startswith("AI 硬件") or reason.startswith("全球首款")


def test_no_reason_for_zero_score():
    """Empty title + boring metrics → no reason, will be filtered."""
    p = _p(title="generic project")
    score, reason = _score_one(p)
    assert score == 0
    assert reason == ""
