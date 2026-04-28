"""Sleeper of the Day — algorithmic picks of interesting projects NOT in Top 10.

The Top 10 (by watchers / USD) is what every reader sees on the front page.
Sleepers are the alpha — projects you'd find if you actually scrolled past
the obvious picks. We score every non-Top-10 project across 6 buckets and
emit the top N (default 5) with the reason each was picked.

Editorial framing: each sleeper shows up with a single-line "why" tag.
That's what differentiates from a raw 'next 10 by watchers' list — every
sleeper has a stated reason for the editor (or reader) to care.

Buckets, in score order:
  - hidden_hot       — funded% > 500%   AND  pledged < $100K
  - acceleration     — Δpledged_24h is > 20% of cumulative pledged
  - early_traction   — live + Δbackers ≥ 50 (24h)
  - watcher_surge    — prelaunch + Δfollowers ≥ 30 (24h)
  - just_crossed     — live + 100% ≤ funded < 200%
  - cold_pick        — watchers < 500 + KS Editor's Pick (PWL)

Output: list of project dicts with two extra keys:
  _sleeper_score   — int, higher = more interesting
  _sleeper_reason  — human-readable single-line tag (zh)
"""
from __future__ import annotations
from typing import Iterable


def _num(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _score_one(p: dict) -> tuple[int, list[str]]:
    """Score a single project. Returns (score, list_of_reasons).
    A project can hit multiple buckets — we pick the most striking reason
    to display, but sum all scores."""
    funded = _num(p.get("percent_funded"))
    pledged = _num(p.get("pledged_usd"))
    delta_p = _num(p.get("delta_pledged_usd"))
    delta_b = int(_num(p.get("delta_backers")))
    delta_f = int(_num(p.get("delta_followers")))
    watchers = int(_num(p.get("followers")))
    status = p.get("status") or ""
    pwl = bool(p.get("project_we_love"))

    score = 0
    reasons: list[tuple[int, str]] = []  # (priority, label)

    # ─ hidden_hot ─
    if funded > 500 and 0 < pledged < 100_000:
        score += 100
        reasons.append((1, f"超额 {funded/100:.0f}× 但只有 {pledged/1000:.0f}K 已筹"))

    # ─ acceleration ─ (only meaningful for live, where pledged grows)
    if pledged > 0 and delta_p > pledged * 0.20:
        score += 80
        pct = delta_p / pledged * 100
        reasons.append((2, f"24h 内涨 {pct:.0f}%（+${delta_p/1000:.1f}K）"))

    # ─ early_traction ─
    if status == "live" and delta_b >= 50:
        score += 60
        reasons.append((3, f"24h +{delta_b} backers"))

    # ─ watcher_surge ─
    if status == "prelaunch" and delta_f >= 30:
        score += 60
        reasons.append((3, f"24h +{delta_f} watchers"))

    # ─ just_crossed ─ (just past goal but not blown up yet)
    if status == "live" and 100 <= funded < 200:
        score += 40
        reasons.append((4, f"刚过目标 · {funded:.0f}%"))

    # ─ cold_pick ─
    if pwl and watchers < 500 and status == "prelaunch":
        score += 50
        reasons.append((4, f"KS Pick 但仅 {watchers} 关注"))
    elif pwl and watchers < 500 and status == "live":
        score += 50
        reasons.append((4, f"KS Pick 但仅 {watchers} watchers"))

    # Pick the highest-priority (lowest priority number = most striking)
    reasons.sort(key=lambda x: x[0])
    return score, [r[1] for r in reasons]


def select_sleepers(
    projects: Iterable[dict],
    exclude_pathnames: set[str],
    n: int = 5,
) -> list[dict]:
    """Pick N projects worth surfacing. Returns shallow-cloned dicts with
    `_sleeper_score` and `_sleeper_reason` keys added.

    `exclude_pathnames` should be the set of pathnames already shown in
    Top 10 prelaunch + Top 10 live + Top 10 successful — so sleepers are
    truly distinct from the front-page picks.

    Diversity rule: at most 2 sleepers per status bucket (prelaunch / live
    / successful), so we don't over-index on one stage of the funnel.
    """
    scored: list[tuple[int, list[str], dict]] = []
    for p in projects:
        if p.get("pathname") in exclude_pathnames:
            continue
        score, reasons = _score_one(p)
        if score <= 0 or not reasons:
            continue
        scored.append((score, reasons, p))

    # Highest-scoring first
    scored.sort(key=lambda t: -t[0])

    out: list[dict] = []
    by_status: dict[str, int] = {}
    for score, reasons, p in scored:
        st = p.get("status") or "unknown"
        if by_status.get(st, 0) >= 2:
            continue
        by_status[st] = by_status.get(st, 0) + 1

        # Shallow clone + annotate
        q = dict(p)
        q["_sleeper_score"] = score
        q["_sleeper_reason"] = reasons[0]  # most striking
        out.append(q)
        if len(out) >= n:
            break

    return out
