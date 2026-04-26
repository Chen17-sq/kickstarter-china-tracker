"""Subscriber list management — read / add / list / send-to-all.

Storage: `data/subscribers.json` — flat list of {email, nickname, added_at, source}.
No unsubscribe flow yet (per owner): to remove someone, edit the file by hand.

Used by:
  - email_notify.py: when SUBSCRIBE_BROADCAST=1, sends today's edition to all
    subscribers (one Resend API call per recipient — Resend has no batch
    `to:` for personalised content; for ≤100 subs/day this is fine).
  - This module's CLI: add / list / count.

Manual flow:
  Formspree posts new sign-ups to the owner's Gmail. The owner runs:
    python -m scraper.subscribers add jane@example.com "Jane"
  …which appends to data/subscribers.json. Next morning's cron broadcasts.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUBSCRIBERS = REPO_ROOT / "data" / "subscribers.json"

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def load() -> dict:
    if not SUBSCRIBERS.exists():
        return {"_meta": {}, "count": 0, "subscribers": []}
    try:
        return json.loads(SUBSCRIBERS.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  warn: subscribers.json failed to load ({e}); starting empty", file=sys.stderr)
        return {"_meta": {}, "count": 0, "subscribers": []}


def save(data: dict) -> None:
    data["count"] = len(data.get("subscribers", []))
    SUBSCRIBERS.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def add(email: str, nickname: str = "", *, source: str = "form") -> bool:
    """Add a subscriber. Returns True if added, False if already present."""
    if not EMAIL_RE.match(email):
        raise ValueError(f"invalid email: {email!r}")
    data = load()
    subs = data.setdefault("subscribers", [])
    if any(s.get("email", "").lower() == email.lower() for s in subs):
        print(f"  {email} already subscribed — no-op")
        return False
    subs.append({
        "email": email,
        "nickname": (nickname or "").strip() or email.split("@")[0],
        "added_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
        "source": source,
    })
    save(data)
    print(f"  added {email} ({nickname!r}); now {len(subs)} subscribers")
    return True


def remove(email: str) -> bool:
    data = load()
    subs = data.setdefault("subscribers", [])
    before = len(subs)
    data["subscribers"] = [s for s in subs if s.get("email", "").lower() != email.lower()]
    if len(data["subscribers"]) == before:
        print(f"  {email} not found")
        return False
    save(data)
    print(f"  removed {email}; now {len(data['subscribers'])} subscribers")
    return True


def emails() -> list[str]:
    data = load()
    return [s["email"] for s in data.get("subscribers", []) if s.get("email")]


def count() -> int:
    return len(emails())


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
            print(f"  {s.get('email','?'):40s} {s.get('nickname',''):20s} {s.get('added_at','')} ({s.get('source','')})")
        print(f"\nTotal: {len(data.get('subscribers', []))}")
        return 0
    if args.cmd == "count":
        print(count())
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
