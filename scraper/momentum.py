"""Compute only observation-backed daily and weekly changes (including true zero)."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .observations import clear_deltas, comparable_delta, is_fresh, parse_time

REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORY = REPO_ROOT / "data" / "history"


def _nearest(days, now=None):
    now = now or dt.datetime.now(dt.UTC)
    target = now - dt.timedelta(days=days)
    candidates = []
    for path in HISTORY.glob("*.json"):
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            ts = parse_time(snapshot.get("generated_at"))
            if ts is None:
                ts = dt.datetime.strptime(path.stem, "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=dt.UTC)
            tolerance = dt.timedelta(hours=6 if days == 1 else 12)
            if ts < now and abs(ts - target) <= tolerance:
                candidates.append((abs(ts - target), ts, snapshot))
        except (ValueError, OSError):
            continue
    if not candidates:
        return None, None
    _, ts, snapshot = min(candidates, key=lambda item: item[0])
    return snapshot, ts


def find_prev_snapshot():
    return _nearest(1)


def find_week_ago_snapshot():
    return _nearest(7)


def _compute(rows, ref, ref_ts, days, now=None):
    now = now or dt.datetime.now(dt.UTC)
    prefix = "weekly_delta_" if days == 7 else "delta_"
    by_path = {}
    snapshots = [ref] if ref else []
    # A failed attempt nearest the target must not hide a successful rerun
    # from the same window. The field's own observation time decides validity.
    for path in sorted(HISTORY.glob("*.json")):
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
            at = parse_time(snap.get("generated_at"))
            if at and now - dt.timedelta(days=days, hours=18) <= at < now:
                snapshots.append(snap)
        except (ValueError, OSError):
            continue
    for snapshot in snapshots:
        for baseline in snapshot.get("projects", []):
            by_path.setdefault(baseline.get("pathname"), []).append(baseline)
    movers = {k: [] for k in ("followers", "backers", "pledged")}
    for row in rows:
        # Re-runs must never retain deltas copied from an earlier snapshot.
        old_meta = row.get("delta_meta", {}).copy()
        clear_deltas(row, prefix)
        row["delta_meta"] = {k: v for k, v in old_meta.items() if not k.startswith(prefix)}
        for key in ("followers", "backers", "pledged_usd"):
            candidates = [comparable_delta(row, baseline, key, days=days, now=now)
                          for baseline in by_path.get(row.get("pathname"), [{}])]
            valid = [item for item in candidates if item[0] is not None]
            value, evidence = (min(valid, key=lambda item: abs(item[1]["seconds"] - days * 86400))
                               if valid else candidates[0])
            row[prefix + key] = value
            row["delta_meta"][prefix + key] = evidence
            if value is not None and value > 0:
                movers[key.replace("_usd", "")].append((row.get("pathname"), value))
    summary = {"ref_at" if days == 7 else "prev_at": (ref or {}).get("generated_at")}
    summary["age_days" if days == 7 else "delta_seconds"] = (
        (now - ref_ts).total_seconds() / (86400 if days == 7 else 1) if ref_ts else None)
    for key, values in movers.items():
        summary[("top_weekly_" if days == 7 else "top_") + key] = sorted(values, key=lambda v: -v[1])[:10 if days == 7 else 5]
    return summary


def compute_deltas(rows, *, now=None):
    ref, ts = _nearest(1, now) if now else find_prev_snapshot()
    return _compute(rows, ref, ts, 1, now)


def compute_weekly_deltas(rows, *, now=None):
    ref, ts = _nearest(7, now) if now else find_week_ago_snapshot()
    return _compute(rows, ref, ts, 7, now)


# ── Display-layer derivations (shared with site/app.js logic) ────────

def conversion_per_watcher(p: dict) -> float | None:
    """USD raised per pre-launch watcher. Useful for live + ended projects."""
    if not is_fresh(p, "followers") or not is_fresh(p, "pledged_usd"):
        return None
    try:
        followers = int(p.get("followers") or 0)
        pledged = float(p.get("pledged_usd") or 0)
        if followers <= 0:
            return None
        return pledged / followers
    except (TypeError, ValueError):
        return None


def conversion_per_backer(p: dict) -> float | None:
    """Average pledge per backer from fresh comparable current metrics."""
    if not is_fresh(p, "backers") or not is_fresh(p, "pledged_usd"):
        return None
    try:
        backers = int(p.get("backers") or 0)
        pledged = float(p.get("pledged_usd") or 0)
        if backers <= 0:
            return None
        return pledged / backers
    except (TypeError, ValueError):
        return None


def top_movers_from_rows(rows: list[dict], key: str, n: int = 3) -> list[dict]:
    """Return top N rows where row[key] > 0, sorted desc by row[key]."""
    items = [r for r in rows if (r.get(key) or 0) > 0]
    items.sort(key=lambda r: -(r.get(key) or 0))
    return items[:n]


def projected_total(p: dict) -> float | None:
    """Naïve linear projection for live projects: $/day × total campaign days.

    Real KS curves are front-loaded (Day 1 spike), middle-quiet, end-spike
    — this estimate over-projects in the early phase. Treat as upper bound.
    Returns None for non-live projects.
    """
    if p.get("status") != "live" or not is_fresh(p, "pledged_usd"):
        return None
    try:
        launched_at = float(p.get("launched_at") or 0)
        deadline = float(p.get("deadline") or 0)
        pledged = float(p.get("pledged_usd") or 0)
    except (TypeError, ValueError):
        return None
    if launched_at <= 0 or deadline <= launched_at:
        return None
    now = dt.datetime.now(dt.UTC).timestamp()
    days_in = (now - launched_at) / 86400
    total_days = (deadline - launched_at) / 86400
    if days_in <= 0.5:  # too early to project
        return None
    return (pledged / days_in) * total_days
