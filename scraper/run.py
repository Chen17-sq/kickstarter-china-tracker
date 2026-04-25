"""End-to-end scrape pipeline — invoked by GitHub Actions cron.

Architecture:
  1. Crawl Discover seeds via the JSON API → DiscoverHit per project, with
     name/creator/location/country/state/pledged/backers/staff_pick/...
  2. Classify each hit; keep those scored 高 or 中 for China background.
  3. For prelaunch projects (state in {submitted, started}), fetch the project
     page to extract `followers` — the key prelaunch metric, missing from the
     Discover JSON.
  4. Write snapshots: data/projects.json (everything), data/prelaunch.json,
     data/live.json, data/history/<ts>.json.
  5. Diff vs the previous history snapshot → CHANGELOG.md (consumed by notify).

Safety: if Discover returns 0 candidates or all China-matches are < a hard
floor (likely Cloudflare blocking the runner), refuse to overwrite the live
projects.json. We still write a history snapshot for forensics.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from .http import RateLimiter
from .discover import crawl_discover, DiscoverHit
from .classify import classify
from .diff import diff_snapshots, changes_to_markdown

# TODO(followers): KS prelaunch pages don't include the follower count in SSR
# HTML — it's fetched client-side via GraphQL after page mount. Two paths to
# get it: (a) reverse-engineer the GraphQL query (needs CSRF token rotation),
# or (b) drive a headless Playwright in CI. Both are non-trivial. For now we
# emit followers=None for prelaunch projects; everything else (status, pledge,
# backers, PWL, deadline, location) comes through cleanly via Discover JSON.

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "data"
HISTORY = DATA / "history"

# If China-matched count drops below this floor, treat the run as compromised
# (likely Cloudflare blocked the runner, KS changed schema, etc.) and do NOT
# overwrite the live data files. The history snapshot is still written so we
# can diagnose afterwards. Tune via env var KS_MIN_KEPT.
MIN_KEPT_FLOOR = int(os.environ.get("KS_MIN_KEPT", "20"))

PRELAUNCH_STATES = {"submitted", "started"}
LIVE_STATES = {"live"}
ENDED_STATES = {"successful", "failed", "canceled", "suspended"}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_status(state: str | None) -> str:
    if state in PRELAUNCH_STATES:
        return "prelaunch"
    if state in LIVE_STATES:
        return "live"
    if state == "successful":
        return "successful"
    if state == "failed":
        return "failed"
    if state in {"canceled", "suspended"}:
        return state
    return "unknown"


def build_row(hit: DiscoverHit, *, followers: int | None,
              confidence: str, reason: str,
              matched_brand: str | None, matched_brand_zh: str | None) -> dict:
    status = normalize_status(hit.state)
    return {
        "pathname": hit.pathname,
        "url": hit.url,
        "title": hit.title,
        "blurb": hit.blurb,
        "creator": hit.creator_name,  # alias for site/app.js compatibility
        "creator_slug": hit.creator_slug,
        "creator_name": hit.creator_name,
        "location": hit.location,
        "country": hit.country,
        "category": hit.category,
        "status": status,
        "raw_state": hit.state,
        "project_we_love": hit.staff_pick,
        "followers": followers,
        "backers": hit.backers_count,
        "pledged_usd": hit.pledged_usd,
        "goal_usd": hit.goal_usd,
        "percent_funded": hit.percent_funded,
        "deadline": hit.deadline,
        "launched_at": hit.launched_at,
        "created_at": hit.created_at,
        "prelaunch_activated": hit.prelaunch_activated,
        "china_confidence": confidence,
        "china_reason": reason,
        "matched_brand": matched_brand,
        "matched_brand_zh": matched_brand_zh,
    }


def run() -> int:
    started = now_iso()
    print(f"[{started}] crawl discover ...")
    hits = crawl_discover()
    print(f"  → {len(hits)} candidate projects")

    if not hits:
        print("FATAL: zero discovered. Likely Cloudflare blocked all seeds. Aborting write.", file=sys.stderr)
        return 1

    rows: list[dict] = []
    for path, hit in hits.items():
        cls = classify(creator_slug=hit.creator_slug, location=hit.location, title=hit.title)
        if cls.confidence not in ("高", "中"):
            continue
        rows.append(build_row(
            hit,
            followers=None,  # see TODO(followers) at top of file
            confidence=cls.confidence,
            reason=cls.reason,
            matched_brand=cls.matched_brand,
            matched_brand_zh=cls.matched_brand_zh,
        ))
    print(f"  classified {len(rows)} as China-background")

    finished = now_iso()
    out = {
        "generated_at": finished,
        "started_at": started,
        "total_candidates": len(hits),
        "kept": len(rows),
        "projects": rows,
    }

    DATA.mkdir(parents=True, exist_ok=True)
    HISTORY.mkdir(parents=True, exist_ok=True)

    # Always write the history snapshot — useful for debugging even when the
    # main file is locked behind the safety guard.
    snap_path = HISTORY / f"{finished.replace(':', '-')}.json"
    snap_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    if len(rows) < MIN_KEPT_FLOOR:
        print(f"WARN: kept {len(rows)} < floor {MIN_KEPT_FLOOR}. "
              f"Refusing to overwrite data/projects.json. "
              f"History snapshot still written to {snap_path.name}.",
              file=sys.stderr)
        return 2

    (DATA / "projects.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    for slice_status in ("prelaunch", "live"):
        sub = {**out, "projects": [r for r in rows if r["status"] == slice_status]}
        (DATA / f"{slice_status}.json").write_text(json.dumps(sub, ensure_ascii=False, indent=2), encoding="utf-8")

    # Diff vs the second-newest snapshot in history
    snaps = sorted(HISTORY.glob("*.json"))
    if len(snaps) >= 2:
        try:
            prev = json.loads(snaps[-2].read_text(encoding="utf-8"))
            diffs = diff_snapshots(prev, out)
            if diffs:
                (REPO_ROOT / "CHANGELOG.md").write_text(
                    changes_to_markdown(diffs), encoding="utf-8"
                )
                print(f"  wrote CHANGELOG.md with {len(diffs)} changes")
            else:
                print("  no changes since last run")
        except Exception as e:
            print(f"  diff skipped: {e}")

    print(f"done. kept {len(rows)}/{len(hits)}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
