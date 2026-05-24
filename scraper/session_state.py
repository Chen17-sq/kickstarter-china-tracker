"""Cross-run session state — cookies, warmth, last-seen-CF-clearance.

Why this exists: every cron used to open a fresh curl_cffi/Playwright
session from a GitHub Actions IP. That triple ("new session + new
fingerprint + flagged IP") is exactly what Cloudflare scores high-bot
on. Persisting `cf_clearance` + `__cflb` + `_kickstarter_session`
between runs makes the scraper look like a returning user, which
materially improves CF pass rates on the GraphQL second-session 403
case (which was confirmed today, 2026-05-24, on the live cron).

State file: `.session_state.json` in repo root, gitignored. In CI it
gets persisted via `actions/cache@v4`. Locally it's just on disk.

What we persist:
  cookies      — cf_clearance, __cflb, __cf_bm, _kickstarter_session,
                 fingerprint, plus anything else KS set during warm-up.
  last_seen    — when the last successful KS interaction happened
                 (used to decide if we should re-warm vs ride existing
                 cookies)
  ua           — the User-Agent that earned the cookies (must match on
                 reuse, or CF rejects mismatched fingerprint+cookies)
  warmed_at    — last warm-up timestamp
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / ".session_state.json"

# Cookies we care about preserving. KS sets many; these are the ones
# that signal "returning user" to CF.
PRESERVE_COOKIE_NAMES = {
    "cf_clearance",       # CF challenge token (gold)
    "__cflb",             # CF load balancer
    "__cf_bm",            # CF bot management (1h TTL)
    "_kickstarter_session",
    "session_token",
    "lang",
    "currency",
}

# Stale cookies are worse than no cookies — CF flags mismatch as
# "stolen session." Anything older than this we throw away and re-warm.
STALE_AFTER_HOURS = 24


def load() -> dict[str, Any]:
    """Load persisted session state. Returns {} on first run or if stale."""
    if not STATE_FILE.exists():
        return {}
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

    last_seen = state.get("last_seen")
    if last_seen:
        try:
            ts = dt.datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            age_hours = (
                dt.datetime.now(dt.UTC) - ts.replace(tzinfo=dt.UTC)
            ).total_seconds() / 3600
            if age_hours > STALE_AFTER_HOURS:
                # Cookies likely expired — start fresh.
                return {}
        except Exception:
            pass
    return state


def save(state: dict[str, Any]) -> None:
    """Persist session state. Caller passes the dict shape:
        {cookies: {name: value}, ua: str, last_seen: iso, warmed_at: iso}
    """
    try:
        STATE_FILE.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        # Persistence is opportunistic — never block the scrape on it.
        pass


def update_cookies(client_or_dict: Any) -> None:
    """Extract cookies from a curl_cffi Session or a dict, persist them."""
    state = load()
    cookies = state.get("cookies") or {}

    # curl_cffi Session has .cookies (a Cookies object iterable)
    if hasattr(client_or_dict, "cookies"):
        for c in client_or_dict.cookies:
            name = getattr(c, "name", None)
            value = getattr(c, "value", None)
            if name in PRESERVE_COOKIE_NAMES and value:
                cookies[name] = value
    elif isinstance(client_or_dict, dict):
        for name, value in client_or_dict.items():
            if name in PRESERVE_COOKIE_NAMES and value:
                cookies[name] = value

    state["cookies"] = cookies
    state["last_seen"] = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    save(state)


def get_cookies() -> dict[str, str]:
    """Return the persisted cookies (or {} if none). Caller seeds these
    into a fresh curl_cffi.Session or Playwright context."""
    state = load()
    return state.get("cookies") or {}


def get_ua() -> str | None:
    """Return the persisted User-Agent (or None). Reusing the same UA
    that earned the cookies is critical — CF flags UA-cookie mismatch."""
    state = load()
    return state.get("ua")


def set_ua(ua: str) -> None:
    state = load()
    state["ua"] = ua
    save(state)


def mark_warmed() -> None:
    state = load()
    state["warmed_at"] = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    save(state)


def is_warm(*, within_hours: float = 6.0) -> bool:
    """Has the session been warmed up recently? If yes, we can skip the
    homepage GET and ride existing cookies."""
    state = load()
    w = state.get("warmed_at")
    if not w:
        return False
    try:
        ts = dt.datetime.fromisoformat(w.replace("Z", "+00:00"))
        age = (dt.datetime.now(dt.UTC) - ts.replace(tzinfo=dt.UTC)).total_seconds()
        return age < within_hours * 3600
    except Exception:
        return False
