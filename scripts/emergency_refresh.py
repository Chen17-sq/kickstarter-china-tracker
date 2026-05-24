#!/usr/bin/env python3
"""Emergency refresh — when KS Discover crawl is broken but GraphQL works.

When CF blocks the Discover endpoints (today's case: 2026-05-24), the
normal cron can't enumerate today's projects. The Sanity gate then
correctly blocks the broadcast because project count drops 50%+ vs
yesterday.

But: GraphQL's per-project query path may still work (we saw watches
got 119/119 today). So we can refresh data without doing discover:

  1. Load yesterday's snapshot — full project list with all metadata
  2. For each pathname, fetch a FAT GraphQL query covering:
       watchesCount · state · backersCount · pledged · percentFunded
  3. Update yesterday's records with today's fresh numbers
  4. Currency normalization: GraphQL returns native pledged amount +
     currency. For USD projects, use directly; for non-USD, fall back
     to yesterday's pledged_usd (most projects are USD anyway).
  5. Recompute deltas vs yesterday
  6. Write as today's snapshot with `_emergency_refresh: true` flag
  7. Caller runs email_notify normally; the flag triggers a small
     banner in the email explaining today's data is partial.

Trade-offs vs a clean cron run:
  ✓ Subscribers get an edition today (instead of nothing)
  ✓ Fresh follower counts, pledged amounts, status transitions
  ✓ Today's status changes (prelaunch→live, live→successful) caught
  ✗ NEW projects discovered today are missing (we only see yesterday's)
  ✗ Projects that vanished from KS today are still listed (stale)

Usage:
    # Just refresh
    python scripts/emergency_refresh.py

    # Refresh + immediately email
    python scripts/emergency_refresh.py && python -m scraper.email_notify
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scraper.project import _open_transport, slug_from_pathname  # noqa: E402

PROJECTS_FILE = REPO_ROOT / "data" / "projects.json"
HISTORY_DIR = REPO_ROOT / "data" / "history"

CHUNK_SIZE = 50  # GraphQL aliased query batch size

# Map KS GraphQL state → our status field
STATE_MAP = {
    "SUBMITTED": "prelaunch",
    "LIVE": "live",
    "SUCCESSFUL": "successful",
    "FAILED": "failed",
    "CANCELED": "failed",  # KS treats canceled distinctly; we lump into failed
    "PURGED": "failed",
    "SUSPENDED": "failed",
}


def _num(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def latest_yesterday_snapshot() -> dict | None:
    """Find the most recent history snapshot that's NOT from today."""
    today_prefix = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    snaps = sorted(HISTORY_DIR.glob("*.json"))
    for p in reversed(snaps):
        if not p.stem.startswith(today_prefix):
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
    return None


def fetch_fat_graphql(slugs: list[str]) -> dict[str, dict]:
    """Run the expanded GraphQL query for all slugs.

    Returns {slug: {watchesCount, state, backersCount, pledged_amt,
                    pledged_currency, percentFunded, goal_amt}}.
    Missing slugs map to {} (project not found / GraphQL errored).
    """
    out: dict[str, dict] = {s: {} for s in slugs}
    if not slugs:
        return out

    transport = _open_transport(label="emergency_refresh", verbose=True)
    if transport is None:
        print("  ✗ transport open failed (curl_cffi + Playwright both blocked)",
              file=sys.stderr)
        return out

    try:
        for i in range(0, len(slugs), CHUNK_SIZE):
            chunk = slugs[i : i + CHUNK_SIZE]
            var_decls = ", ".join(f"$s{j}: String!" for j in range(len(chunk)))
            fields = "\n  ".join(
                f"""p{j}: project(slug: $s{j}) {{
                    watchesCount
                    state
                    backersCount
                    pledged {{ amount currency }}
                    percentFunded
                    goal {{ amount }}
                }}"""
                for j in range(len(chunk))
            )
            query = f"query Refresh({var_decls}) {{\n  {fields}\n}}"
            variables = {f"s{j}": s for j, s in enumerate(chunk)}
            body = {
                "operationName": "Refresh",
                "variables": variables,
                "query": query,
            }
            status, jdata = transport.post_graphql(body)
            if status != 200:
                print(f"  ! chunk {i // CHUNK_SIZE + 1}: status {status}",
                      file=sys.stderr)
                continue
            data = (jdata or {}).get("data") or {}
            for j, s in enumerate(chunk):
                obj = data.get(f"p{j}") or {}
                if isinstance(obj, dict):
                    pledged = obj.get("pledged") or {}
                    goal = obj.get("goal") or {}
                    out[s] = {
                        "watchesCount": obj.get("watchesCount"),
                        "state": obj.get("state"),
                        "backersCount": obj.get("backersCount"),
                        "pledged_amt": _num(pledged.get("amount")),
                        "pledged_currency": pledged.get("currency"),
                        "percentFunded": obj.get("percentFunded"),
                        "goal_amt": _num(goal.get("amount")),
                    }
            print(
                f"  ✓ chunk {i // CHUNK_SIZE + 1}/{(len(slugs) + CHUNK_SIZE - 1) // CHUNK_SIZE}"
                f" — {len(chunk)} projects",
                file=sys.stderr,
            )
    finally:
        transport.close()
    return out


def main() -> int:
    yesterday = latest_yesterday_snapshot()
    if yesterday is None:
        print("✗ no yesterday snapshot in data/history/ — bailing", file=sys.stderr)
        return 1

    projects = yesterday.get("projects") or []
    if not projects:
        print("✗ yesterday's snapshot has no projects", file=sys.stderr)
        return 1

    pathnames = [p.get("pathname") for p in projects if p.get("pathname")]
    slugs = [slug_from_pathname(p) for p in pathnames]
    print(f"  loaded {len(slugs)} projects from yesterday's snapshot")
    print(f"  fetching fat GraphQL refresh ...")

    refresh = fetch_fat_graphql(slugs)
    n_with_fresh = sum(1 for v in refresh.values() if v.get("watchesCount") is not None)
    print(f"  got fresh data for {n_with_fresh}/{len(slugs)} projects")

    if n_with_fresh < len(slugs) * 0.5:
        print(
            f"✗ only {n_with_fresh}/{len(slugs)} projects refreshed (<50%) — "
            "GraphQL is also blocked. Cannot proceed.",
            file=sys.stderr,
        )
        return 1

    # Build today's snapshot. For each project: start from yesterday's record,
    # overlay fresh fields from GraphQL when available, keep stale data
    # otherwise (and clearly flag).
    today_projects: list[dict] = []
    state_change_count = 0
    for orig in projects:
        path = orig.get("pathname")
        slug = slug_from_pathname(path) if path else None
        fresh = refresh.get(slug) or {}
        new = dict(orig)  # start from yesterday

        if fresh.get("watchesCount") is not None:
            old_followers = new.get("followers") or 0
            new["followers"] = int(fresh["watchesCount"])
            new["delta_followers"] = new["followers"] - int(old_followers)
        if fresh.get("state"):
            mapped = STATE_MAP.get(fresh["state"])
            if mapped and mapped != new.get("status"):
                state_change_count += 1
            if mapped:
                new["status"] = mapped
        if fresh.get("backersCount") is not None:
            old_backers = new.get("backers") or 0
            new["backers"] = int(fresh["backersCount"])
            new["delta_backers"] = new["backers"] - int(old_backers)
        # Currency normalization: only update pledged_usd if the fresh
        # value is in USD. Otherwise keep yesterday's pledged_usd (which
        # was already converted by the original cron).
        if fresh.get("pledged_currency") == "USD" and fresh.get("pledged_amt") is not None:
            old_pledged = _num(new.get("pledged_usd"))
            new["pledged_usd"] = float(fresh["pledged_amt"])
            new["delta_pledged_usd"] = new["pledged_usd"] - old_pledged
        if fresh.get("percentFunded") is not None:
            new["percent_funded"] = fresh["percentFunded"]

        today_projects.append(new)

    print(f"  state changes detected: {state_change_count}")

    now = dt.datetime.now(dt.UTC)
    today_snapshot = dict(yesterday)
    today_snapshot["generated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    today_snapshot["projects"] = today_projects
    today_snapshot["_emergency_refresh"] = {
        "reason": "KS discover crawl blocked; refreshed from yesterday's catalog",
        "yesterday_snapshot": yesterday.get("generated_at"),
        "projects_refreshed": n_with_fresh,
        "projects_carried_over": len(slugs) - n_with_fresh,
        "state_changes_detected": state_change_count,
    }

    # Write to data/projects.json (the live snapshot the rest of the
    # pipeline reads) AND archive in data/history/.
    PROJECTS_FILE.write_text(
        json.dumps(today_snapshot, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    history_path = HISTORY_DIR / f"{now.strftime('%Y-%m-%dT%H-%M-%SZ')}.json"
    history_path.write_text(
        json.dumps(today_snapshot, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  ✓ wrote data/projects.json ({len(today_projects)} projects)")
    print(f"  ✓ archived {history_path.relative_to(REPO_ROOT)}")
    print()
    print("Next step:")
    print("  python -m scraper.email_notify")
    return 0


if __name__ == "__main__":
    sys.exit(main())
