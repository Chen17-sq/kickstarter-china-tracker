"""Walk Kickstarter Discover pages and yield candidate project URLs.

Why several seeds?
  - China geo filter (woe_id=23424781) gets the projects KS *labels* as Chinese.
  - Tech / Design upcoming + popularity catches Chinese brands that register their
    KS account from a US address (Delaware/CA/NY) — they don't show up in the
    geo-filtered list.

The Discover HTML is server-rendered, so plain `httpx + selectolax` is enough.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Iterator
from selectolax.parser import HTMLParser

from .http import make_client, RateLimiter

DISCOVER_SEEDS = [
    # China-labeled, all states
    "https://www.kickstarter.com/discover/advanced?woe_id=23424781&sort=newest",
    "https://www.kickstarter.com/discover/advanced?woe_id=23424781&sort=most_funded&state=live",
    "https://www.kickstarter.com/discover/advanced?woe_id=23424781&state=upcoming&sort=popularity",
    "https://www.kickstarter.com/discover/advanced?woe_id=23424781&sort=most_backed&state=live",
    # Global Tech category (catches Chinese brands listed in US)
    "https://www.kickstarter.com/discover/advanced?state=upcoming&category_id=16&sort=popularity",
    "https://www.kickstarter.com/discover/advanced?state=live&category_id=16&sort=most_funded",
    # Global Design category (Product Design hardware)
    "https://www.kickstarter.com/discover/advanced?state=upcoming&category_id=7&sort=popularity",
    "https://www.kickstarter.com/discover/advanced?state=live&category_id=7&sort=most_funded",
]


@dataclass
class DiscoverHit:
    url: str          # absolute project URL
    pathname: str     # /projects/<creator>/<slug>
    title: str
    creator: str | None
    location: str | None
    blurb: str | None


def _walk_seed(client, url: str, max_pages: int = 4) -> Iterator[DiscoverHit]:
    for page in range(1, max_pages + 1):
        sep = "&" if "?" in url else "?"
        page_url = f"{url}{sep}page={page}"
        r = client.get(page_url)
        if r.status_code != 200:
            return
        tree = HTMLParser(r.text)
        cards = tree.css("div[data-project-id]") or tree.css("a[href^='/projects/']")
        if not cards:
            return
        seen_in_page = set()
        for a in tree.css("a[href^='/projects/']"):
            href = a.attributes.get("href", "")
            # path looks like /projects/<creator>/<slug>?ref=...
            path = href.split("?", 1)[0]
            if path.count("/") < 3:
                continue
            if path in seen_in_page:
                continue
            seen_in_page.add(path)
            title = (a.text() or "").strip()[:120]
            yield DiscoverHit(
                url="https://www.kickstarter.com" + path,
                pathname=path,
                title=title,
                creator=path.split("/")[2] if path.count("/") >= 3 else None,
                location=None,
                blurb=None,
            )


def crawl_discover(seeds: Iterable[str] = DISCOVER_SEEDS) -> dict[str, DiscoverHit]:
    """Returns {pathname: DiscoverHit} merged across all seeds."""
    pacer = RateLimiter(qps=1.0)
    out: dict[str, DiscoverHit] = {}
    with make_client() as client:
        for seed in seeds:
            pacer.wait()
            for hit in _walk_seed(client, seed):
                # Dedup; keep the first-seen variant
                out.setdefault(hit.pathname, hit)
                pacer.wait()
    return out


if __name__ == "__main__":
    hits = crawl_discover()
    print(f"discovered {len(hits)} unique project pathnames")
    for h in list(hits.values())[:10]:
        print(" ", h.pathname, "—", h.title[:60])
