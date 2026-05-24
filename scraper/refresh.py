"""Daily refresh — promote yesterday's projects with one fat GraphQL query.

Architecturally this is the BIGGEST resilience improvement in the whole
scraper. Before today: every cron tried to re-discover the entire
universe via /discover/advanced — fragile, single point of failure
(today's 2026-05-24 cron lost 50% of projects when 4/14 seeds got CF-
blocked). After: we load yesterday's pathnames from local history (free,
no network), refresh them via ONE GraphQL query (watchesCount + state +
backersCount + pledged_usd + percentFunded + goal_amt), and use discover
ONLY for finding genuinely new projects.

This makes the pipeline ALMOST IMMUNE to discover failures. Even if
KS hard-blocks /discover/advanced for a week, we still have ~245 live
project refreshes per day with all their fresh metrics. The sanity gate
stops firing on "project count dropped 50%" because the floor is
yesterday's count, not today's discover output.

Reused for `scripts/emergency_refresh.py` AND `scraper/run.py` so the
two paths share one canonical implementation.

Cost: ONE GraphQL call (~5 chunks of 50 slugs). ~3-10 seconds total.
Same transport ladder (curl_cffi → patchright → nodriver) so when CF
blocks one layer, we ride down the tiers exactly like the discover path.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import health
from .project import (
    CHUNK_SIZE,
    _open_transport,
    _Transport,
    backoff,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = REPO_ROOT / "data" / "history"

# Map KS GraphQL state → our internal status field
STATE_MAP = {
    "SUBMITTED": "prelaunch",
    "LIVE": "live",
    "SUCCESSFUL": "successful",
    "FAILED": "failed",
    "CANCELED": "failed",
    "PURGED": "failed",
    "SUSPENDED": "failed",
}

# Field set for the fat query — everything that can change day-to-day
# in a single round trip. Adding fields here is cheap (KS doesn't charge
# per field) but bloats response size.
FAT_QUERY_FIELDS = """
    watchesCount
    state
    backersCount
    pledged { amount currency }
    percentFunded
    goal { amount }
    deadlineAt
"""


def _num(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def latest_history_snapshot() -> dict | None:
    """Most recent history snapshot (not necessarily yesterday — could be
    any prior day if cron skipped some). Returns None if no history."""
    if not HISTORY_DIR.exists():
        return None
    snaps = sorted(HISTORY_DIR.glob("*.json"))
    if not snaps:
        return None
    today_prefix = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    # Skip today's snapshot if present (we're building TOMORROW's
    # refresh from YESTERDAY's data, not from a half-written today)
    for p in reversed(snaps):
        if not p.stem.startswith(today_prefix):
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
    return None


def fetch_fat_graphql(
    slugs: list[str],
    *,
    transport: _Transport | None = None,
    verbose: bool = True,
) -> dict[str, dict]:
    """Fat GraphQL fetch — one query, many fields, batched 50 slugs/chunk.

    Returns {slug: {watchesCount, state, backersCount, pledged_amt,
                    pledged_currency, percentFunded, goal_amt, deadlineAt}}.
    Missing/failed slugs map to {} so caller can handle gracefully.

    If `transport` is provided, use it and don't close (caller owns
    lifecycle — useful for sharing with watchesCount/pledge_min downstream).
    Otherwise open + close internally.
    """
    out: dict[str, dict] = {s: {} for s in slugs}
    if not slugs:
        return out

    own_transport = transport is None
    if own_transport:
        transport = _open_transport(label="refresh", verbose=verbose)
        if transport is None:
            if verbose:
                print("  ✗ refresh: transport open failed (all tiers blocked)")
            return out

    try:
        for i in range(0, len(slugs), CHUNK_SIZE):
            if i > 0:
                backoff.chunk_pause(1.0, 3.0)
            chunk = slugs[i : i + CHUNK_SIZE]
            var_decls = ", ".join(f"$s{j}: String!" for j in range(len(chunk)))
            fields = "\n  ".join(
                f"p{j}: project(slug: $s{j}) {{{FAT_QUERY_FIELDS}}}"
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
                if verbose:
                    print(
                        f"  ! refresh chunk {i // CHUNK_SIZE + 1}: status {status}"
                    )
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
                        "deadlineAt": obj.get("deadlineAt"),
                    }
        if verbose:
            n_with = sum(
                1 for v in out.values() if v.get("watchesCount") is not None
            )
            print(f"  refresh: got fat data for {n_with}/{len(slugs)} slugs")
    finally:
        if own_transport:
            transport.close()
    return out


def apply_refresh(
    project_records: list[dict],
    refresh_data: dict[str, dict],
    *,
    verbose: bool = True,
) -> tuple[list[dict], dict]:
    """Mutate-and-return: layer refresh data onto each project record.

    Returns (new_records, summary) where summary is:
        {refreshed: N, carried_over: N, state_changes: N, total_usd_delta: float}
    """
    from .project import slug_from_pathname

    new_records: list[dict] = []
    refreshed = 0
    state_changes = 0
    total_usd_delta = 0.0

    for orig in project_records:
        path = orig.get("pathname")
        slug = slug_from_pathname(path) if path else None
        fresh = refresh_data.get(slug) or {}
        new = dict(orig)

        if fresh.get("watchesCount") is not None:
            old_followers = new.get("followers") or 0
            new["followers"] = int(fresh["watchesCount"])
            new["delta_followers"] = new["followers"] - int(old_followers)
            refreshed += 1

        if fresh.get("state"):
            mapped = STATE_MAP.get(fresh["state"])
            if mapped and mapped != new.get("status"):
                state_changes += 1
            if mapped:
                new["status"] = mapped

        if fresh.get("backersCount") is not None:
            old_backers = new.get("backers") or 0
            new["backers"] = int(fresh["backersCount"])
            new["delta_backers"] = new["backers"] - int(old_backers)

        # Currency normalization: only update pledged_usd if returned value
        # is USD. Otherwise keep yesterday's pledged_usd.
        if (
            fresh.get("pledged_currency") == "USD"
            and fresh.get("pledged_amt") is not None
        ):
            old_pledged = _num(new.get("pledged_usd"))
            new["pledged_usd"] = float(fresh["pledged_amt"])
            d = new["pledged_usd"] - old_pledged
            new["delta_pledged_usd"] = d
            if new.get("status") == "live":
                total_usd_delta += d

        if fresh.get("percentFunded") is not None:
            new["percent_funded"] = fresh["percentFunded"]

        new_records.append(new)

    summary = {
        "refreshed": refreshed,
        "carried_over": len(project_records) - refreshed,
        "state_changes": state_changes,
        "total_usd_delta": total_usd_delta,
    }
    if verbose:
        print(
            f"  refresh applied: {refreshed}/{len(project_records)} fresh, "
            f"{state_changes} state changes, "
            f"+${total_usd_delta:,.0f} live USD net"
        )
    return new_records, summary


def refresh_from_history(
    *,
    transport: _Transport | None = None,
    verbose: bool = True,
) -> tuple[list[dict], dict] | None:
    """End-to-end: load yesterday's snapshot, fat-fetch, apply, return.

    Returns (refreshed_projects, summary) or None if no history exists.
    The summary dict includes a `_meta` block ready to slot into
    today's projects.json under a top-level `_refresh` key.
    """
    from .project import slug_from_pathname

    prev = latest_history_snapshot()
    if prev is None:
        if verbose:
            print("  refresh: no history snapshot — first run, skipping")
        return None

    projects = prev.get("projects") or []
    if not projects:
        if verbose:
            print("  refresh: history has no projects, skipping")
        return None

    pathnames = [p.get("pathname") for p in projects if p.get("pathname")]
    slugs = [slug_from_pathname(p) for p in pathnames if p]
    if verbose:
        print(f"  refresh: loading {len(slugs)} pathnames from {prev.get('generated_at', '?')}")

    refresh_data = fetch_fat_graphql(slugs, transport=transport, verbose=verbose)
    refreshed_projects, summary = apply_refresh(
        projects, refresh_data, verbose=verbose
    )
    summary["_meta"] = {
        "source_snapshot": prev.get("generated_at"),
        "fetched_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_slugs": len(slugs),
    }
    # Record health
    n_with = sum(1 for d in refresh_data.values() if d.get("watchesCount") is not None)
    try:
        health.refresh_done(  # type: ignore[attr-defined]
            fetched=n_with, requested=len(slugs)
        )
    except AttributeError:
        # health module doesn't have refresh_done yet — non-fatal
        pass
    return refreshed_projects, summary


def latest_pathname_set() -> set[str]:
    """All pathnames from the most recent history snapshot. Used by
    discover to avoid re-fetching pathnames we already have refreshed."""
    prev = latest_history_snapshot()
    if not prev:
        return set()
    return {
        p.get("pathname") for p in (prev.get("projects") or []) if p.get("pathname")
    }


# Public helpers for emergency_refresh.py compatibility
get_state_map = lambda: dict(STATE_MAP)


if __name__ == "__main__":
    import sys
    out = refresh_from_history(verbose=True)
    if out is None:
        print("no refresh data — first run or empty history")
        sys.exit(1)
    projects, summary = out
    print(f"\nrefreshed {summary['refreshed']} projects, {summary['state_changes']} state changes")
    print(f"total live USD delta: +${summary['total_usd_delta']:,.0f}")
