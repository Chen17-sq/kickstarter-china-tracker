"""Tests for session_state.py — cross-run cookie / warmth persistence."""
from __future__ import annotations

import datetime as dt
import json

from scraper import session_state


def test_load_returns_empty_when_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(session_state, "STATE_FILE", tmp_path / "nonexistent.json")
    assert session_state.load() == {}


def test_load_returns_empty_when_bad_json(monkeypatch, tmp_path):
    fake = tmp_path / "state.json"
    fake.write_text("{not json}")
    monkeypatch.setattr(session_state, "STATE_FILE", fake)
    assert session_state.load() == {}


def test_load_returns_state_when_fresh(monkeypatch, tmp_path):
    fake = tmp_path / "state.json"
    state = {
        "cookies": {"cf_clearance": "abc123"},
        "ua": "Mozilla/5.0",
        "last_seen": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    fake.write_text(json.dumps(state))
    monkeypatch.setattr(session_state, "STATE_FILE", fake)
    out = session_state.load()
    assert out["cookies"]["cf_clearance"] == "abc123"


def test_load_returns_empty_when_stale(monkeypatch, tmp_path):
    """Cookies older than STALE_AFTER_HOURS should be thrown away."""
    fake = tmp_path / "state.json"
    old_ts = dt.datetime.now(dt.UTC) - dt.timedelta(hours=48)
    state = {
        "cookies": {"cf_clearance": "stale"},
        "last_seen": old_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    fake.write_text(json.dumps(state))
    monkeypatch.setattr(session_state, "STATE_FILE", fake)
    assert session_state.load() == {}


def test_update_cookies_from_dict(monkeypatch, tmp_path):
    fake = tmp_path / "state.json"
    monkeypatch.setattr(session_state, "STATE_FILE", fake)
    session_state.update_cookies({
        "cf_clearance": "fresh",
        "_kickstarter_session": "sid",
        "unrelated_cookie": "ignore-me",  # not in PRESERVE_COOKIE_NAMES
    })
    cookies = session_state.get_cookies()
    assert cookies["cf_clearance"] == "fresh"
    assert cookies["_kickstarter_session"] == "sid"
    assert "unrelated_cookie" not in cookies


def test_set_and_get_ua(monkeypatch, tmp_path):
    fake = tmp_path / "state.json"
    monkeypatch.setattr(session_state, "STATE_FILE", fake)
    session_state.set_ua("Mozilla/5.0 (Macintosh) Chrome/131")
    assert session_state.get_ua() == "Mozilla/5.0 (Macintosh) Chrome/131"


def test_is_warm_returns_false_when_never_warmed(monkeypatch, tmp_path):
    fake = tmp_path / "state.json"
    monkeypatch.setattr(session_state, "STATE_FILE", fake)
    assert session_state.is_warm() is False


def test_is_warm_returns_true_after_recent_mark(monkeypatch, tmp_path):
    fake = tmp_path / "state.json"
    monkeypatch.setattr(session_state, "STATE_FILE", fake)
    session_state.mark_warmed()
    assert session_state.is_warm(within_hours=1) is True


def test_is_warm_returns_false_when_old(monkeypatch, tmp_path):
    fake = tmp_path / "state.json"
    old_ts = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=10)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    fake.write_text(json.dumps({"warmed_at": old_ts}))
    monkeypatch.setattr(session_state, "STATE_FILE", fake)
    assert session_state.is_warm(within_hours=6) is False


def test_update_cookies_preserves_existing(monkeypatch, tmp_path):
    """Successive updates should accumulate, not overwrite."""
    fake = tmp_path / "state.json"
    monkeypatch.setattr(session_state, "STATE_FILE", fake)
    session_state.update_cookies({"cf_clearance": "first"})
    session_state.update_cookies({"_kickstarter_session": "second"})
    cookies = session_state.get_cookies()
    assert cookies["cf_clearance"] == "first"
    assert cookies["_kickstarter_session"] == "second"
