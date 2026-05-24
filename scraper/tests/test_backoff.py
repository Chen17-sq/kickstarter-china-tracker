"""Tests for backoff.py — jittered exponential backoff math + budget tracking."""
from __future__ import annotations

import time

import pytest

from scraper.backoff import Backoff, chunk_pause, warmup_pause


def test_can_retry_initially_true():
    bo = Backoff(name="t", max_attempts=3, verbose=False)
    assert bo.can_retry() is True


def test_can_retry_after_budget_exhausted(monkeypatch):
    """After max_attempts sleeps, can_retry returns False."""
    bo = Backoff(name="t", max_attempts=2, base_seconds=0.01, verbose=False)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    bo.sleep_and_retry()
    assert bo.can_retry() is True
    bo.sleep_and_retry()
    assert bo.can_retry() is False


def test_attempts_used_increments(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    bo = Backoff(name="t", max_attempts=5, base_seconds=0.01, verbose=False)
    assert bo.attempts_used == 0
    bo.sleep_and_retry()
    assert bo.attempts_used == 1
    bo.sleep_and_retry()
    assert bo.attempts_used == 2


def test_reset_zeros_attempts(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    bo = Backoff(name="t", max_attempts=3, base_seconds=0.01, verbose=False)
    bo.sleep_and_retry()
    bo.sleep_and_retry()
    assert bo.attempts_used == 2
    bo.reset()
    assert bo.attempts_used == 0
    assert bo.can_retry() is True


def test_exponential_growth(monkeypatch):
    """Each subsequent sleep should be roughly 2× the previous (modulo jitter)."""
    delays = []
    monkeypatch.setattr(time, "sleep", lambda s: delays.append(s))
    bo = Backoff(name="t", max_attempts=5, base_seconds=1.0,
                 jitter_ratio=0.0, verbose=False)
    bo.sleep_and_retry()  # attempt 0 → base * 1 = 1.0
    bo.sleep_and_retry()  # attempt 1 → base * 2 = 2.0
    bo.sleep_and_retry()  # attempt 2 → base * 4 = 4.0
    bo.sleep_and_retry()  # attempt 3 → base * 8 = 8.0
    assert delays == pytest.approx([1.0, 2.0, 4.0, 8.0], abs=0.01)


def test_cap_prevents_runaway_delay(monkeypatch):
    """High attempts shouldn't sleep more than cap_seconds."""
    delays = []
    monkeypatch.setattr(time, "sleep", lambda s: delays.append(s))
    bo = Backoff(name="t", max_attempts=10, base_seconds=1.0,
                 jitter_ratio=0.0, cap_seconds=10.0, verbose=False)
    for _ in range(10):
        bo.sleep_and_retry()
    # 1, 2, 4, 8, 16→10, 32→10, ... — all should be ≤10
    assert max(delays) <= 10.0


def test_jitter_creates_variance(monkeypatch):
    """jitter_ratio > 0 should produce non-deterministic delays."""
    delays = []
    monkeypatch.setattr(time, "sleep", lambda s: delays.append(s))
    bo = Backoff(name="t", max_attempts=20, base_seconds=10.0,
                 jitter_ratio=0.3, verbose=False)
    for _ in range(20):
        bo.sleep_and_retry()
        bo.reset()  # always exercise the first-attempt delay
    # With 30% jitter on a 10s base, we expect spread roughly 7-13s
    unique = {round(d, 1) for d in delays}
    assert len(unique) > 5, "jitter should produce many different values"


def test_sleep_and_retry_after_budget_returns_zero(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    bo = Backoff(name="t", max_attempts=1, base_seconds=0.01, verbose=False)
    bo.sleep_and_retry()
    # Already at budget — should return 0 (no-op)
    assert bo.sleep_and_retry() == 0.0


def test_chunk_pause_uniform_range(monkeypatch):
    """chunk_pause should sleep between min_s and max_s."""
    captured = []
    monkeypatch.setattr(time, "sleep", lambda s: captured.append(s))
    for _ in range(50):
        chunk_pause(1.0, 2.0)
    assert all(1.0 <= s <= 2.0 for s in captured)


def test_warmup_pause_uniform_range(monkeypatch):
    captured = []
    monkeypatch.setattr(time, "sleep", lambda s: captured.append(s))
    for _ in range(50):
        warmup_pause(3.0, 8.0)
    assert all(3.0 <= s <= 8.0 for s in captured)
