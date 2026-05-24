"""Jittered exponential backoff with per-endpoint budget.

Today's (2026-05-24) failure mode: the 4-attempt impersonation rotation
fires all 4 attempts within 30 seconds. That tight burst is itself a
detection signal — once CF starts blocking, hammering it with rotated
TLS fingerprints just escalates the block, doesn't escape it.

This module gives every endpoint a *retry budget* (max attempts) and
forces jittered exponential delays between attempts. When the budget
is exhausted, the caller falls back to the next defense layer
(Playwright → nodriver → proxy → alternative source).

Use:
    bo = Backoff(name="discover_seed_china", max_attempts=4, base_seconds=2)
    while bo.can_retry():
        status, resp = try_fetch()
        if status == 200:
            break
        if status in (403, 429, 503):
            bo.sleep_and_retry()
            continue
        break
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass


@dataclass
class Backoff:
    """One backoff state per logical operation.

    Recommended params for KS:
      seed fetch (discover):  max_attempts=3, base=3.0 → 3s/6s/12s spread
      graphql chunk:          max_attempts=2, base=1.5 → 1.5s/3s spread
      retry budget for whole run is implicit (chunks * max_attempts)
    """
    name: str
    max_attempts: int = 3
    base_seconds: float = 2.0
    jitter_ratio: float = 0.35  # ±35% randomness around the computed delay
    cap_seconds: float = 60.0   # never sleep more than this
    verbose: bool = True

    _attempt: int = 0

    def can_retry(self) -> bool:
        return self._attempt < self.max_attempts

    def sleep_and_retry(self) -> float:
        """Sleep for the next backoff interval, then increment attempt.
        Returns the actual seconds slept (for logging)."""
        if self._attempt >= self.max_attempts:
            return 0.0
        # Exponential: 2^attempt × base, with jitter
        delay = self.base_seconds * (2 ** self._attempt)
        jitter = delay * self.jitter_ratio * (random.random() * 2 - 1)
        actual = min(self.cap_seconds, max(0.5, delay + jitter))
        if self.verbose:
            print(
                f"  ⏳ {self.name}: backoff {actual:.1f}s "
                f"(attempt {self._attempt + 1}/{self.max_attempts})"
            )
        time.sleep(actual)
        self._attempt += 1
        return actual

    def reset(self) -> None:
        self._attempt = 0

    @property
    def attempts_used(self) -> int:
        return self._attempt


def chunk_pause(min_s: float = 1.0, max_s: float = 4.0) -> float:
    """Random sleep between successive chunked requests inside one run.
    Fixed delays are themselves a fingerprint — KS sees "exactly 1.0s
    between every chunk" and flags it. Random uniform between min/max
    seconds is the standard human-traffic spec. Returns seconds slept.
    """
    delay = random.uniform(min_s, max_s)
    time.sleep(delay)
    return delay


def warmup_pause(min_s: float = 3.0, max_s: float = 8.0) -> float:
    """Pause after a warmup GET, before the actual data request.
    A real human takes a few seconds to find the link they want and
    click. 3-8s is the common envelope. Returns seconds slept.
    """
    delay = random.uniform(min_s, max_s)
    time.sleep(delay)
    return delay
