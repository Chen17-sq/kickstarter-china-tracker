"""Walk Kickstarter Discover and yield candidate projects with rich metadata.

We use the undocumented `&format=json` endpoint that the Discover page itself
uses for client-side pagination. It returns a JSON object:

    {
      "projects": [ {<full project object>} ... ],
      "total_hits": int,
      "has_more": bool,
      ...
    }

Each project object already contains: name, slug, blurb, country, location,
creator, category, state, deadline, launched_at, pledged, usd_pledged, goal,
backers_count, percent_funded, staff_pick (= Project We Love), urls, etc.
That covers ~90% of the fields we need — we only need to fetch the project
page separately to get the prelaunch follower count.

Why several seeds?
  - China geo filter (woe_id=23424781) gets KS-labeled-Chinese projects.
  - Tech / Design upcoming + popularity catches Chinese brands that registered
    their KS account from a US address (Delaware/CA/NY) — those don't appear
    in the geo-filtered list.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from .http import fetch, RateLimiter

DISCOVER_SEEDS = [
    # ── China-labeled (woe_id=23424781) — 5 sort/state slices ──────────────
    "https://www.kickstarter.com/discover/advanced?woe_id=23424781&sort=newest",
    "https://www.kickstarter.com/discover/advanced?woe_id=23424781&state=live&sort=newest",
    "https://www.kickstarter.com/discover/advanced?woe_id=23424781&state=live&sort=most_funded",
    "https://www.kickstarter.com/discover/advanced?woe_id=23424781&state=live&sort=most_backed",
    "https://www.kickstarter.com/discover/advanced?woe_id=23424781&state=upcoming&sort=popularity",
    # ── Global Tech (category_id=16) — 4 slices, catches CN brands listed in US ──
    "https://www.kickstarter.com/discover/advanced?category_id=16&state=upcoming&sort=popularity",
    "https://www.kickstarter.com/discover/advanced?category_id=16&state=upcoming&sort=newest",
    "https://www.kickstarter.com/discover/advanced?category_id=16&state=live&sort=most_funded",
    "https://www.kickstarter.com/discover/advanced?category_id=16&state=live&sort=newest",
    # ── Global Design / Product Design (category_id=7) — 4 slices ─────────
    "https://www.kickstarter.com/discover/advanced?category_id=7&state=upcoming&sort=popularity",
    "https://www.kickstarter.com/discover/advanced?category_id=7&state=upcoming&sort=newest",
    "https://www.kickstarter.com/discover/advanced?category_id=7&state=live&sort=most_funded",
    "https://www.kickstarter.com/discover/advanced?category_id=7&state=live&sort=newest",
    # ── Keyword search — picks up off-category Chinese hardware (Shenzhen) ──
    "https://www.kickstarter.com/discover/advanced?term=shenzhen&state=upcoming&sort=popularity",
]

# Cap pages per seed to avoid pulling thousands of rows. The signal lives near
# the top of each sort order; tail is mostly noise we'd filter out anyway.
MAX_PAGES_PER_SEED = 8


@dataclass
class DiscoverHit:
    pathname: str          # /projects/<creator>/<slug>
    url: str
    title: str | None
    blurb: str | None
    creator_slug: str | None
    creator_name: str | None
    location: str | None   # displayable_name e.g. "Shanghai, China"
    country: str | None    # ISO-2, e.g. "CN", "HK", "US"
    state: str | None      # "live" | "successful" | "failed" | "submitted" (≈ prelaunch)
    staff_pick: bool = False
    backers_count: int | None = None
    pledged_usd: float | None = None
    goal_usd: float | None = None
    percent_funded: float | None = None
    deadline: int | None = None     # epoch seconds
    launched_at: int | None = None
    created_at: int | None = None
    state_changed_at: int | None = None  # last state transition (= prelaunch start for "submitted")
    prelaunch_activated: bool | None = None
    category: str | None = None
    image_url: str | None = None        # photo.full from KS Discover JSON
    raw: dict[str, Any] = field(default_factory=dict)


def _hit_from_proj(p: dict[str, Any]) -> DiscoverHit:
    urls = (p.get("urls") or {}).get("web") or {}
    project_url = urls.get("project") or ""
    pathname = project_url.replace("https://www.kickstarter.com", "", 1) if project_url else ""
    creator = p.get("creator") or {}
    location = p.get("location") or {}
    category = p.get("category") or {}
    return DiscoverHit(
        pathname=pathname,
        url=project_url,
        title=p.get("name"),
        blurb=p.get("blurb"),
        creator_slug=creator.get("slug"),
        creator_name=creator.get("name"),
        location=location.get("displayable_name") or location.get("name"),
        country=p.get("country") or location.get("country"),
        state=p.get("state"),
        staff_pick=bool(p.get("staff_pick")),
        backers_count=p.get("backers_count"),
        pledged_usd=p.get("usd_pledged") or p.get("converted_pledged_amount"),
        goal_usd=(p.get("goal") or 0) * (p.get("static_usd_rate") or 1.0) if p.get("goal") else None,
        percent_funded=p.get("percent_funded"),
        deadline=p.get("deadline"),
        launched_at=p.get("launched_at"),
        created_at=p.get("created_at"),
        state_changed_at=p.get("state_changed_at"),
        prelaunch_activated=p.get("prelaunch_activated"),
        category=category.get("name"),
        image_url=(p.get("photo") or {}).get("full"),
        raw=p,
    )


def _walk_seed(seed_url: str, *, pacer: RateLimiter) -> Iterator[DiscoverHit]:
    sep = "&" if "?" in seed_url else "?"
    for page in range(1, MAX_PAGES_PER_SEED + 1):
        pacer.wait()
        page_url = f"{seed_url}{sep}format=json&page={page}"
        try:
            r = fetch(page_url)
        except RuntimeError as e:
            print(f"  ! seed page failed: {page_url}\n    {e}")
            return
        try:
            data = r.json()
        except Exception:
            print(f"  ! seed returned non-JSON (likely Cloudflare HTML challenge slipped through): {page_url}")
            return
        projects = data.get("projects") or []
        for p in projects:
            yield _hit_from_proj(p)
        if not data.get("has_more"):
            return


def crawl_discover(seeds: Iterable[str] = DISCOVER_SEEDS) -> dict[str, DiscoverHit]:
    """Returns {pathname: DiscoverHit}, deduped across all seeds.

    First-seen wins. Order of DISCOVER_SEEDS thus matters: put the highest-
    signal seeds first so their richer metadata is preferred.
    """
    pacer = RateLimiter(qps=0.6)  # ~1 request per 1.7s — well under any threshold
    out: dict[str, DiscoverHit] = {}
    for seed in seeds:
        before = len(out)
        for hit in _walk_seed(seed, pacer=pacer):
            if not hit.pathname:
                continue
            out.setdefault(hit.pathname, hit)
        print(f"  seed: {seed[51:120]:<70} +{len(out)-before} new (total {len(out)})")
    return out


if __name__ == "__main__":
    hits = crawl_discover()
    print(f"\ndiscovered {len(hits)} unique projects")
    for h in list(hits.values())[:10]:
        funded = f"{h.percent_funded*100:.0f}%" if h.percent_funded else "—"
        print(f"  {h.country:>3} {h.state:<12} {funded:>5}  {h.title[:60] if h.title else '?'}")
