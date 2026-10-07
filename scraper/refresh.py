"""Refresh known catalog entries independently of discovery.

Field-level evidence distinguishes failed requests from unchanged observations.
Catalog queries use conservative batches; GraphQL errors remain diagnosable.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import health
from .graphql import CATALOG_BATCH_SIZE, fetch_projects
from .money import observe_money, to_usd
from .observations import carry_row, number, observe, timestamp
from .project import (
    _open_transport,
)

_AUTO_TRANSPORT = object()

REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = REPO_ROOT / "data" / "history"

# Map KS GraphQL state → our internal status field
STATE_MAP = {
    "STARTED": "prelaunch",
    "SUBMITTED": "prelaunch",
    "LIVE": "live",
    "SUCCESSFUL": "successful",
    "FAILED": "failed",
    "CANCELED": "canceled",
    "PURGED": "suspended",
    "SUSPENDED": "suspended",
}

# Field set for the fat query — everything that can change day-to-day
# in a single round trip. Adding fields here is cheap (KS doesn't charge
# per field) but bloats response size.
FAT_QUERY_FIELDS = """
    watchesCount
    currency
    usdExchangeRate
    state
    backersCount
    pledged { amount currency }
    percentFunded
    goal { amount currency }
    deadlineAt
"""


def latest_history_snapshot() -> dict | None:
    """Most recent history snapshot (not necessarily yesterday — could be
    any prior day if cron skipped some). Returns None if no history."""
    if not HISTORY_DIR.exists():
        return None
    snaps = sorted(HISTORY_DIR.glob("*.json"))
    if not snaps:
        return None
    now = timestamp()
    # Include same-day successful observations when recovering; never invent
    # a timestamp from the enclosing snapshot for legacy carried values.
    for p in reversed(snaps):
        try:
            snapshot = json.loads(p.read_text(encoding="utf-8"))
            if snapshot.get("generated_at", "") <= now:
                return snapshot
        except (ValueError, OSError):
            continue
    return None


def fetch_fat_graphql(
    slugs: list[str],
    *,
    transport=_AUTO_TRANSPORT,
    verbose: bool = True,
) -> dict[str, dict]:
    """Fat GraphQL fetch — one query, many fields, batched 20 slugs/chunk.

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

    own_transport = transport is _AUTO_TRANSPORT
    if own_transport:
        transport = _open_transport(label="refresh", verbose=verbose)
        if transport is None:
            if verbose:
                print("  ✗ refresh: transport open failed (all tiers blocked)")
            return out

    if transport is None:
        return out

    try:
        fetched = fetch_projects(slugs, transport=transport, fields=FAT_QUERY_FIELDS,
                                 operation="Refresh", batch_size=CATALOG_BATCH_SIZE,
                                 source="catalog_refresh")
        for slug, response in fetched.items():
            obj = response["data"]
            pledged = obj.get("pledged")
            pledged = pledged if isinstance(pledged, dict) else {}
            goal = obj.get("goal")
            goal = goal if isinstance(goal, dict) else {}
            out[slug] = {
                "_error": response["error"],
                "currency": obj.get("currency"), "usd_exchange_rate": number(obj.get("usdExchangeRate")),
                "watchesCount": obj.get("watchesCount"), "state": obj.get("state"),
                "backersCount": obj.get("backersCount"),
                "pledged_amt": number(pledged.get("amount")),
                "pledged_currency": pledged.get("currency"),
                "percentFunded": obj.get("percentFunded"),
                "goal_amt": number(goal.get("amount")), "goal_currency": goal.get("currency"), "deadlineAt": obj.get("deadlineAt"),
                "observed_at": response.get("observed_at"),
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
    refreshed = state_changes = 0
    total_usd_delta = None  # computed exclusively by momentum with validated baselines
    attempted = timestamp()
    for orig in project_records:
        path = orig.get("pathname")
        slug = slug_from_pathname(path) if path else None
        fresh = refresh_data.get(slug) or {}
        reason = fresh.get("_error", "source_missing" if fresh else "fetch_failed")
        new = carry_row(orig, at=attempted, reason=reason)
        at = fresh.get("observed_at") or attempted
        any_fresh = False
        for field, source_field in (("followers", "watchesCount"), ("backers", "backersCount"),
                                    ("percent_funded", "percentFunded")):
            any_fresh |= observe(new, field, fresh.get(source_field), at=at, source="ks_graphql")
        currency = fresh.get("pledged_currency")
        if currency:
            observe(new, "pledged_native", fresh.get("pledged_amt"), at=at,
                    source="ks_graphql", unit=currency, basis="native_pledged:" + currency)
            converted = to_usd(fresh.get("pledged_amt"), currency,
                               fresh.get("currency"), fresh.get("usd_exchange_rate"))
            any_fresh |= observe_money(new, "pledged_usd", converted, at=at, source="ks_graphql")
        if fresh.get("currency"):
            new["native_currency"] = fresh["currency"]
        any_fresh |= observe_money(new, "goal_usd", to_usd(
            fresh.get("goal_amt"), fresh.get("goal_currency"), fresh.get("currency"),
            fresh.get("usd_exchange_rate")), at=at, source="ks_graphql")
        if fresh.get("state") in STATE_MAP:
            mapped = STATE_MAP[fresh["state"]]
            state_changes += mapped != orig.get("status")
            new["status"] = mapped
            new["raw_state"] = fresh["state"].lower()
            new["status_observation"] = {"status": "fresh", "observed_at": at,
                                         "source": "ks_graphql", "raw_state": fresh["state"]}
        refreshed += bool(any_fresh)
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
            "live USD net: computed later from comparable observations"
        )
    return new_records, summary


def refresh_from_history(
    *,
    transport=_AUTO_TRANSPORT,
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
