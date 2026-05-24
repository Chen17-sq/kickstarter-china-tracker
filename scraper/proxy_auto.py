"""Auto-discover free HTTP proxies — removes the user-side proxy dependency.

When `KS_PROXY` env var isn't set, this module fetches a fresh list of
public HTTP proxies from ProxyScrape, validates each candidate against
Kickstarter's robots.txt, and returns the first working URL. Working
proxies are cached in `data/.proxy_cache.json` (gitignored, 24h TTL)
so we don't re-validate on every cron run.

This is the "no signup required" tier of IP rotation. It's strictly
best-effort:

  - Free proxies are unreliable (mostly dead within hours)
  - Some may be honeypots / MITM rigs
  - Latency is much worse than residential

But it's still a meaningful win when the alternative is bare GH Actions
IP (whose ASN Cloudflare aggressively fingerprints). Any working proxy
moves us off the flagged ASN entirely.

Precedence order in `pick_proxy()`:
  1. KS_PROXY env var (user-configured residential, e.g. Webshare)
  2. proxy_auto.discover() — this module
  3. Direct connection (current behavior)

ProxyScrape (proxyscrape.com) is the data source — no auth required,
refreshed every 60 minutes, returns thousands of IP:PORT lines.
"""
from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = REPO_ROOT / "data" / ".proxy_cache.json"

PROXYSCRAPE_URL = (
    "https://api.proxyscrape.com/v2/"
    "?request=displayproxies&protocol=http&timeout=10000"
    "&country=all&ssl=all&anonymity=all"
)
TEST_URL = "https://www.kickstarter.com/robots.txt"
TEST_TIMEOUT = 5.0
MAX_CANDIDATES = 20
CACHE_TTL_HOURS = 24
KEEP_N_WORKING = 3  # save a few in cache for redundancy across runs


def _load_cache() -> list[str]:
    """Return cached working proxy URLs, or [] if cache missing/stale."""
    if not CACHE_FILE.exists():
        return []
    try:
        d = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        ts = d.get("updated_at", "")
        when = dt.datetime.fromisoformat(ts)
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.UTC)
        age_hours = (dt.datetime.now(dt.UTC) - when).total_seconds() / 3600
        if age_hours > CACHE_TTL_HOURS:
            return []
        return [p for p in d.get("proxies", []) if isinstance(p, str)]
    except Exception:
        return []


def _save_cache(proxies: list[str]) -> None:
    """Persist working proxy list. Failures are swallowed — caller
    treats persistence as opportunistic, never a hard dependency."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(
            json.dumps({
                "updated_at": dt.datetime.now(dt.UTC).isoformat(),
                "proxies": proxies,
            }),
            encoding="utf-8",
        )
    except Exception:
        pass


def fetch_candidates() -> list[str]:
    """Pull raw IP:PORT list from ProxyScrape, return as http:// URLs.

    Returns [] on any network/parse failure. We don't differentiate
    between "list service is down" and "list is empty" — both mean
    "fall through to direct connection."
    """
    try:
        # Use curl_cffi (already a dependency) — also gives us a real
        # browser TLS fingerprint when hitting ProxyScrape, in case they
        # ever start gating their own API.
        from curl_cffi import requests as cc
        r = cc.get(PROXYSCRAPE_URL, timeout=10.0, impersonate="chrome120")
        if r.status_code != 200:
            return []
        lines = [ln.strip() for ln in r.text.splitlines() if ln.strip()]
        # Keep only ones that look like IPv4:PORT
        out = []
        for ln in lines:
            if ":" not in ln or ln.count(".") != 3:
                continue
            _ip, _, port = ln.partition(":")
            if not port.isdigit():
                continue
            out.append(f"http://{ln}")
        return out
    except Exception:
        return []


def validate_proxy(proxy_url: str) -> bool:
    """Smoke test: can we reach KS robots.txt through this proxy?

    Robots.txt is unauthenticated and stable — perfect probe target.
    A working proxy returns 200 + content starting with "User-agent".
    """
    try:
        from curl_cffi import requests as cc
        r = cc.get(
            TEST_URL,
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=TEST_TIMEOUT,
            impersonate="chrome120",
        )
        return r.status_code == 200 and "User-agent" in (r.text[:500] or "")
    except Exception:
        return False


def discover(*, max_test: int = MAX_CANDIDATES) -> str | None:
    """Return one validated free proxy URL, or None.

    Strategy:
      1. Cache hit (24h TTL) — return first cache entry that still works
      2. Cache miss — fetch fresh list from ProxyScrape
      3. Shuffle, validate up to `max_test` candidates
      4. Cache the working ones for next run
      5. Return the first working URL (or None)
    """
    # Cache-first
    for p in _load_cache():
        if validate_proxy(p):
            return p

    candidates = fetch_candidates()
    if not candidates:
        return None

    random.shuffle(candidates)
    working: list[str] = []
    for c in candidates[:max_test]:
        if validate_proxy(c):
            working.append(c)
            if len(working) >= KEEP_N_WORKING:
                break

    if working:
        _save_cache(working)
        return working[0]
    return None
