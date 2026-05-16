"""Public JSON API surface — slim, stable, documented.

Why a separate API output and not just `data/projects.json`?
  - The internal data file is whatever shape the scraper happens to
    emit today; breaking changes are routine.
  - The API output is the explicit promise to outside consumers
    (Slack bots, dashboards, mirror sites, partner scrapers). Keep
    the schema stable so they don't break when we refactor internals.

Layout on disk:
  site/api/today.json        — alias for the latest day
  site/api/<YYYY-MM-DD>.json — same payload, per-date
  site/api/index.json        — list of available dates + meta

Schema (versioned via top-level `schema_version`):
  {
    "schema_version": 1,
    "generated_at": "2026-05-15T02:00:00Z",
    "edition": 21,
    "counts": {"prelaunch": 86, "live": 76, "successful": 72, "failed": 0,
               "total": 234, "pwl": 59},
    "total_live_usd": 33250000.0,
    "projects": [
      {
        "pathname": "/projects/.../widget",
        "title": "...",
        "blurb_zh": "...",        # may be empty
        "status": "live",
        "url": "https://www.kickstarter.com/...",
        "country": "CN",
        "creator": "...",
        "followers": 1234,
        "backers": 567,
        "pledged_usd": 89000.0,
        "goal_usd": 50000.0,
        "percent_funded": 178,
        "deadline": "2026-06-01T12:00:00Z",
        "launched_at": "2026-04-15T12:00:00Z",
        "project_we_love": true,
        "china_confidence": "高",
        "delta_followers": 12,
        "delta_backers": 4,
        "delta_pledged_usd": 1200.0
      },
      ...
    ]
  }

We DELIBERATELY omit some fields from data/projects.json:
  - photo (large URL strings, fluctuating)
  - blurb (English, often redundant with blurb_zh)
  - matched_brand / matched_brand_zh (internal classifier hint)
  - Anything starting with _ (private)
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from ._common import edition_number

REPO_ROOT = Path(__file__).resolve().parent.parent
API_DIR = REPO_ROOT / "site" / "api"
SCHEMA_VERSION = 1

# Whitelist of project fields exposed in the public API.
# Adding a field is safe; removing one is a breaking change.
PUBLIC_PROJECT_FIELDS = [
    "pathname",
    "title",
    "blurb_zh",
    "status",
    "url",
    "country",
    "creator",
    "followers",
    "backers",
    "pledged_usd",
    "goal_usd",
    "percent_funded",
    "deadline",
    "launched_at",
    "project_we_love",
    "china_confidence",
    "delta_followers",
    "delta_backers",
    "delta_pledged_usd",
]


def _slim_project(p: dict) -> dict:
    """Return only the whitelisted fields, dropping internals."""
    return {k: p.get(k) for k in PUBLIC_PROJECT_FIELDS if k in p}


def build_payload(curr: dict) -> dict:
    """Build the API JSON payload from a projects.json-shaped dict."""
    projects = curr.get("projects") or []
    counts = {"prelaunch": 0, "live": 0, "successful": 0, "failed": 0}
    pwl = 0
    total_live_usd = 0.0
    for p in projects:
        st = p.get("status")
        if st in counts:
            counts[st] += 1
        if p.get("project_we_love"):
            pwl += 1
        if st == "live":
            try:
                total_live_usd += float(p.get("pledged_usd") or 0)
            except (TypeError, ValueError):
                pass
    counts["total"] = len(projects)
    counts["pwl"] = pwl

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": curr.get("generated_at")
            or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "edition": edition_number(),
        "counts": counts,
        "total_live_usd": total_live_usd,
        "projects": [_slim_project(p) for p in projects],
    }


def write_api(curr: dict) -> list[Path]:
    """Write today.json + <date>.json + index.json to site/api/.

    Returns the list of paths written so the caller can log + cron commits."""
    API_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_payload(curr)
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    body = json.dumps(payload, indent=2, ensure_ascii=False)

    paths: list[Path] = []
    today_path = API_DIR / f"{today}.json"
    today_path.write_text(body, encoding="utf-8")
    paths.append(today_path)

    alias = API_DIR / "today.json"
    alias.write_text(body, encoding="utf-8")
    paths.append(alias)

    # Build the index of available dates by scanning the dir
    dated = sorted(
        [f.stem for f in API_DIR.glob("*.json") if f.stem not in ("today", "index")],
        reverse=True,
    )
    index = {
        "schema_version": SCHEMA_VERSION,
        "latest": dated[0] if dated else None,
        "dates": dated,
        "doc_url": "https://github.com/Chen17-sq/kickstarter-china-tracker#docs",
    }
    index_path = API_DIR / "index.json"
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    paths.append(index_path)
    return paths


if __name__ == "__main__":
    curr = json.loads((REPO_ROOT / "data" / "projects.json").read_text(encoding="utf-8"))
    paths = write_api(curr)
    for p in paths:
        print(f"wrote {p.relative_to(REPO_ROOT)} ({p.stat().st_size:,} bytes)")
