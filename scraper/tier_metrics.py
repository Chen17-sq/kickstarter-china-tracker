"""Adaptive tier metrics — learn which transport tier works recently.

Each cron run records the tier (curl_cffi / playwright / nodriver /
failed) that ACTUALLY carried the data for each fetch path (watches,
pledge, refresh). Aggregated across days, we can answer:

  "Has Tier 1 (curl_cffi) been failing for the last 3 days? Then
  maybe skip the optimistic retries and go straight to Tier 2."

  "Did Tier 3 (nodriver) succeed yesterday when nothing else worked?
  Bump its priority."

This module exposes:
  - record(path, tier) — call after each successful fetch
  - rolling_stats() — return per-tier success rate over last N days
  - recommended_tier(path) — return suggested first-try tier for path

History file: `data/.tier_metrics.json` (gitignored). Bounded to last
N=30 days; older entries auto-pruned.

This is the LEARNING layer — without it, every run starts with the
hardcoded "try Tier 1 first" rule even when Tier 1 has been blocked
for a week. With it, we adapt automatically.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
METRICS_FILE = REPO_ROOT / "data" / ".tier_metrics.json"

# Rolling window for "recent" stats
WINDOW_DAYS = 30
# Recommended-tier decision threshold — if a tier's success rate over
# WINDOW_DAYS is below this, we skip it on first try.
MIN_SUCCESS_RATE = 0.40

# Known tiers (must match what project.py sets as Transport.mode)
KNOWN_TIERS = ("curl_cffi", "playwright", "patchright", "nodriver", "failed")


def _load_raw() -> dict:
    if not METRICS_FILE.exists():
        return {"days": {}}
    try:
        d = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
        if "days" not in d:
            d["days"] = {}
        return d
    except Exception:
        return {"days": {}}


def _save_raw(d: dict) -> None:
    try:
        METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        METRICS_FILE.write_text(
            json.dumps(d, indent=2), encoding="utf-8"
        )
    except Exception:
        # Persistence is opportunistic — never block the scrape on it
        pass


def _prune_old(d: dict) -> dict:
    cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=WINDOW_DAYS)).strftime(
        "%Y-%m-%d"
    )
    d["days"] = {k: v for k, v in d.get("days", {}).items() if k >= cutoff}
    return d


def record(path: str, tier: str) -> None:
    """Log that `path` succeeded via `tier` today.

    `path` is the logical fetch label: "watches", "pledge", "refresh",
    "discover", etc. `tier` is the Transport.mode that won.
    """
    if not tier:
        tier = "failed"
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    d = _prune_old(_load_raw())
    day = d["days"].setdefault(today, {})
    path_stats = day.setdefault(path, {})
    path_stats[tier] = path_stats.get(tier, 0) + 1
    _save_raw(d)


def rolling_stats(*, window_days: int = WINDOW_DAYS) -> dict:
    """Return per-path-per-tier counts over the last `window_days`.

    Shape:
      {
        path: {
          tier: count,
          ...
          "_total": sum,
          "_success_rate": float (excludes 'failed' tier),
        },
        ...
      }
    """
    cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=window_days)).strftime(
        "%Y-%m-%d"
    )
    d = _load_raw()
    aggregated: dict[str, dict[str, int]] = {}
    for day_str, day_data in d.get("days", {}).items():
        if day_str < cutoff:
            continue
        for path, tier_counts in day_data.items():
            agg = aggregated.setdefault(path, {})
            for tier, count in tier_counts.items():
                agg[tier] = agg.get(tier, 0) + count

    # Compute totals + success rates
    for agg in aggregated.values():
        total = sum(agg.values())
        success = sum(v for k, v in agg.items() if k != "failed")
        agg["_total"] = total
        agg["_success_rate"] = success / total if total else 0.0
    return aggregated


def recommended_tier(path: str) -> str | None:
    """Suggest which tier to try FIRST for the given path, based on
    recent history. Returns None when we have no data or no strong
    signal (in which case the caller should use the default order).

    Logic:
      - If Tier 1 (curl_cffi) succeeded for `path` ≥ MIN_SUCCESS_RATE
        of the time over the window: recommend curl_cffi (default).
      - If Tier 1 failed most of the time but Tier 2/3 succeeded:
        recommend the highest-rate winning tier.
      - Otherwise None (fall back to hardcoded ladder).
    """
    stats = rolling_stats()
    path_stats = stats.get(path)
    if not path_stats:
        return None
    total = path_stats.get("_total", 0)
    if total < 5:
        return None  # too little data to be confident
    cc_rate = path_stats.get("curl_cffi", 0) / total
    if cc_rate >= MIN_SUCCESS_RATE:
        return "curl_cffi"
    # Tier 1 is degraded — pick the best of 2/3
    best_tier = None
    best_count = 0
    for t in ("nodriver", "patchright", "playwright"):
        c = path_stats.get(t, 0)
        if c > best_count:
            best_count = c
            best_tier = t
    return best_tier


def format_digest_lines(*, window_days: int = 7) -> list[str]:
    """Return human-readable lines for the OPS digest summarizing
    recent tier-level performance. Empty when no data."""
    stats = rolling_stats(window_days=window_days)
    if not stats:
        return []
    out = [f"Tier metrics (last {window_days} days):"]
    for path in sorted(stats.keys()):
        s = stats[path]
        total = s.get("_total", 0)
        if total == 0:
            continue
        # Render as: "watches: 7d=12 · curl_cffi 9/12 · playwright 2/12 · failed 1/12"
        parts = [f"7d={total}"]
        for tier in KNOWN_TIERS:
            v = s.get(tier, 0)
            if v > 0:
                parts.append(f"{tier} {v}/{total}")
        out.append(f"  {path:10}: {' · '.join(parts)}")
    return out
