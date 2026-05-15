"""Per-project anomaly detection — surfaces things the owner should know
about but that aren't bad enough to block the broadcast.

Three classes of anomaly:
  vanished — was in yesterday's snapshot, isn't in today's. Most common
             cause: project finished its campaign and was unpublished
             by the creator, OR it was removed by KS. Worth checking.
  reverted — followers dropped >50% vs yesterday. Real causes: KS pruned
             bot followers from the count, creator unpublished + reposted,
             or our scraper's classifier inconsistently included it. Rare.
  stuck    — live project whose pledged_usd hasn't moved in 7+ days. Owner
             may want to remove from "live" carousel since it's effectively
             stalled. (Note: KS doesn't auto-fail a campaign until deadline,
             so the project stays "live" even with zero movement.)

Output: emit a JSON blob to `data/.anomalies.json` that email_notify
reads into the OPS digest. Block list (sanity.py) is NOT modified —
these are FYI signals, not broadcast-stopping issues.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORY = REPO_ROOT / "data" / "history"
ANOMALIES_PATH = REPO_ROOT / "data" / ".anomalies.json"

# A project must have had ≥10 followers yesterday for a follower-drop
# anomaly to count — single-digit drops are noise.
REVERTED_FOLLOWERS_FLOOR = 10
REVERTED_DROP_RATIO = 0.50  # ≥50% drop = anomaly

# A live project that hasn't moved in this many DAYS is "stuck".
STUCK_DAYS = 7


def _num(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _load_history_snapshot(n_back: int) -> Optional[dict]:
    """Return the n-th-most-recent history snapshot (n_back=1 = yesterday)."""
    if not HISTORY.exists():
        return None
    snaps = sorted(HISTORY.glob("*.json"))
    if len(snaps) < n_back:
        return None
    try:
        return json.loads(snaps[-n_back].read_text(encoding="utf-8"))
    except Exception:
        return None


def detect(curr: dict, prev: Optional[dict] = None) -> dict:
    """Run all anomaly detectors over curr (today) vs prev (yesterday).

    Returns:
        {
          "vanished": [{pathname, title, status, last_followers}, ...],
          "reverted": [{pathname, title, prev_followers, curr_followers}, ...],
          "stuck":    [{pathname, title, pledged_usd, days_unchanged}, ...],
          "_meta": {generated_at, prev_at}
        }
    """
    out: dict = {
        "vanished": [],
        "reverted": [],
        "stuck": [],
        "_meta": {
            "generated_at": dt.datetime.now(dt.UTC).isoformat(),
            "prev_at": None,
        },
    }
    if prev is None:
        return out
    out["_meta"]["prev_at"] = prev.get("generated_at")

    curr_by_path = {
        p.get("pathname"): p for p in (curr.get("projects") or []) if p.get("pathname")
    }
    prev_by_path = {
        p.get("pathname"): p for p in (prev.get("projects") or []) if p.get("pathname")
    }

    # ── vanished: in prev but not curr ────────────────────────────
    for path, prev_p in prev_by_path.items():
        if path in curr_by_path:
            continue
        # If the project was 'successful' or 'failed' yesterday, vanishing is
        # expected — creator usually unpublishes after the campaign ends.
        # Skip those (they're not interesting anomalies).
        prev_status = prev_p.get("status")
        if prev_status in ("successful", "failed"):
            continue
        out["vanished"].append({
            "pathname": path,
            "title": prev_p.get("title") or "?",
            "status": prev_status or "?",
            "last_followers": prev_p.get("followers"),
        })

    # ── reverted: follower count cratered ────────────────────────
    for path, curr_p in curr_by_path.items():
        prev_p = prev_by_path.get(path)
        if not prev_p:
            continue
        pf = _num(prev_p.get("followers"))
        cf = _num(curr_p.get("followers"))
        if pf < REVERTED_FOLLOWERS_FLOOR:
            continue
        if cf < pf * (1 - REVERTED_DROP_RATIO):
            out["reverted"].append({
                "pathname": path,
                "title": curr_p.get("title") or "?",
                "prev_followers": int(pf),
                "curr_followers": int(cf),
            })

    # ── stuck: live project, pledged hasn't moved across N days ──
    # Reach back N history snapshots to compare
    week_old = _load_history_snapshot(STUCK_DAYS)
    if week_old:
        week_by_path = {
            p.get("pathname"): p
            for p in (week_old.get("projects") or [])
            if p.get("pathname")
        }
        for path, curr_p in curr_by_path.items():
            if curr_p.get("status") != "live":
                continue
            wp = week_by_path.get(path)
            if not wp:
                continue
            curr_pledged = _num(curr_p.get("pledged_usd"))
            week_pledged = _num(wp.get("pledged_usd"))
            # Stuck = literally zero movement (within $1) AND >=$100 baseline
            if curr_pledged >= 100 and abs(curr_pledged - week_pledged) < 1.0:
                out["stuck"].append({
                    "pathname": path,
                    "title": curr_p.get("title") or "?",
                    "pledged_usd": curr_pledged,
                    "days_unchanged": STUCK_DAYS,
                })

    return out


def save(anomalies: dict) -> Path:
    ANOMALIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    ANOMALIES_PATH.write_text(json.dumps(anomalies, indent=2), encoding="utf-8")
    return ANOMALIES_PATH


def load() -> Optional[dict]:
    if not ANOMALIES_PATH.exists():
        return None
    try:
        return json.loads(ANOMALIES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def format_digest_lines(anomalies: dict | None) -> list[str]:
    """Return plaintext lines for the OPS digest. Empty list if nothing."""
    if not anomalies:
        return []
    v, r, s = anomalies.get("vanished") or [], anomalies.get("reverted") or [], anomalies.get("stuck") or []
    if not (v or r or s):
        return []
    out = ["Anomalies (FYI — broadcast not blocked):"]
    if v:
        out.append(f"  vanished:  {len(v)} project(s) gone from discovery — first few:")
        for p in v[:5]:
            out.append(f"    · {p.get('title','?')[:55]:55} (was {p.get('status','?')}, {p.get('last_followers') or 0} followers)")
        if len(v) > 5:
            out.append(f"    · …and {len(v)-5} more")
    if r:
        out.append(f"  reverted:  {len(r)} project(s) lost >50% followers — first few:")
        for p in r[:5]:
            out.append(f"    · {p.get('title','?')[:55]:55} ({p.get('prev_followers')} → {p.get('curr_followers')})")
    if s:
        out.append(f"  stuck:     {len(s)} live project(s) with $0 movement in {STUCK_DAYS} days — first few:")
        for p in s[:5]:
            out.append(f"    · {p.get('title','?')[:55]:55} (${p.get('pledged_usd',0):,.0f} unchanged)")
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("usage: python -m scraper.anomalies <curr.json> <prev.json>")
        sys.exit(1)
    curr = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    prev = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    result = detect(curr, prev)
    print(json.dumps(result, indent=2))
