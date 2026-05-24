"""Fetch supplementary project data via the KS GraphQL endpoint.

The Discover JSON endpoint gives us 90% of what we need (name, creator,
location, country, pledged, backers, staff_pick, deadline …). The one
missing piece — the prelaunch follower count — is *not* in the SSR HTML
either; KS injects it client-side after page mount.

But KS exposes a public GraphQL endpoint at /graph that accepts anonymous
queries with just a CSRF token from the meta tag of any page. The field
is `watchesCount` on the Project type — that's the prelaunch follower
count visible on the "Notify me on launch" UI.

We batch all slugs into a single aliased GraphQL query (chunked at 50)
so 138 projects → ~3 round trips instead of 138.

Anti-bot strategy (in order of fall-through):
  1. curl_cffi with TLS impersonation rotation — fast, usually works.
     If the seed GET succeeds, we keep curl_cffi for the POSTs too —
     the TLS fingerprint that got us past CF on the GET is the same
     fingerprint CF will accept on subsequent POSTs.
  2. Playwright headless Chromium END-TO-END fallback — when CF 403's
     the curl_cffi GET across all TLS impersonations, we don't just
     borrow the cookies and hand them to curl_cffi (CF can still tell
     the difference by TLS + sec-ch-ua + cookie ordering). Instead we
     route the GraphQL POSTs through the SAME browser context via
     `ctx.request.post()`, which preserves the entire fingerprint.

History of how this evolved:
  - v1: curl_cffi only — broke when CF tightened.
  - v2: curl_cffi → Playwright for seed, curl_cffi for POSTs — broke
        when CF started cross-checking TLS vs cookies (5-09, 5-12).
  - v3: curl_cffi → Playwright for seed + POSTs — current.
"""
from __future__ import annotations

import json
import random
import re
import time
from typing import Optional

from curl_cffi import requests as cc_requests

from . import health
from .http import (
    DEFAULT_COOKIES,
    IMPERSONATE_ROTATION,
    curl_cffi_proxies,
    pick_proxy,
    playwright_proxy,
)

GRAPH_URL = "https://www.kickstarter.com/graph"
SEED_URL = "https://www.kickstarter.com/discover/advanced?state=upcoming"
RE_CSRF = re.compile(r'<meta[^>]*name="csrf-token"[^>]*content="([^"]+)"')

CHUNK_SIZE = 50
PLEDGE_CHUNK_SIZE = 25  # rewards expansion roughly doubles response per project
SEED_MAX_ATTEMPTS = 4
PLAYWRIGHT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class _Transport:
    """Uniform interface over curl_cffi or Playwright for GraphQL POSTs.

    Built either:
      - from_curl_cffi(client, csrf)    — fast path
      - from_playwright(pw, browser, ctx, page, csrf) — fallback when CF
        blocks curl_cffi entirely. POSTs run via `page.evaluate(fetch(...))`
        so the request goes through the REAL browser HTTP stack: browser
        TLS fingerprint, sec-ch-ua, cookie ordering, accept-language, the
        works. (Playwright's APIRequestContext is NOT this — it shares
        cookies but uses its own Node-based HTTP client, which CF still
        spots as non-browser.)

    Lifecycle: callers MUST call .close() (usually via try/finally) to
    release the Playwright runtime + browser process. curl_cffi sessions
    are GC-safe so close() is a no-op for them.
    """

    @classmethod
    def from_curl_cffi(cls, client: cc_requests.Session, csrf: str) -> _Transport:
        t = cls.__new__(cls)
        t._cc = client
        t._pw_runtime = None
        t._pw_browser = None
        t._pw_ctx = None
        t._pw_page = None
        t.csrf = csrf
        t.mode = "curl_cffi"
        return t

    @classmethod
    def from_playwright(cls, pw, browser, ctx, page, csrf: str) -> _Transport:
        t = cls.__new__(cls)
        t._cc = None
        t._pw_runtime = pw
        t._pw_browser = browser
        t._pw_ctx = ctx
        t._pw_page = page
        t.csrf = csrf
        t.mode = "playwright"
        return t

    def post_graphql(self, body: dict) -> tuple[int, dict | None]:
        """POST a GraphQL query, return (status, parsed_json_or_None).

        Status -1 indicates a transport-level exception (network error,
        timeout, ...). Status != 200 means CF blocked or KS returned an
        error; data will be None either way."""
        headers = {
            "X-CSRF-Token": self.csrf,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = json.dumps(body)
        if self._cc is not None:
            headers["Referer"] = "https://www.kickstarter.com/"
            try:
                r = self._cc.post(GRAPH_URL, headers=headers, data=payload)
            except Exception:
                return -1, None
            if r.status_code != 200:
                return r.status_code, None
            try:
                return r.status_code, r.json()
            except Exception:
                return r.status_code, None
        # Playwright path — POST runs INSIDE the browser via page.evaluate
        # (fetch). Browser supplies TLS fingerprint, sec-ch-ua, cookies,
        # accept-language — everything CF checks beyond a cookie match.
        try:
            result = self._pw_page.evaluate(
                """async ({url, headers, body}) => {
                    try {
                        const r = await fetch(url, {
                            method: 'POST',
                            headers: headers,
                            body: body,
                            credentials: 'include',
                        });
                        const text = await r.text();
                        return { status: r.status, text: text };
                    } catch (e) {
                        return { status: -1, text: String(e) };
                    }
                }""",
                {
                    "url": GRAPH_URL,
                    "headers": headers,  # browser adds Referer/Origin/sec-ch-ua itself
                    "body": payload,
                },
            )
        except Exception:
            return -1, None
        status = int(result.get("status", -1))
        text = result.get("text") or ""
        if status != 200:
            return status, None
        try:
            return status, json.loads(text)
        except Exception:
            return status, None

    def close(self) -> None:
        """Release any external resources. Safe to call multiple times."""
        if self._pw_runtime is None:
            return
        try:
            if self._pw_page is not None:
                self._pw_page.close()
        except Exception:
            pass
        try:
            if self._pw_browser is not None:
                self._pw_browser.close()
        except Exception:
            pass
        try:
            self._pw_runtime.stop()
        except Exception:
            pass
        self._pw_runtime = None
        self._pw_browser = None
        self._pw_ctx = None
        self._pw_page = None


def _try_curl_cffi_seed(
    label: str, verbose: bool
) -> tuple[cc_requests.Session, str] | None:
    """Try every TLS impersonation in rotation; return (client, csrf) or None."""
    for attempt in range(SEED_MAX_ATTEMPTS):
        impersonate = IMPERSONATE_ROTATION[attempt % len(IMPERSONATE_ROTATION)]
        client = cc_requests.Session(impersonate=impersonate, timeout=30)
        # Route through KS_PROXY if set (random pick per attempt — so different
        # retries may hit different proxy IPs, which helps if one is degraded).
        px = curl_cffi_proxies(pick_proxy())
        if px:
            client.proxies = px
        for k, v in DEFAULT_COOKIES.items():
            client.cookies.set(k, v)
        try:
            r = client.get(SEED_URL, headers={"Referer": "https://www.kickstarter.com/"})
        except Exception as e:
            if verbose:
                print(f"  {label} seed attempt {attempt+1} ({impersonate}): exception {e}")
            time.sleep(1.5 + attempt + random.random())
            continue
        if r.status_code == 200:
            m = RE_CSRF.search(r.text)
            if m:
                return client, m.group(1)
            elif verbose:
                print(f"  {label} seed attempt {attempt+1} ({impersonate}): 200 but no CSRF token")
        elif verbose:
            print(f"  {label} seed attempt {attempt+1} ({impersonate}): status {r.status_code}")
        time.sleep(2 + attempt + random.random() * 1.5)
    return None


def _open_playwright_transport(label: str, verbose: bool) -> _Transport | None:
    """Spin up sync Playwright, seed CSRF, return a Transport that POSTs via
    the same browser context. The whole CF-acceptable fingerprint is reused.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if verbose:
            print("  ! Playwright not installed; cannot fall back")
        return None

    pw = None
    browser = None
    page = None
    try:
        pw = sync_playwright().start()
        launch_kwargs = {}
        pxy = playwright_proxy(pick_proxy())
        if pxy:
            launch_kwargs["proxy"] = pxy
        browser = pw.chromium.launch(**launch_kwargs)
        ctx = browser.new_context(
            user_agent=PLAYWRIGHT_UA,
            locale="en-US",
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()
        page.goto(SEED_URL, wait_until="domcontentloaded", timeout=30_000)
        # Give Cloudflare's interactive challenge a beat to clear
        page.wait_for_timeout(800)
        csrf = page.evaluate(
            "() => { const m = document.querySelector('meta[name=\"csrf-token\"]'); return m ? m.content : null; }"
        )
        if not csrf:
            raise RuntimeError("CSRF token not found after Playwright navigation")
        # IMPORTANT: keep the page open. We use page.evaluate('fetch(...)')
        # for the subsequent GraphQL POSTs so each request gets the real
        # browser TLS fingerprint + sec-ch-ua headers. Closing the page
        # would force a new context and lose those.
        if verbose:
            n_cookies = len(ctx.cookies())
            print(
                f"  {label} ✅ seeded via Playwright "
                f"(csrf len={len(csrf)}, {n_cookies} cookies)"
            )
        return _Transport.from_playwright(pw, browser, ctx, page, csrf)
    except Exception as e:
        if verbose:
            print(f"  ! Playwright seed exception: {e}")
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if pw is not None:
            try:
                pw.stop()
            except Exception:
                pass
        return None


def _open_transport(label: str, verbose: bool = True) -> _Transport | None:
    """Try curl_cffi first (fast). If all rotations 403, fall back to a
    Playwright-end-to-end transport — same browser context handles both
    the seed and the POSTs, so the TLS fingerprint stays consistent."""
    cc = _try_curl_cffi_seed(label, verbose)
    if cc is not None:
        client, csrf = cc
        return _Transport.from_curl_cffi(client, csrf)
    if verbose:
        print(f"  {label} curl_cffi seed failed; falling back to Playwright (full session)")
    return _open_playwright_transport(label, verbose)


def open_transport(label: str = "ks_graphql", *, verbose: bool = True) -> _Transport | None:
    """Public alias of _open_transport — for callers that want to share
    one session across both watches + pledge_min fetches.

    Why share: opening two separate Playwright sessions back-to-back trips
    CF's "burst of fresh sessions" detector. As of 2026-05-24 cron logs,
    pledge_min was consistently 403'd on chunks even with a successful
    Playwright seed — likely because it was the SECOND Playwright in 30s.
    Sharing the session collapses two suspicious patterns into one.
    """
    return _open_transport(label, verbose=verbose)


def fetch_watches_counts(
    slugs: list[str],
    *,
    verbose: bool = True,
    transport: _Transport | None = None,
) -> dict[str, Optional[int]]:
    """Batch-fetch `watchesCount` for project slugs via KS GraphQL.

    Returns {slug: count_or_None}. Slugs that error out individually still
    appear in the dict mapped to None — callers can fall back gracefully.

    A slug is the *last* segment of the KS pathname:
        /projects/creator/foo-bar  →  "foo-bar"

    If `transport` is provided, use it and DO NOT close it (caller owns
    lifecycle). Otherwise open + close internally.
    """
    out: dict[str, Optional[int]] = {s: None for s in slugs}
    if not slugs:
        return out

    own_transport = transport is None
    if own_transport:
        transport = _open_transport(label="watchesCount", verbose=verbose)
        if transport is None:
            if verbose:
                print("  watchesCount: failed to seed (curl_cffi + Playwright); skipping")
            health.watches_done(path="failed", fetched=0, requested=len(slugs))
            return out

    try:
        # Chunked batch GraphQL query, one round trip per ~50 slugs.
        for i in range(0, len(slugs), CHUNK_SIZE):
            chunk = slugs[i : i + CHUNK_SIZE]
            # Build aliased query: p0: project(slug: $s0) { watchesCount } …
            # Use variables (not interpolated strings) — safer + cacheable.
            var_decls = ", ".join(f"$s{j}: String!" for j in range(len(chunk)))
            fields = "\n  ".join(
                f"p{j}: project(slug: $s{j}) {{ watchesCount }}"
                for j in range(len(chunk))
            )
            query = f"query Watches({var_decls}) {{\n  {fields}\n}}"
            variables = {f"s{j}": s for j, s in enumerate(chunk)}
            body = {"operationName": "Watches", "variables": variables, "query": query}

            status, jdata = transport.post_graphql(body)
            if status != 200:
                if verbose:
                    print(f"  watchesCount chunk {i//CHUNK_SIZE+1}: status {status}")
                continue
            data = (jdata or {}).get("data") or {}
            for j, s in enumerate(chunk):
                obj = data.get(f"p{j}")
                if isinstance(obj, dict) and "watchesCount" in obj:
                    out[s] = obj["watchesCount"]
        # Record which transport actually carried the data
        fetched = sum(1 for v in out.values() if v is not None)
        health.watches_done(path=transport.mode, fetched=fetched, requested=len(slugs))
    finally:
        if own_transport:
            transport.close()
    return out


def fetch_pledge_minimums(
    slugs: list[str],
    *,
    verbose: bool = True,
    transport: _Transport | None = None,
) -> dict[str, Optional[float]]:
    """Batch-fetch minimum pledge tier (in USD) for project slugs.

    Returns {slug: usd_amount_or_None}. We pull all reward tiers via the
    same /graph endpoint as fetch_watches_counts — but with a smaller
    chunk size (25) since the rewards array roughly doubles the response
    per project.

    Strategy: for each project, take min(amount) across all rewards with
    amount > 0. Some KS projects have a $1 'support us' reward — we keep
    it as the minimum because the user-facing display formats $1 fine
    and editorial nuance can be handled in the UI layer.

    Currency is forced to USD via the `currency` cookie (set in
    DEFAULT_COOKIES), so amounts come back already converted.

    If `transport` is provided, use it and DO NOT close it (caller owns
    lifecycle). Otherwise open + close internally.
    """
    out: dict[str, Optional[float]] = {s: None for s in slugs}
    if not slugs:
        return out

    own_transport = transport is None
    if own_transport:
        transport = _open_transport(label="pledge_min", verbose=verbose)
        if transport is None:
            if verbose:
                print("  pledge_min: failed to seed; skipping")
            health.pledge_done(path="failed", fetched=0, requested=len(slugs))
            return out

    try:
        for i in range(0, len(slugs), PLEDGE_CHUNK_SIZE):
            chunk = slugs[i : i + PLEDGE_CHUNK_SIZE]
            var_decls = ", ".join(f"$s{j}: String!" for j in range(len(chunk)))
            fields = "\n  ".join(
                f"p{j}: project(slug: $s{j}) {{ rewards(first: 30) {{ nodes {{ amount {{ amount currency }} }} }} }}"
                for j in range(len(chunk))
            )
            query = f"query Pledges({var_decls}) {{\n  {fields}\n}}"
            variables = {f"s{j}": s for j, s in enumerate(chunk)}
            body = {"operationName": "Pledges", "variables": variables, "query": query}

            status, jdata = transport.post_graphql(body)
            if status != 200:
                if verbose:
                    print(f"  pledge_min chunk {i//PLEDGE_CHUNK_SIZE+1}: status {status}")
                continue
            data = (jdata or {}).get("data") or {}
            for j, s in enumerate(chunk):
                obj = data.get(f"p{j}") or {}
                rewards = (obj.get("rewards") or {}).get("nodes") or []
                amounts: list[float] = []
                for node in rewards:
                    amt_obj = node.get("amount") or {}
                    try:
                        amt = float(amt_obj.get("amount") or 0)
                        if amt > 0:
                            amounts.append(amt)
                    except (TypeError, ValueError):
                        pass
                if amounts:
                    out[s] = min(amounts)
        fetched = sum(1 for v in out.values() if v is not None)
        health.pledge_done(path=transport.mode, fetched=fetched, requested=len(slugs))
    finally:
        if own_transport:
            transport.close()
    return out


def slug_from_pathname(pathname: str) -> str:
    """`/projects/creator/foo-bar` → `foo-bar`."""
    return (pathname or "").rstrip("/").split("/")[-1]


if __name__ == "__main__":
    import sys
    slugs = sys.argv[1:] or [
        "ayaneo-pocket-play-mobile-phone-and-gaming-handheld-in-one",
        "xgimi-titan-noir-series-4k-projector",
        "la-seine-espresso-machine",
    ]
    counts = fetch_watches_counts(slugs)
    for s, c in counts.items():
        print(f"  {c if c is not None else '—':>8}  {s}")
