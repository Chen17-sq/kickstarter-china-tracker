"""Data sanity checks — last gate before subscribers' inboxes.

A scrape can complete "successfully" (workflow returns 0) and still
produce a snapshot full of garbage:
  - watchers all 0 (Cloudflare blocked GraphQL — today's case)
  - pledged_usd all 0 (Discover JSON shape changed)
  - 5 projects when yesterday had 240 (seed pages all 403'd)

The pipeline above this catches some of these (run.py preserves
previous followers if coverage <50%). This module is the LAST gate:
called from email_notify.py right before the broadcast loop. If any
check fails, we abort the broadcast, fire an owner-only alert, and
let the human decide.

Better to send 0 emails today than 6 wrong ones.
"""
from __future__ import annotations
from typing import Optional


def validate_for_send(curr: dict, prev: Optional[dict] = None) -> tuple[bool, list[str]]:
    """Inspect today's snapshot. If anything looks broken, return (False, reasons).

    `curr` and `prev` are the parsed contents of `data/projects.json` from
    today and yesterday respectively. `prev` may be None (first-ever run,
    or history not loadable — rare).

    Returns (ok_to_broadcast, issues). When `ok_to_broadcast` is False, the
    caller MUST skip the subscriber loop and send an owner-only alert
    instead. `issues` is a list of human-readable failure reasons (joined
    with newlines for the alert body).
    """
    issues: list[str] = []
    projects = curr.get("projects") or []
    n = len(projects)

    # ── Hard floors (absolute) ────────────────────────────────────
    if n == 0:
        return False, ["snapshot has zero projects (discover catastrophic failure)"]

    # Outlier detection — pledged_usd values that can't physically exist.
    # KS's largest project ever (Pebble 2) was ~$20M. A single project
    # >$100M = currency conversion bug (×100 from cents). We block.
    def _num(v):
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0
    outlier_pledged = [p for p in projects if _num(p.get("pledged_usd")) > 100_000_000]
    if outlier_pledged:
        names = ", ".join((p.get("title") or "?")[:40] for p in outlier_pledged[:3])
        issues.append(
            f"{len(outlier_pledged)} projects pledged > $100M (currency conversion bug?): {names}"
        )

    # Negative or NaN pledged values — pure data corruption signal
    bad_pledged = []
    for p in projects:
        v = _num(p.get("pledged_usd"))
        if v < 0 or v != v:
            bad_pledged.append(p)
    if bad_pledged:
        issues.append(f"{len(bad_pledged)} projects have negative/NaN pledged_usd")

    # Duplicate pathnames — discover dedup broke
    pathnames = [p.get("pathname") for p in projects if p.get("pathname")]
    if len(pathnames) != len(set(pathnames)):
        dupes = len(pathnames) - len(set(pathnames))
        issues.append(f"{dupes} duplicate pathnames in snapshot — discover dedup may have broken")

    # Followers coverage — this catches today's exact failure mode
    n_with_f = sum(1 for p in projects if (p.get("followers") or 0) > 0)
    f_cov = n_with_f / n
    if f_cov < 0.30:
        issues.append(
            f"followers coverage {f_cov:.0%} ({n_with_f}/{n}); likely watchers GraphQL was blocked"
        )

    # All live projects must have SOME backers in aggregate (catches
    # 'pledged field stripped' or 'all live mis-classified' bugs)
    live = [p for p in projects if p.get("status") == "live"]
    if live:
        live_with_backers = sum(1 for p in live if (p.get("backers") or 0) > 0)
        if live_with_backers < len(live) * 0.50:
            issues.append(
                f"only {live_with_backers}/{len(live)} live projects have backers > 0; "
                f"Discover JSON shape may have changed"
            )
        live_usd_total = sum(float(p.get("pledged_usd") or 0) for p in live)
        if live_usd_total == 0:
            issues.append("all live projects sum to $0 pledged (impossible — abort)")

    # ── Comparative drift (vs yesterday) — only if prev exists ────
    # Sanity check the prev itself first: if its timestamp is AFTER curr,
    # find_prev_snapshot picked the wrong file (history listing got
    # ordered weird, or there's a future-dated snapshot). Don't trust
    # the comparison — but proceed with the absolute checks above.
    if prev:
        try:
            curr_ts = curr.get("generated_at", "")
            prev_ts = prev.get("generated_at", "")
            if prev_ts and curr_ts and prev_ts >= curr_ts:
                issues.append(
                    f"prev snapshot timestamp {prev_ts} >= curr {curr_ts} — "
                    f"history ordering broken; skipping comparative checks"
                )
                prev = None
        except Exception:
            pass

    if prev:
        prev_projects = prev.get("projects") or []
        prev_n = len(prev_projects)

        # Catastrophic project count drop
        if prev_n >= 50:
            ratio = n / prev_n
            if ratio < 0.70:
                issues.append(
                    f"project count dropped {prev_n} → {n} ({ratio:.0%}); "
                    f"discover seed pages likely got 403'd"
                )

        # Catastrophic live-USD drop (one big project ending is fine,
        # half the portfolio vanishing isn't)
        if live:
            prev_live = [p for p in prev_projects if p.get("status") == "live"]
            prev_live_usd = sum(float(p.get("pledged_usd") or 0) for p in prev_live)
            curr_live_usd = sum(float(p.get("pledged_usd") or 0) for p in live)
            if prev_live_usd > 100_000:
                ratio = curr_live_usd / prev_live_usd if prev_live_usd else 1
                if ratio < 0.30:
                    issues.append(
                        f"live USD crashed ${prev_live_usd:,.0f} → ${curr_live_usd:,.0f} "
                        f"({ratio:.0%}); pledged field may have stripped"
                    )

        # Followers identity check — if today's watchers all match
        # yesterday's exactly, the fallback kicked in and Δ values
        # will all be 0. Not a block, but warn so the owner knows
        # the email won't have meaningful Δ this round.
        if prev_n and n:
            prev_f_by_path = {
                p.get("pathname"): p.get("followers")
                for p in prev_projects if p.get("pathname")
            }
            same = sum(
                1 for p in projects
                if p.get("pathname") in prev_f_by_path
                and p.get("followers") == prev_f_by_path[p.get("pathname")]
            )
            if same > n * 0.85:
                issues.append(
                    f"followers identical to yesterday for {same}/{n} projects — "
                    f"watchers likely fell back to previous snapshot. "
                    f"Δ deltas in email will read 0; broadcasting anyway."
                )
                # NOTE: this issue is informational, not blocking.
                # See logic below — we still allow if this is the only issue.

    # ── Decide ─────────────────────────────────────────────────────
    # Block list: anything except the "followers identical" warning is hard-blocking.
    blocking = [i for i in issues if "broadcasting anyway" not in i]
    return (len(blocking) == 0), issues


def format_alert_body(issues: list[str], snapshot_meta: dict) -> str:
    """Human-readable alert body for owner email when broadcast is blocked."""
    lines = [
        "Today's KS Tracker broadcast was BLOCKED by the sanity gate.",
        "",
        "Issues:",
    ]
    for i in issues:
        lines.append(f"  - {i}")
    lines += [
        "",
        f"Generated at: {snapshot_meta.get('generated_at', '?')}",
        f"Total projects: {len(snapshot_meta.get('projects') or [])}",
        "",
        "What was sent: NOTHING. No subscribers received today's edition.",
        "What to do:",
        "  1. Open https://ks.aldrich.fyi/ and check it visually",
        "  2. If data looks fine: re-run `gh workflow run scrape.yml --repo Chen17-sq/kickstarter-china-tracker`",
        "     after deleting today's history file (so the idempotency guard re-fires)",
        "  3. If data is genuinely broken: investigate the scraper logs",
        "",
        "— sanity gate, scraper/sanity.py",
    ]
    return "\n".join(lines)
