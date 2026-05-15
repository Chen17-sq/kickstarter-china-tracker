"""HTTP client — Cloudflare-bypassing TLS impersonation via curl_cffi.

Plain httpx returns a 403 "Just a moment..." Cloudflare challenge from KS.
curl_cffi matches a real browser's TLS+HTTP/2 fingerprint and gets through.
The challenge still fires probabilistically, so fetch() rotates the
impersonation profile + backs off on 403.

Anti-bot stack used by this layer:

  * TLS fingerprint rotation — IMPERSONATE_ROTATION below has 8 entries
    spanning Safari / Chrome / Edge / Firefox + recent versions. Rotating
    on every retry attempt lowers the chance CF has fingerprinted our
    pattern.

  * Persistent warm session (warm_client()) — visit the KS homepage first
    so CF drops its session cookie + clearance cookie before we make any
    data request. A cold curl_cffi session looks like a fresh-eyes bot;
    a session that already has CF cookies looks like a continued human
    browsing session. The discover crawler uses this — one warm client
    threads through all 14 seeds.

  * Browser-honest headers — Accept / Accept-Language / Accept-Encoding /
    sec-fetch-* are all set by the impersonation profile, but we also
    layer an explicit Accept-Language header to be safe.
"""
from __future__ import annotations
import random
import time
from typing import Any
from curl_cffi import requests as cc_requests

# Rotation order matters: most-likely-to-pass first so successful sessions
# stick. List spans recent Chrome / Safari / Edge / Firefox so we look
# multifaceted to any TLS fingerprint clustering CF does.
#
# curl_cffi supports many more profiles (chrome99..chrome138, chrome_android,
# safari15_5..safari18_2, firefox133/135, edge99/101); 8 is enough variety
# without diluting the "most browsers run recent Chrome" prior.
IMPERSONATE_ROTATION = [
    "chrome131",   # most common — try first
    "safari17_0",
    "chrome120",
    "edge101",
    "chrome133",
    "safari18_0",
    "firefox135",
    "chrome_android",
]

DEFAULT_COOKIES = {"currency": "USD"}

# Headers we layer on top of whatever the impersonation profile sets.
# Lowering the risk of CF flagging "browser TLS but missing Accept-Language".
BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def make_client(*, timeout: float = 30.0, impersonate: str = "chrome131") -> "cc_requests.Session":
    return cc_requests.Session(
        impersonate=impersonate,
        timeout=timeout,
    )


def warm_client(*, impersonate: str = "chrome131", verbose: bool = False) -> "cc_requests.Session":
    """Create a Session and pre-visit the KS homepage so we acquire CF
    clearance + session cookies BEFORE making any data requests.

    A cold session = "first time visitor with no history" → CF often
    challenges. A warm session = "user who's been browsing" → CF lets
    nearly everything through.

    Returns the session ready to reuse for many requests. Doesn't raise
    if the warm-up itself fails — we still return a session, just an
    un-warmed one. Callers can recover via the impersonation rotation
    in fetch() or via Playwright fallback.
    """
    c = cc_requests.Session(impersonate=impersonate, timeout=30.0)
    for k, v in DEFAULT_COOKIES.items():
        c.cookies.set(k, v)
    try:
        r = c.get(
            "https://www.kickstarter.com/",
            headers=BROWSER_HEADERS,
        )
        if verbose:
            print(f"  warm_client: KS homepage status={r.status_code}, {len(c.cookies)} cookies")
    except Exception as e:
        if verbose:
            print(f"  warm_client: homepage GET raised ({e}); proceeding cold")
    return c


def fetch(
    url: str,
    *,
    client: "cc_requests.Session | None" = None,
    max_attempts: int = 4,
    headers: "dict | None" = None,
    **kwargs,
) -> "cc_requests.Response":
    """Fetch a URL with TLS impersonation and Cloudflare-aware retry.

    Cloudflare 403 challenges are probabilistic — retry with a different
    impersonation profile + jittered backoff. Raises RuntimeError on
    terminal failure (caller can fall back to Playwright).

    If `client` is passed, reuse it across all attempts (cookies persist —
    important for keeping CF "this is a continued session" state). The
    impersonation rotation is applied per-request via the per-request
    `impersonate=` kwarg, so the same Session object can switch TLS
    fingerprints between attempts.
    """
    merged_headers = dict(BROWSER_HEADERS)
    if headers:
        merged_headers.update(headers)

    last_status: int | None = None
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        impersonate = IMPERSONATE_ROTATION[attempt % len(IMPERSONATE_ROTATION)]
        # If caller passed a client, reuse it (cookies persist). Otherwise
        # make a fresh one per attempt — but that loses the cookies between
        # attempts. Always prefer passing a warm_client() for crawl loops.
        c = client or cc_requests.Session(impersonate=impersonate, timeout=30.0)
        try:
            r = c.get(
                url,
                cookies=DEFAULT_COOKIES,
                impersonate=impersonate,
                headers=merged_headers,
                **kwargs,
            )
        except Exception as e:  # connection reset, timeout, etc.
            last_err = e
            time.sleep(1.0 + attempt + random.random())
            continue
        last_status = r.status_code
        if r.status_code == 200:
            return r
        # Exponential-ish backoff on 403 / 429 / 5xx
        time.sleep(2.0 + attempt * 1.5 + random.random() * 1.5)
    msg = f"failed after {max_attempts} attempts, last_status={last_status}"
    if last_err:
        msg += f", last_err={last_err}"
    raise RuntimeError(msg)


class RateLimiter:
    """Per-second pacer — be a polite scraper.

    Adds small random jitter (±20%) so we don't look like a metronome
    to any rate-detection layer. The base interval is 1/qps.
    """

    def __init__(self, qps: float = 1.0, *, jitter: float = 0.2):
        self.min_interval = 1.0 / qps
        self._jitter = max(0.0, min(1.0, jitter))
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delta = now - self._last
        # Apply ±jitter% to the next interval
        interval = self.min_interval * (1.0 + (random.random() * 2 - 1) * self._jitter)
        if delta < interval:
            time.sleep(interval - delta)
        self._last = time.monotonic()
