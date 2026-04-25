"""Fetch a single Kickstarter project page and extract the structured fields.

Two project page shapes:
  1. Prelaunch ("Coming Soon") — has `Launching soon`, `N followers`, badge,
     creator handle, location, category. NO pledge/backer numbers.
  2. Live / Successful — has `Project We Love` badge, `S$/USD pledged of goal`,
     `N backers`, `N days to go`, location, creator.

We rely on plain text patterns because the markup is React-rendered but the SSR
HTML still contains all the visible text in the right order.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional
from selectolax.parser import HTMLParser

from .http import make_client


# --- regex patterns over the visible text ---
RE_FOLLOWERS = re.compile(r"([\d,]+)\s*followers", re.I)
RE_BACKERS   = re.compile(r"([\d,]+)\s*backers", re.I)
RE_DAYS_LEFT = re.compile(r"([\d,]+)\s*days?\s*to\s*go", re.I)
RE_PLEDGED   = re.compile(r"([A-Z]{0,3}\$?\s*[\d,]+)\s*pledged\s*of\s*([A-Z]{0,3}\$?\s*[\d,]+)\s*goal", re.I)
RE_FUNDED_PCT = re.compile(r"(\d[\d,]*)\%\s*funded", re.I)
RE_DEADLINE   = re.compile(r"by\s+(\w+,\s+\w+\s+\d+\s+\d{4}\s+[\d:]+\s+[AP]M)", re.I)


@dataclass
class ProjectSnapshot:
    pathname: str
    url: str
    title: Optional[str]
    subtitle: Optional[str]
    creator: Optional[str]
    location: Optional[str]
    category: Optional[str]
    status: str                       # "prelaunch" | "live" | "successful" | "failed" | "unknown"
    project_we_love: bool
    followers: Optional[int]          # prelaunch
    backers: Optional[int]            # live/ended
    pledged_native: Optional[str]     # raw "S$ 882,982"
    goal_native: Optional[str]
    funded_pct: Optional[float]
    days_to_go: Optional[int]
    deadline: Optional[str]
    raw_text_excerpt: str             # first 400 chars of main, useful for debugging


def _to_int(s: str) -> Optional[int]:
    if s is None:
        return None
    m = re.sub(r"[^\d]", "", s)
    return int(m) if m else None


def _detect_status(text: str) -> str:
    head = text[:200].lower()
    if "launching soon" in head:
        return "prelaunch"
    if "days to go" in text.lower() or "hours to go" in text.lower():
        return "live"
    if "funding successful" in text.lower() or "successful" in text.lower():
        return "successful"
    if "funding unsuccessful" in text.lower():
        return "failed"
    return "unknown"


def parse_project_html(pathname: str, html: str) -> ProjectSnapshot:
    tree = HTMLParser(html)
    main = tree.css_first("main") or tree.body
    text = (main.text() if main else tree.text()).strip()
    text_compact = re.sub(r"\s+", " ", text)

    title = None
    subtitle = None
    h1 = tree.css_first("h1")
    if h1:
        title = h1.text(strip=True)

    status = _detect_status(text_compact)
    pwl = "Project We Love" in text_compact

    followers = _to_int(m.group(1)) if (m := RE_FOLLOWERS.search(text_compact)) else None
    backers = _to_int(m.group(1)) if (m := RE_BACKERS.search(text_compact)) else None
    days = _to_int(m.group(1)) if (m := RE_DAYS_LEFT.search(text_compact)) else None
    deadline = m.group(1) if (m := RE_DEADLINE.search(text_compact)) else None

    pledged = goal = None
    if (m := RE_PLEDGED.search(text_compact)):
        pledged, goal = m.group(1).strip(), m.group(2).strip()

    funded_pct = float(m.group(1).replace(",", "")) if (m := RE_FUNDED_PCT.search(text_compact)) else None

    # location & category are typically near top, hard to pin down without React state.
    # Approximation: scan for tokens after "Project We Love" or "Launching soon"
    loc_match = re.search(r"(?:Project We Love|Launching soon)\s+([^\n]{0,80}?,\s+[A-Z]{2,4}|[^\n]{0,80}?,\s*\w+)", text_compact)
    location = loc_match.group(1).strip() if loc_match else None

    cat_match = re.search(r",\s*[A-Z]{2,4}\s+([\w &/]+?)\s+(?:Notify me on launch|Back this project|Remind me)", text_compact)
    category = cat_match.group(1).strip() if cat_match else None

    creator = pathname.strip("/").split("/")[1] if pathname.count("/") >= 3 else None

    return ProjectSnapshot(
        pathname=pathname,
        url="https://www.kickstarter.com" + pathname,
        title=title,
        subtitle=subtitle,
        creator=creator,
        location=location,
        category=category,
        status=status,
        project_we_love=pwl,
        followers=followers,
        backers=backers,
        pledged_native=pledged,
        goal_native=goal,
        funded_pct=funded_pct,
        days_to_go=days,
        deadline=deadline,
        raw_text_excerpt=text_compact[:400],
    )


def fetch_project(pathname: str, *, client=None) -> ProjectSnapshot:
    own = client is None
    if own:
        client = make_client()
    try:
        url = "https://www.kickstarter.com" + pathname
        r = client.get(url)
        r.raise_for_status()
        return parse_project_html(pathname, r.text)
    finally:
        if own:
            client.close()


if __name__ == "__main__":
    import sys, json
    snap = fetch_project(sys.argv[1] if len(sys.argv) > 1 else "/projects/xlean/xlean-tr1-dual-form-transformable-floor-washing-robot")
    print(json.dumps(snap.__dict__, ensure_ascii=False, indent=2))
