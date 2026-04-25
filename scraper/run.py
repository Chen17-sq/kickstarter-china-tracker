"""End-to-end scrape pipeline — invoked by GitHub Actions cron.

Steps:
  1. Crawl Discover seeds → set of project pathnames.
  2. For each pathname, fetch project page → snapshot.
  3. Classify China background.
  4. Filter to china_confidence ∈ {高, 中}.
  5. Write data/projects.json + slice files (prelaunch/live/recently_ended).
  6. Write a timestamped snapshot under data/history/.
  7. Write CHANGELOG.md (diff vs previous snapshot, used by notify.py).
"""
from __future__ import annotations
import datetime as dt
import json
import os
from dataclasses import asdict
from pathlib import Path

from .http import make_client, RateLimiter
from .discover import crawl_discover
from .project import fetch_project
from .classify import classify
from .diff import diff_snapshots, changes_to_markdown

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "data"
HISTORY = DATA / "history"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run() -> None:
    started = now_iso()
    print(f"[{started}] crawl discover ...")
    hits = crawl_discover()
    print(f"  → {len(hits)} candidate projects")

    pacer = RateLimiter(qps=1.0)
    rows: list[dict] = []
    with make_client() as client:
        for i, (path, hit) in enumerate(hits.items(), 1):
            pacer.wait()
            try:
                snap = fetch_project(path, client=client)
            except Exception as e:
                print(f"  [{i}] FAIL {path}: {e}")
                continue
            cls = classify(creator_slug=snap.creator, location=snap.location, title=snap.title)
            if cls.confidence not in ("高", "中"):
                continue
            row = asdict(snap)
            row["china_confidence"] = cls.confidence
            row["china_reason"] = cls.reason
            row["matched_brand"] = cls.matched_brand
            rows.append(row)
            if i % 25 == 0:
                print(f"  [{i}/{len(hits)}] kept {len(rows)} so far")

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
    (DATA / "projects.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    for slice_status in ("prelaunch", "live"):
        sub = {**out, "projects": [r for r in rows if r["status"] == slice_status]}
        (DATA / f"{slice_status}.json").write_text(json.dumps(sub, ensure_ascii=False, indent=2), encoding="utf-8")

    snap_path = HISTORY / f"{finished.replace(':', '-')}.json"
    snap_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # Diff vs the second-newest snapshot in history
    snaps = sorted(HISTORY.glob("*.json"))
    if len(snaps) >= 2:
        prev = json.loads(snaps[-2].read_text(encoding="utf-8"))
        diffs = diff_snapshots(prev, out)
        if diffs:
            (REPO_ROOT / "CHANGELOG.md").write_text(changes_to_markdown(diffs), encoding="utf-8")
            print(f"  wrote CHANGELOG.md with {len(diffs)} changes")
        else:
            print("  no changes since last run")

    print(f"done. kept {len(rows)}/{len(hits)}")


if __name__ == "__main__":
    run()
