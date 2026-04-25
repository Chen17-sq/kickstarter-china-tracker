"""Fetch supplementary data from a single Kickstarter project page.

The Discover JSON endpoint already gives us 90% of the fields we need
(name, creator, location, country, pledged, backers, state, deadline,
staff_pick, ...). The one thing it does NOT include is the **follower count**,
which is the key prelaunch metric. So this module only fetches what's missing.

Project pages are React-rendered, but the SSR HTML still contains the visible
text in order — including a "N followers" string near the top.
"""
from __future__ import annotations
import re
from typing import Optional

from .http import fetch

RE_FOLLOWERS = re.compile(r"([\d,]+)\s*followers", re.I)


def _to_int(s: str | None) -> Optional[int]:
    if s is None:
        return None
    m = re.sub(r"[^\d]", "", s)
    return int(m) if m else None


def fetch_followers(pathname: str, *, client=None) -> Optional[int]:
    """Fetch a project page and extract the follower count.

    Returns None if the field can't be found (e.g. the page is now in a state
    that doesn't expose followers, or the regex fails).
    """
    url = "https://www.kickstarter.com" + pathname
    try:
        r = fetch(url, client=client)
    except RuntimeError:
        return None
    text = re.sub(r"\s+", " ", r.text)
    m = RE_FOLLOWERS.search(text)
    return _to_int(m.group(1)) if m else None


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "/projects/xlean/xlean-tr1-dual-form-transformable-floor-washing-robot"
    print(f"{path} → followers={fetch_followers(path)}")
