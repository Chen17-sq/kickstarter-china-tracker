"""HTTP client — Cloudflare-bypassing TLS impersonation via curl_cffi.

Plain httpx returns a 403 "Just a moment..." Cloudflare challenge from KS.
curl_cffi matches a real browser's TLS+HTTP/2 fingerprint and gets through.
The challenge still fires probabilistically (~30% of requests), so
fetch_with_retry() rotates the impersonation profile + backs off on 403.
"""
from __future__ import annotations
import random
import time
from typing import Any
from curl_cffi import requests as cc_requests

IMPERSONATE_ROTATION = ["safari17_0", "chrome131", "chrome120", "edge101"]

DEFAULT_COOKIES = {"currency": "USD"}


def make_client(*, timeout: float = 30.0, impersonate: str = "chrome131"):
    return cc_requests.Session(
        impersonate=impersonate,
        timeout=timeout,
    )


def fetch(url: str, *, client=None, max_attempts: int = 4, **kwargs) -> cc_requests.Response:
    """Fetch a URL with TLS impersonation and Cloudflare-aware retry.

    Cloudflare 403 challenges are probabilistic — retry with a different
    impersonation profile + jittered backoff. Raises on terminal failure.
    """
    last_status: int | None = None
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        impersonate = IMPERSONATE_ROTATION[attempt % len(IMPERSONATE_ROTATION)]
        c = client or cc_requests.Session(impersonate=impersonate, timeout=30.0)
        # If we were given an existing client, override its impersonation per-attempt.
        # curl_cffi Session lets us pass impersonate per-request as kwarg too.
        try:
            r = c.get(url, cookies=DEFAULT_COOKIES, impersonate=impersonate, **kwargs)
        except Exception as e:  # connection reset, timeout, etc.
            last_err = e
            time.sleep(1.0 + attempt + random.random())
            continue
        last_status = r.status_code
        if r.status_code == 200:
            return r
        # Backoff on 403 / 429 / 5xx
        time.sleep(2.0 + attempt + random.random() * 1.5)
    msg = f"failed after {max_attempts} attempts, last_status={last_status}"
    if last_err:
        msg += f", last_err={last_err}"
    raise RuntimeError(msg)


class RateLimiter:
    """Per-second pacer — be a polite scraper."""

    def __init__(self, qps: float = 1.0):
        self.min_interval = 1.0 / qps
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delta = now - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()
