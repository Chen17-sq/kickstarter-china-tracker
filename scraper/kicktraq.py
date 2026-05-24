"""Kicktraq RSS — CF-free secondary discovery source.

Kicktraq (kicktraq.com) tracks 600K+ KS projects and publishes public
RSS feeds that mirror their internal lists. Crucially, these feeds are
NOT behind Cloudflare — they're served by a separate origin and have
never blocked us. That makes them a useful "second source" for
discovery when KS's own /discover/advanced endpoint is CF-blocked.

Feed URLs (verified 2026-05-24):
  /rss/dayones-latest.rss          — newest "Day-1" early-stage projects
  /rss/dayones-ending.rss          — Day-1 projects ending soon
  /rss/soclose-latest.rss          — close-to-funding (just-launched-ish)
  /rss/soclose-ending.rss          — close-to-funding ending soon
  /rss/kickingitforward-latest.rss — KIF (creators who back others)
  /rss/kickingitforward-ending.rss — KIF ending soon

Each item has a <link> pointing to kicktraq.com/projects/<creator>/<slug>/
from which we derive the canonical KS pathname /projects/<creator>/<slug>.

How we use it: when scraper/discover.py's own crawl returns fewer than
the floor count (today's case: 4/14 seeds CF-blocked), we pull these
RSS feeds and add any KS pathnames that aren't already in the discover
set. Then the rest of the pipeline (classify, watchesCount fetch, ...)
treats them like any other discovered project.

Limitations:
  - The 6 feeds are curated lists, not "everything" — coverage is biased
    toward the niches Kicktraq surfaces. Better than nothing when KS is
    blocked, but not a full replacement for /discover/advanced.
  - We get the pathname + title but NO usd_pledged/backers/state. Those
    still come from GraphQL after the pathname is in the pool.
  - We don't filter for China-background here — classify.py handles
    that downstream when we hand it the pathnames.

Cost: 6 HTTPS requests/day to a non-CF endpoint. ~30KB total. Free.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

# Verified working as of 2026-05-24. If Kicktraq restructures their site,
# we'll see empty results and fall back to no supplement.
FEED_URLS = [
    "https://www.kicktraq.com/rss/dayones-latest.rss",
    "https://www.kicktraq.com/rss/dayones-ending.rss",
    "https://www.kicktraq.com/rss/soclose-latest.rss",
    "https://www.kicktraq.com/rss/soclose-ending.rss",
    "https://www.kicktraq.com/rss/kickingitforward-latest.rss",
    "https://www.kicktraq.com/rss/kickingitforward-ending.rss",
]

# Kicktraq URL → /projects/<creator>/<slug>/ — strip the trailing slash
# and host to get our canonical pathname.
RE_KICKTRAQ_PROJECT = re.compile(
    r"kicktraq\.com(/projects/[A-Za-z0-9_\-]+/[A-Za-z0-9_\-]+)/?"
)

# Single <item> block — extract link + title
RE_RSS_ITEM = re.compile(
    r"<item>(.*?)</item>", re.DOTALL | re.IGNORECASE
)
RE_LINK = re.compile(r"<link>([^<]+)</link>", re.IGNORECASE)
RE_TITLE = re.compile(
    r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class KicktraqHit:
    pathname: str   # /projects/<creator>/<slug>
    title: str
    source_feed: str

    @property
    def ks_url(self) -> str:
        return f"https://www.kickstarter.com{self.pathname}"


def parse_feed(xml: str, source_feed: str) -> list[KicktraqHit]:
    """Extract KS pathnames from one Kicktraq RSS XML blob."""
    out: list[KicktraqHit] = []
    seen: set[str] = set()
    for item in RE_RSS_ITEM.findall(xml):
        link_match = RE_LINK.search(item)
        if not link_match:
            continue
        url_match = RE_KICKTRAQ_PROJECT.search(link_match.group(1))
        if not url_match:
            continue
        pathname = url_match.group(1)
        if pathname in seen:
            continue
        seen.add(pathname)
        title_match = RE_TITLE.search(item)
        title = (title_match.group(1).strip() if title_match else "").replace(
            "<![CDATA[", ""
        ).replace("]]>", "").strip()
        out.append(KicktraqHit(pathname=pathname, title=title, source_feed=source_feed))
    return out


def fetch_all(*, verbose: bool = True, timeout: float = 15.0) -> list[KicktraqHit]:
    """Fetch all 6 Kicktraq feeds, dedupe across them, return a flat list.

    Failures on individual feeds are silently swallowed — we'd rather
    have partial supplement than no supplement when our own discover is
    already underperforming.
    """
    all_hits: list[KicktraqHit] = []
    seen: set[str] = set()
    for feed_url in FEED_URLS:
        try:
            r = httpx.get(feed_url, timeout=timeout, headers={
                "User-Agent": "Mozilla/5.0 (compatible; ks-tracker-bot/1.0; +https://ks.aldrich.fyi)",
            })
            if r.status_code != 200:
                if verbose:
                    print(f"  kicktraq {feed_url.rsplit('/', 1)[-1]}: status {r.status_code}")
                continue
            hits = parse_feed(r.text, source_feed=feed_url)
            for h in hits:
                if h.pathname not in seen:
                    seen.add(h.pathname)
                    all_hits.append(h)
            if verbose:
                feed_name = feed_url.rsplit("/", 1)[-1].replace(".rss", "")
                print(f"  kicktraq {feed_name}: {len(hits)} items")
        except Exception as e:
            if verbose:
                print(f"  kicktraq {feed_url.rsplit('/', 1)[-1]}: error {e}")
            continue
    if verbose:
        print(f"  kicktraq total deduped: {len(all_hits)} unique KS pathnames")
    return all_hits


if __name__ == "__main__":
    import sys
    hits = fetch_all(verbose=True)
    print("\nTop 10 pathnames:")
    for h in hits[:10]:
        print(f"  {h.pathname}  ({h.title[:50]})")
    sys.exit(0 if hits else 1)
