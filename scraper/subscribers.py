"""Subscriber list — fetched from the private Cloudflare KV store via Worker.

Storage moved from `data/subscribers.json` (public GitHub) to a Cloudflare KV
namespace bound to the `ks-tracker-subscribe` Worker. The change closes a
real privacy hole: the old json file leaked subscribers' emails to anyone
who could clone the public repo.

Read path (this module):
  GET https://ks-tracker-subscribe.schen-aldrich.workers.dev/list
  Headers: { "X-Owner-Token": <env.OWNER_TOKEN> }
  Response: { count: N, subscribers: [{email, nickname, ...}] }

Write path:
  Form submissions go to the Worker's POST /, which writes to KV.
  Owner-driven CLI add/remove uses POST / and POST /unsubscribe.

Required env vars (set in GH Actions secrets + locally as needed):
  SUBSCRIBE_API_URL — defaults to the production Worker URL below
  OWNER_TOKEN       — random secret matching the Worker's binding

Local fallback:
  If neither env var is set, the module falls back to reading
  data/subscribers.json (only useful if you're testing pre-migration).
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_LOCAL = REPO_ROOT / "data" / "subscribers.json"

DEFAULT_WORKER = "https://ks-tracker-subscribe.schen-aldrich.workers.dev"
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _api_base() -> str:
    return (os.environ.get("SUBSCRIBE_API_URL") or DEFAULT_WORKER).rstrip("/")


def _token() -> str | None:
    return os.environ.get("OWNER_TOKEN") or None


def _api_load() -> dict | None:
    """Try the Worker /list endpoint. Returns None if unavailable."""
    base = _api_base()
    tok = _token()
    if not tok:
        return None
    try:
        r = httpx.get(f"{base}/list",
                      headers={"X-Owner-Token": tok},
                      timeout=10)
        if r.status_code == 200:
            return r.json()
        print(f"  warn: GET {base}/list returned {r.status_code}", file=sys.stderr)
    except Exception as e:
        print(f"  warn: GET {base}/list failed ({e})", file=sys.stderr)
    return None


def _local_load() -> dict:
    """Pre-migration fallback: read the old data/subscribers.json on disk."""
    if not LEGACY_LOCAL.exists():
        return {"_meta": {}, "count": 0, "subscribers": []}
    try:
        return json.loads(LEGACY_LOCAL.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  warn: subscribers.json failed to load ({e}); starting empty",
              file=sys.stderr)
        return {"_meta": {}, "count": 0, "subscribers": []}


def load() -> dict:
    """Return the subscriber list. KV-backed when configured, else local file."""
    api = _api_load()
    if api is not None:
        return api
    return _local_load()


def add(email: str, nickname: str = "", *, source: str = "form") -> bool:
    """Add a subscriber via the Worker. Returns True if added, False if already present."""
    if not EMAIL_RE.match(email):
        raise ValueError(f"invalid email: {email!r}")
    base = _api_base()
    try:
        r = httpx.post(f"{base}/",
                       json={"email": email, "nickname": nickname},
                       timeout=10)
        if r.status_code != 200:
            print(f"  POST {base}/ returned {r.status_code}: {r.text[:200]}",
                  file=sys.stderr)
            return False
        body = r.json()
        if body.get("duplicate"):
            print(f"  {email} already subscribed — no-op")
            return False
        print(f"  added {email} ({nickname!r}); count now {body.get('count')}")
        return True
    except Exception as e:
        print(f"  add failed: {e}", file=sys.stderr)
        return False


def remove(email: str) -> bool:
    """Remove a subscriber via the Worker. Owner token required."""
    base = _api_base()
    tok = _token()
    if not tok:
        print("  OWNER_TOKEN env not set — cannot call /unsubscribe", file=sys.stderr)
        return False
    try:
        r = httpx.post(f"{base}/unsubscribe",
                       headers={"X-Owner-Token": tok},
                       json={"email": email},
                       timeout=10)
        if r.status_code != 200:
            print(f"  /unsubscribe returned {r.status_code}: {r.text[:200]}",
                  file=sys.stderr)
            return False
        body = r.json()
        # Worker now returns flat shape: {ok, removed: N, count: M}
        rm = int(body.get("removed", 0) or 0)
        if not rm:
            print(f"  {email} not found")
            return False
        print(f"  removed {email}; count now {body.get('count')}")
        return True
    except Exception as e:
        print(f"  remove failed: {e}", file=sys.stderr)
        return False


def emails() -> list[str]:
    data = load()
    return [s["email"] for s in data.get("subscribers", []) if s.get("email")]


def all_subscribers() -> list[dict]:
    """Return the full subscriber list, including type/creator_slug fields.
    Used by email_notify to personalise creator-type subscribers' emails."""
    data = load()
    return list(data.get("subscribers", []) or [])


def count() -> int:
    return len(emails())


# ── Migration helper: bulk-import from local file → Worker KV ──────
def migrate_local_to_kv() -> int:
    """Push every subscriber from data/subscribers.json to the Worker KV.
    Worker dedupe is case-insensitive, so re-running is idempotent.
    Returns the number of fresh adds."""
    data = _local_load()
    subs = data.get("subscribers") or []
    if not subs:
        print("  no local subscribers to migrate")
        return 0
    print(f"  migrating {len(subs)} subscribers to KV via Worker ...")
    added = 0
    for s in subs:
        email = s.get("email") or ""
        nick = s.get("nickname") or ""
        if not EMAIL_RE.match(email):
            print(f"  skip: invalid email {email!r}")
            continue
        if add(email, nick, source=s.get("source", "form")):
            added += 1
    print(f"  ✓ migration complete: {added} new, {len(subs) - added} already in KV")
    return added


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="Add a subscriber")
    a.add_argument("email")
    a.add_argument("nickname", nargs="?", default="")
    a.add_argument("--source", default="manual")
    r = sub.add_parser("remove", help="Remove a subscriber")
    r.add_argument("email")
    sub.add_parser("list", help="List subscribers")
    sub.add_parser("count", help="Print subscriber count")
    sub.add_parser("migrate", help="One-shot: push local data/subscribers.json into KV")

    args = ap.parse_args(argv)
    if args.cmd == "add":
        ok = add(args.email, args.nickname, source=args.source)
        return 0 if ok else 1
    if args.cmd == "remove":
        ok = remove(args.email)
        return 0 if ok else 1
    if args.cmd == "list":
        data = load()
        for s in data.get("subscribers", []):
            print(f"  {s.get('email','?'):40s} {s.get('nickname',''):20s} "
                  f"{s.get('added_at','')} ({s.get('source','')})")
        print(f"\nTotal: {len(data.get('subscribers', []))}")
        return 0
    if args.cmd == "count":
        print(count())
        return 0
    if args.cmd == "migrate":
        migrate_local_to_kv()
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
