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

Anti-bot stack (applied to each request in order of cost):
  1. ONE warm curl_cffi session (warm_client()) for the whole crawl —
     cookies + CF clearance persist across all 14 seeds, so we look like
     a continued browsing session rather than 14 fresh visitors.
  2. TLS impersonation rotation per retry (http.fetch rotates 8 profiles).
  3. Playwright fallback (lazy) for pages where curl_cffi exhausts all
     8 retries. Reuses one browser across all subsequent fallback hits
     to amortize the ~5s startup cost.
"""
from __future__ import annotations
import json as _json
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Optional

from .http import fetch, warm_client, RateLimiter
from . import health

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

PLAYWRIGHT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


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


class _DiscoverPlaywright:
    """Lazy Playwright fallback for the Discover JSON endpoint.

    When curl_cffi.fetch() exhausts its 8-impersonation rotation and
    raises RuntimeError, we open a real Chromium and use
    `page.evaluate("fetch(...)")` to grab the JSON. The browser request
    runs through the real browser HTTP stack (real TLS, real sec-ch-ua,
    real cookies), so CF treats it as a normal page navigation.

    Lazy + reused: the browser only starts on the first failed seed
    (~5s cost) and stays open for the rest of the crawl. Subsequent
    fallback hits are ~500ms each.
    """

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None
        self._opened = False
        self._failed = False  # once we've failed to open, stop trying

    def _ensure_open(self) -> bool:
        if self._opened:
            return True
        if self._failed:
            return False
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("  ! Playwright not installed; discover fallback unavailable")
            self._failed = True
            return False
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch()
            self._ctx = self._browser.new_context(
                user_agent=PLAYWRIGHT_UA,
                locale="en-US",
                viewport={"width": 1280, "height": 800},
            )
            self._page = self._ctx.new_page()
            # Pre-warm: navigate to KS discover so CF drops session cookies
            # BEFORE any JSON fetch. CF often inspects whether the requester
            # is "transitioning" from a real page vs. spawning headless.
            self._page.goto(
                "https://www.kickstarter.com/discover/advanced",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            self._page.wait_for_timeout(1200)
            n_cookies = len(self._ctx.cookies())
            print(f"  📺 discover Playwright fallback warmed up ({n_cookies} cookies)")
            self._opened = True
            return True
        except Exception as e:
            print(f"  ! discover Playwright open failed: {e}")
            self._failed = True
            self._close_quiet()
            return False

    def fetch_json(self, url: str) -> Optional[dict]:
        """Return parsed JSON, or None if anything went wrong.

        IMPORTANT — `X-Requested-With: XMLHttpRequest` is required by the
        KS discover JSON endpoint. Plain `fetch()` from Playwright (or
        any modern browser) does NOT add this header by default, but
        legacy AJAX libs (jQuery.ajax, etc.) do — and KS specifically
        accepts only that flavor for `format=json` URLs. Without it the
        endpoint returns 403 even with valid CF clearance cookies. We
        verified this empirically in a local probe: same URL, with the
        header → 200 JSON; without → 403 HTML.
        """
        if not self._ensure_open():
            return None
        try:
            result = self._page.evaluate(
                """async (url) => {
                    try {
                        const r = await fetch(url, {
                            headers: {
                                'Accept': 'application/json',
                                'X-Requested-With': 'XMLHttpRequest',
                            },
                            credentials: 'include',
                        });
                        const text = await r.text();
                        return { status: r.status, text: text };
                    } catch (e) {
                        return { status: -1, text: String(e) };
                    }
                }""",
                url,
            )
        except Exception as e:
            print(f"    ! Playwright fetch crashed: {e}")
            return None
        status = int(result.get("status", -1))
        if status != 200:
            print(f"    ! Playwright fetch returned status {status}")
            return None
        text = result.get("text") or ""
        try:
            return _json.loads(text)
        except Exception as e:
            print(f"    ! Playwright fetch returned non-JSON ({e}); first 80 chars: {text[:80]!r}")
            return None

    def _close_quiet(self) -> None:
        for obj_name in ("_page", "_ctx", "_browser"):
            obj = getattr(self, obj_name, None)
            if obj is None:
                continue
            try:
                obj.close()
            except Exception:
                pass
            setattr(self, obj_name, None)
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def close(self) -> None:
        self._close_quiet()
        self._opened = False


def _walk_seed(
    seed_url: str,
    *,
    pacer: RateLimiter,
    client,
    pw_fallback: _DiscoverPlaywright,
) -> Iterator[DiscoverHit]:
    sep = "&" if "?" in seed_url else "?"
    seed_had_failure = False  # so we only bump the "seed had a page failure" counter once
    for page in range(1, MAX_PAGES_PER_SEED + 1):
        pacer.wait()
        page_url = f"{seed_url}{sep}format=json&page={page}"
        data: Optional[dict] = None

        # Path 1: curl_cffi (warm session)
        try:
            r = fetch(page_url, client=client)
            data = r.json()
        except RuntimeError as e:
            # All impersonations exhausted — try Playwright fallback
            print(f"  ! curl_cffi exhausted on {page_url}\n    {e}; trying Playwright")
            if not seed_had_failure:
                health.discover_seed_page_failed_curl_cffi()
                seed_had_failure = True
            data = pw_fallback.fetch_json(page_url)
            if data is not None:
                health.discover_playwright_used(pages=1)
        except Exception:
            # JSON decode error or other — try Playwright too
            print(f"  ! seed returned non-JSON: {page_url}; trying Playwright")
            if not seed_had_failure:
                health.discover_seed_page_failed_curl_cffi()
                seed_had_failure = True
            data = pw_fallback.fetch_json(page_url)
            if data is not None:
                health.discover_playwright_used(pages=1)

        if not data:
            # Both paths failed — give up on this seed
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

    Uses a single warmed curl_cffi session for the whole crawl (cookies
    persist across all 14 seeds). On per-page CF block, lazily opens a
    Playwright fallback that gets reused for any subsequent blocked pages.
    """
    pacer = RateLimiter(qps=0.6)  # ~1 request per 1.7s — well under any threshold
    # ── Warm-up: visit homepage once before any data fetch so CF drops its
    #    session cookies into our session. Without this, every fetch starts
    #    cold and looks fresher to CF than necessary.
    client = warm_client(verbose=True)
    pw_fallback = _DiscoverPlaywright()  # lazy; only opens on first failure

    out: dict[str, DiscoverHit] = {}
    try:
        for seed in seeds:
            health.discover_seed_started()
            before = len(out)
            for hit in _walk_seed(seed, pacer=pacer, client=client, pw_fallback=pw_fallback):
                if not hit.pathname:
                    continue
                out.setdefault(hit.pathname, hit)
            print(f"  seed: {seed[51:120]:<70} +{len(out)-before} new (total {len(out)})")
    finally:
        pw_fallback.close()
    health.discover_finalize(candidates_total=len(out))
    return out


if __name__ == "__main__":
    hits = crawl_discover()
    print(f"\ndiscovered {len(hits)} unique projects")
    for h in list(hits.values())[:10]:
        funded = f"{h.percent_funded*100:.0f}%" if h.percent_funded else "—"
        print(f"  {h.country:>3} {h.state:<12} {funded:>5}  {h.title[:60] if h.title else '?'}")
