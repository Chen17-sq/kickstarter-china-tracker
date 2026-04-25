"""HTTP session helpers — polite scraping, USD currency forced, sane User-Agent."""
from __future__ import annotations
import time
import httpx

DEFAULT_HEADERS = {
    "User-Agent": (
        "kickstarter-china-tracker/0.1 "
        "(+https://github.com/YOUR_HANDLE/kickstarter-china-tracker)"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Force USD pricing across the site (KS picks currency by IP otherwise)
DEFAULT_COOKIES = {"currency": "USD"}


def make_client(*, timeout: float = 20.0) -> httpx.Client:
    return httpx.Client(
        headers=DEFAULT_HEADERS,
        cookies=DEFAULT_COOKIES,
        timeout=timeout,
        follow_redirects=True,
        http2=True,
    )


class RateLimiter:
    """Simple per-second pacer — be a good citizen."""

    def __init__(self, qps: float = 1.0):
        self.min_interval = 1.0 / qps
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delta = now - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()
