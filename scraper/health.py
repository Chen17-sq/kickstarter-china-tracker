"""Lightweight in-memory scrape-run health log + JSON serializer.

Each run accumulates counters here as `discover`, `project`, and `run`
modules execute, then `save()` is called at the end of `scraper.run`
to dump to `data/.scrape_health.json`. `email_notify` reads that file
and prints a 2-3 line summary in the OPS digest.

Why a singleton? A run is composed of multiple modules (discover.py,
project.py) that each contribute counters. Passing a logger through
every function signature is clutter. A module-level dict is simpler
and we never run two scrapes in parallel in one process.

What the owner sees in the OPS digest (example):
  Scrape health:
    discover:  688 candidates · 14/14 seeds clean (curl_cffi)
    watches:   234/234 (100.0%) via curl_cffi
    pledge:    198/234 (84.6%)

When degraded:
  Scrape health:
    discover:  237 candidates · 6/14 seeds had page failures · 12 pages via Playwright
    watches:   234/234 (100.0%) via PLAYWRIGHT FALLBACK
    pledge:    198/234 (84.6%) · 0 restored from prev snapshot
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HEALTH_PATH = REPO_ROOT / "data" / ".scrape_health.json"


def _empty_state() -> dict:
    return {
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "finished_at": None,
        "discover": {
            "candidates_total": 0,            # deduped projects across all seeds
            "seeds_total": 0,                 # seeds attempted
            "seeds_with_page_failure": 0,     # seeds where at least one page failed curl_cffi
            "playwright_used": False,         # did we ever open the Playwright fallback?
            "playwright_pages_served": 0,     # individual pages served by Playwright
        },
        "watches": {
            "path": "unknown",                # "curl_cffi" | "playwright" | "failed"
            "fetched": 0,
            "requested": 0,
            "restored_from_prev_snapshot": 0,
        },
        "pledge": {
            "path": "unknown",
            "fetched": 0,
            "requested": 0,
        },
        "classified": 0,                      # rows kept after Chinese-background classify
    }


_state: dict = _empty_state()


def reset() -> None:
    """Reset all counters. Call once at the start of a run."""
    global _state
    _state = _empty_state()


# ── Discover counters ────────────────────────────────────────────────

def discover_seed_started() -> None:
    _state["discover"]["seeds_total"] += 1


def discover_seed_page_failed_curl_cffi() -> None:
    # Marks the CURRENT seed as having had a curl_cffi page failure.
    # Idempotent — same seed can fail multiple pages and we still count once.
    # discover.py is expected to call this once per affected seed (boolean-like).
    # If you want per-page granularity later, just bump a separate counter.
    _state["discover"]["seeds_with_page_failure"] += 1


def discover_playwright_used(pages: int = 1) -> None:
    _state["discover"]["playwright_used"] = True
    _state["discover"]["playwright_pages_served"] += pages


def discover_finalize(candidates_total: int) -> None:
    _state["discover"]["candidates_total"] = candidates_total


# ── Watches / pledge counters ───────────────────────────────────────

def watches_done(path: str, fetched: int, requested: int) -> None:
    """`path` is "curl_cffi" / "playwright" / "failed"."""
    _state["watches"]["path"] = path
    _state["watches"]["fetched"] = fetched
    _state["watches"]["requested"] = requested


def watches_restored_from_prev(n: int) -> None:
    _state["watches"]["restored_from_prev_snapshot"] = n


def pledge_done(path: str, fetched: int, requested: int) -> None:
    _state["pledge"]["path"] = path
    _state["pledge"]["fetched"] = fetched
    _state["pledge"]["requested"] = requested


# ── Classify counter ────────────────────────────────────────────────

def classified(n: int) -> None:
    _state["classified"] = n


# ── Persist + load ──────────────────────────────────────────────────

def save() -> Path:
    """Write current state to data/.scrape_health.json. Returns the path."""
    _state["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_PATH.write_text(json.dumps(_state, indent=2), encoding="utf-8")
    return HEALTH_PATH


def load() -> dict | None:
    """Read the last scrape's health log. Returns None if missing or corrupt."""
    if not HEALTH_PATH.exists():
        return None
    try:
        return json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── Owner-readable summary ──────────────────────────────────────────

def format_digest_lines(state: dict | None = None) -> list[str]:
    """Return 3-5 plaintext lines suitable for the OPS digest body."""
    s = state if state is not None else _state
    d = s.get("discover") or {}
    w = s.get("watches") or {}
    pl = s.get("pledge") or {}

    lines = ["Scrape health:"]

    # discover line
    seeds_clean = (d.get("seeds_total", 0) or 0) - (d.get("seeds_with_page_failure", 0) or 0)
    seeds_total = d.get("seeds_total", 0) or 0
    if d.get("playwright_used"):
        lines.append(
            f"  discover: {d.get('candidates_total','?')} candidates · "
            f"{seeds_clean}/{seeds_total} seeds clean · "
            f"{d.get('playwright_pages_served', 0)} pages via PLAYWRIGHT FALLBACK"
        )
    else:
        lines.append(
            f"  discover: {d.get('candidates_total','?')} candidates · "
            f"{seeds_clean}/{seeds_total} seeds clean (curl_cffi)"
        )

    # watches line
    req = w.get("requested", 0) or 0
    fetched = w.get("fetched", 0) or 0
    pct = (100.0 * fetched / req) if req else 0
    path = (w.get("path") or "unknown").upper() if w.get("path") == "playwright" else w.get("path") or "unknown"
    restored = w.get("restored_from_prev_snapshot", 0) or 0
    watches_line = f"  watches:   {fetched}/{req} ({pct:.1f}%) via {path}"
    if restored:
        watches_line += f" · {restored} restored from prev snapshot"
    lines.append(watches_line)

    # pledge line
    pr = pl.get("requested", 0) or 0
    pf = pl.get("fetched", 0) or 0
    p_pct = (100.0 * pf / pr) if pr else 0
    lines.append(f"  pledge:    {pf}/{pr} ({p_pct:.1f}%) via {pl.get('path','unknown')}")

    # classified line
    if s.get("classified"):
        lines.append(f"  classified: {s['classified']} China-background kept")

    return lines
