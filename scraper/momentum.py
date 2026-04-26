"""Compute per-project momentum (Δ since previous snapshot).

Reads `data/history/*.json`, finds the second-most-recent snapshot, and
mutates the current `rows` in-place to add three delta fields:
  - delta_followers       (int, can be negative if people unfollow)
  - delta_backers         (int)
  - delta_pledged_usd     (float)
  - delta_seconds         (int — seconds elapsed since the prev snapshot;
                           lets the front-end label '24h Δ' vs '4h Δ')

Under daily cron, prev snapshot is ~24h old. Under more frequent cron,
it's whatever the previous run was.

Top-movers rankings are also exposed for the report / email / front-page
'BREAKING' module:
  - top_movers_followers  → list of (slug, delta) sorted desc
  - top_movers_pledged
  - top_movers_backers
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORY = REPO_ROOT / "data" / "history"


def find_prev_snapshot() -> tuple[dict | None, dt.datetime | None]:
    """Return (snapshot_dict, snapshot_timestamp) for the most recent history file.

    Designed to be called from scraper.run BEFORE the current run writes its
    own snapshot — so `snaps[-1]` is the previous run, not the current.
    """
    if not HISTORY.exists():
        return None, None
    snaps = sorted(HISTORY.glob("*.json"))
    if not snaps:
        return None, None
    prev_path = snaps[-1]
    try:
        ts = dt.datetime.strptime(prev_path.stem, "%Y-%m-%dT%H-%M-%SZ").replace(
            tzinfo=dt.timezone.utc
        )
    except ValueError:
        ts = None
    try:
        return json.loads(prev_path.read_text(encoding="utf-8")), ts
    except Exception:
        return None, None


def compute_deltas(rows: list[dict]) -> dict:
    """Mutate `rows` in-place to add delta_* fields. Returns top-movers summary.

    Returns a dict:
      {
        "prev_at": "2026-04-25T05:28:09Z" or None,
        "delta_seconds": int or None,
        "top_followers": [(pathname, delta), ...],
        "top_pledged":   [(pathname, delta), ...],
        "top_backers":   [(pathname, delta), ...],
      }
    """
    prev, prev_ts = find_prev_snapshot()
    summary: dict = {
        "prev_at": prev.get("generated_at") if prev else None,
        "delta_seconds": None,
        "top_followers": [],
        "top_pledged": [],
        "top_backers": [],
    }
    if prev is None:
        return summary

    if prev_ts:
        summary["delta_seconds"] = int(
            (dt.datetime.now(dt.timezone.utc) - prev_ts).total_seconds()
        )

    prev_by_path = {
        p["pathname"]: p
        for p in prev.get("projects", [])
        if p.get("pathname")
    }

    f_movers: list[tuple[str, int]] = []
    p_movers: list[tuple[str, float]] = []
    b_movers: list[tuple[str, int]] = []

    for r in rows:
        path = r.get("pathname")
        prev_p = prev_by_path.get(path)
        if prev_p is None:
            continue

        # Follower delta
        cf, pf = r.get("followers"), prev_p.get("followers")
        if cf is not None and pf is not None:
            try:
                d = int(cf) - int(pf)
                r["delta_followers"] = d
                if d != 0:
                    f_movers.append((path, d))
            except (TypeError, ValueError):
                pass

        # Backer delta
        cb, pb = r.get("backers"), prev_p.get("backers")
        if cb is not None and pb is not None:
            try:
                d = int(cb) - int(pb)
                r["delta_backers"] = d
                if d != 0:
                    b_movers.append((path, d))
            except (TypeError, ValueError):
                pass

        # Pledged delta
        try:
            cp = float(r.get("pledged_usd") or 0)
            pp = float(prev_p.get("pledged_usd") or 0)
            d = cp - pp
            r["delta_pledged_usd"] = d
            if abs(d) > 0.01:
                p_movers.append((path, d))
        except (TypeError, ValueError):
            pass

    f_movers.sort(key=lambda x: -x[1])
    p_movers.sort(key=lambda x: -x[1])
    b_movers.sort(key=lambda x: -x[1])
    summary["top_followers"] = f_movers[:5]
    summary["top_pledged"] = p_movers[:5]
    summary["top_backers"] = b_movers[:5]
    return summary


# ── Display-layer derivations (shared with site/app.js logic) ────────

def conversion_per_watcher(p: dict) -> float | None:
    """USD raised per pre-launch watcher. Useful for live + ended projects."""
    try:
        followers = int(p.get("followers") or 0)
        pledged = float(p.get("pledged_usd") or 0)
        if followers <= 0:
            return None
        return pledged / followers
    except (TypeError, ValueError):
        return None


def conversion_per_backer(p: dict) -> float | None:
    """Average pledge per backer."""
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
    if p.get("status") != "live":
        return None
    try:
        launched_at = float(p.get("launched_at") or 0)
        deadline = float(p.get("deadline") or 0)
        pledged = float(p.get("pledged_usd") or 0)
    except (TypeError, ValueError):
        return None
    if launched_at <= 0 or deadline <= launched_at:
        return None
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    days_in = (now - launched_at) / 86400
    total_days = (deadline - launched_at) / 86400
    if days_in <= 0.5:  # too early to project
        return None
    return (pledged / days_in) * total_days
