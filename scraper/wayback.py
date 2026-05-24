"""Wayback Machine fallback — ultimate degradation when KS itself is down.

When everything else fails — discover blocked, refresh GraphQL blocked,
even Kicktraq RSS unreachable — we still have one source of historical
KS data that's hosted entirely OUTSIDE Cloudflare's reach:

   web.archive.org/wayback/

The Internet Archive periodically snapshots KS pages. Snapshots are
hours-to-days stale (depending on the project's popularity), but they're
better than zero data when KS is completely unreachable.

This is a TRUE last resort. The data is stale and incomplete — we lose
fresh follower counts, lose today's pledge increments. But for a daily
tracker that depends on KS being scrapable, having SOMETHING > NOTHING
is the difference between a published edition and a black day.

How it works:
  1. For each pathname we want, query the Wayback CDX API to find the
     most recent snapshot URL.
  2. Fetch the snapshot HTML (via web.archive.org).
  3. Extract whatever data we can from the cached page.

What we can get from a Wayback snapshot:
  - title (always in <title>)
  - location (usually in DOM)
  - usd_pledged (visible on the page if it was live at snapshot time)
  - backers (usually visible)
  - status (live/successful/canceled — visible in URL pattern + DOM)

What we CAN'T get:
  - Today's follower count (snapshot is stale)
  - Today's status change (project may have launched after snapshot)
  - Reward tiers (Wayback often doesn't capture below-fold content)

Use case in the pipeline: emergency-refresh-of-emergency-refresh. If
refresh.refresh_from_history() returns 0 fresh records (transport
exhausted at all 3 tiers), the email_notify pipeline can call this to
populate at least title + last-known status for the day's edition.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

import httpx

CDX_URL = "https://web.archive.org/cdx/search/cdx"
WAYBACK_PREFIX = "https://web.archive.org/web"


@dataclass
class WaybackSnap:
    """One Wayback Machine snapshot of a KS project page."""
    pathname: str
    snap_ts: str   # ISO timestamp of the snapshot
    snap_url: str  # full web.archive.org URL


def find_latest_snapshot(
    pathname: str, *, timeout: float = 10.0
) -> WaybackSnap | None:
    """Query the Wayback CDX API to find the most recent snapshot of a
    KS project page. Returns None if no snapshot exists.

    The CDX API is a free public service from the Internet Archive. No
    rate limits beyond their typical hosting bandwidth. Format: line-
    based "timestamp original_url" (single line for our query).
    """
    url = f"https://www.kickstarter.com{pathname}"
    params = {
        "url": url,
        "limit": "-1",          # most recent
        "output": "json",       # JSON array of arrays
        "filter": "statuscode:200",  # skip 404/302 snapshots
    }
    try:
        r = httpx.get(CDX_URL, params=params, timeout=timeout)
        r.raise_for_status()
    except Exception:
        return None
    try:
        rows = r.json()
    except Exception:
        return None
    # First row is headers, rest are data
    if not isinstance(rows, list) or len(rows) < 2:
        return None
    fields = rows[0]
    try:
        ts_idx = fields.index("timestamp")
        url_idx = fields.index("original")
    except (ValueError, AttributeError):
        return None
    latest = rows[-1]
    ts = latest[ts_idx]   # e.g. "20260501123045"
    orig = latest[url_idx]
    snap_url = f"{WAYBACK_PREFIX}/{ts}/{orig}"
    # Format ts as ISO-ish for readability
    try:
        snap_dt = dt.datetime.strptime(ts, "%Y%m%d%H%M%S")
        snap_ts = snap_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        snap_ts = ts
    return WaybackSnap(pathname=pathname, snap_ts=snap_ts, snap_url=snap_url)


# Heuristics for plucking data from a cached HTML page. Brittle by
# nature — KS markup changes between snapshots — so we wrap each
# extractor with try/except and return None on miss.
RE_TITLE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
RE_PLEDGED = re.compile(
    r'data-pledged="([0-9.]+)"|"pledged"\s*:\s*"?([0-9.]+)"?',
    re.IGNORECASE,
)
RE_BACKERS = re.compile(
    r'data-backers="(\d+)"|"backers_count"\s*:\s*(\d+)',
    re.IGNORECASE,
)
RE_STATE = re.compile(
    r'data-state="([a-z_]+)"|"state"\s*:\s*"([a-z_]+)"',
    re.IGNORECASE,
)


def fetch_snapshot_data(snap: WaybackSnap, *, timeout: float = 20.0) -> dict:
    """Fetch the snapshot HTML, extract whatever fields we can.

    Returns a dict with keys present only when extraction succeeds:
      title, pledged_usd, backers, state, _source: "wayback",
      _snap_ts: <when this snapshot was taken>
    Returns at minimum {"_source": "wayback", "_snap_ts": ...} even on
    extraction failure — caller can use the timestamp to decide whether
    a snapshot is too stale to be useful.
    """
    out: dict = {
        "_source": "wayback",
        "_snap_ts": snap.snap_ts,
        "_snap_url": snap.snap_url,
        "pathname": snap.pathname,
    }
    try:
        r = httpx.get(snap.snap_url, timeout=timeout, follow_redirects=True)
        if r.status_code != 200:
            return out
        html = r.text
    except Exception:
        return out

    m = RE_TITLE.search(html)
    if m:
        title = m.group(1).strip().split(" — Kickstarter")[0]
        out["title"] = title

    m = RE_PLEDGED.search(html)
    if m:
        val = m.group(1) or m.group(2)
        try:
            out["pledged_usd"] = float(val)
        except (ValueError, TypeError):
            pass

    m = RE_BACKERS.search(html)
    if m:
        val = m.group(1) or m.group(2)
        try:
            out["backers"] = int(val)
        except (ValueError, TypeError):
            pass

    m = RE_STATE.search(html)
    if m:
        state = (m.group(1) or m.group(2) or "").lower()
        if state:
            out["state"] = state
    return out


def emergency_data_for(pathname: str, *, verbose: bool = True) -> dict | None:
    """End-to-end: find latest Wayback snapshot of a KS pathname, fetch
    its HTML, extract what we can. Returns None if no snapshot exists.

    Intended use:
        for path in missing_paths:
            data = wayback.emergency_data_for(path)
            if data:
                supplement_with_stale_record(path, data)
    """
    snap = find_latest_snapshot(pathname)
    if snap is None:
        if verbose:
            print(f"  wayback: no snapshot for {pathname}")
        return None
    data = fetch_snapshot_data(snap)
    if verbose:
        age = "?"
        try:
            snap_dt = dt.datetime.fromisoformat(snap.snap_ts.replace("Z", "+00:00"))
            age_days = (
                dt.datetime.now(dt.UTC) - snap_dt.replace(tzinfo=dt.UTC)
            ).total_seconds() / 86400
            age = f"{age_days:.1f}d old"
        except Exception:
            pass
        fields = [k for k in data if not k.startswith("_") and k != "pathname"]
        print(f"  wayback ✓ {pathname} ({age}): {fields}")
    return data


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m scraper.wayback /projects/creator/slug")
        sys.exit(1)
    for path in sys.argv[1:]:
        data = emergency_data_for(path)
        if data:
            import json
            print(json.dumps(data, indent=2, ensure_ascii=False))
