"""Tests for post_resend() 429 handling — covers Resend's 5 req/s limit."""
from __future__ import annotations

from scraper import email_notify


class _FakeResp:
    def __init__(self, status_code: int, text: str = "", headers: dict | None = None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self):
        import httpx
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=None,  # type: ignore[arg-type]
                response=None,  # type: ignore[arg-type]
            )


def test_post_resend_retries_on_429(monkeypatch):
    """First 429 → retry → success on 2nd attempt."""
    calls = []

    def fake_post(url, **kw):
        calls.append(1)
        if len(calls) == 1:
            return _FakeResp(429, text="rate_limit_exceeded", headers={"retry-after": "0.5"})
        return _FakeResp(200, text="ok")

    monkeypatch.setattr(email_notify.httpx, "post", fake_post)
    monkeypatch.setattr(email_notify.time, "sleep", lambda s: None)  # no real sleep
    email_notify.post_resend("k", "from@x", ["to@x"], "s", "<p>h</p>")
    assert len(calls) == 2


def test_post_resend_gives_up_after_max_retries(monkeypatch):
    """3 consecutive 429s → final raises HTTPStatusError."""
    calls = []

    def fake_post(url, **kw):
        calls.append(1)
        return _FakeResp(429, text="rate_limit_exceeded")

    monkeypatch.setattr(email_notify.httpx, "post", fake_post)
    monkeypatch.setattr(email_notify.time, "sleep", lambda s: None)
    import httpx
    try:
        email_notify.post_resend("k", "from@x", ["to@x"], "s", "<p>h</p>", max_retries=3)
        raise AssertionError("Expected raise after max_retries")
    except httpx.HTTPStatusError:
        pass
    assert len(calls) == 3  # tried max_retries times


def test_post_resend_succeeds_first_try_when_no_429(monkeypatch):
    calls = []

    def fake_post(url, **kw):
        calls.append(1)
        return _FakeResp(200, text="ok")

    monkeypatch.setattr(email_notify.httpx, "post", fake_post)
    monkeypatch.setattr(email_notify.time, "sleep", lambda s: None)
    email_notify.post_resend("k", "from@x", ["to@x"], "s", "<p>h</p>")
    assert len(calls) == 1  # no retry needed


def test_post_resend_non_429_4xx_raises_immediately(monkeypatch):
    """422/400 errors are NOT retried — they're structural, not transient."""
    calls = []

    def fake_post(url, **kw):
        calls.append(1)
        return _FakeResp(422, text="invalid")

    monkeypatch.setattr(email_notify.httpx, "post", fake_post)
    monkeypatch.setattr(email_notify.time, "sleep", lambda s: None)
    import httpx
    try:
        email_notify.post_resend("k", "from@x", ["to@x"], "s", "<p>h</p>")
        raise AssertionError("Expected raise on 422")
    except httpx.HTTPStatusError:
        pass
    assert len(calls) == 1  # no retry on non-429


def test_post_resend_respects_retry_after_header(monkeypatch):
    """Server-provided Retry-After overrides exponential backoff."""
    sleeps = []
    monkeypatch.setattr(email_notify.time, "sleep", lambda s: sleeps.append(s))

    calls = []

    def fake_post(url, **kw):
        calls.append(1)
        if len(calls) == 1:
            return _FakeResp(429, headers={"retry-after": "3"})
        return _FakeResp(200, text="ok")

    monkeypatch.setattr(email_notify.httpx, "post", fake_post)
    email_notify.post_resend("k", "from@x", ["to@x"], "s", "<p>h</p>")
    assert 3.0 in sleeps


def test_post_resend_caps_retry_after_at_10s(monkeypatch):
    """A pathological Retry-After of 600s gets clamped to 10s."""
    sleeps = []
    monkeypatch.setattr(email_notify.time, "sleep", lambda s: sleeps.append(s))

    calls = []

    def fake_post(url, **kw):
        calls.append(1)
        if len(calls) == 1:
            return _FakeResp(429, headers={"retry-after": "600"})
        return _FakeResp(200, text="ok")

    monkeypatch.setattr(email_notify.httpx, "post", fake_post)
    email_notify.post_resend("k", "from@x", ["to@x"], "s", "<p>h</p>")
    assert max(sleeps) <= 10.0


def test_post_resend_handles_garbage_retry_after(monkeypatch):
    """Non-numeric Retry-After falls back to exponential backoff."""
    sleeps = []
    monkeypatch.setattr(email_notify.time, "sleep", lambda s: sleeps.append(s))

    calls = []

    def fake_post(url, **kw):
        calls.append(1)
        if len(calls) == 1:
            return _FakeResp(429, headers={"retry-after": "wat"})
        return _FakeResp(200, text="ok")

    monkeypatch.setattr(email_notify.httpx, "post", fake_post)
    email_notify.post_resend("k", "from@x", ["to@x"], "s", "<p>h</p>")
    # Falls back to 2.0 ** 0 == 1.0
    assert 1.0 in sleeps
