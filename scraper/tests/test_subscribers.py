"""Tests for subscribers.py — load fallback, emails extraction, CLI args.

We don't test the Worker round-trip path here (no HTTP). The focus is the
fallback / local-file path that runs when OWNER_TOKEN is unset, plus the
helper accessors. These are the bits most likely to silently break under
refactor.
"""
from __future__ import annotations

import json

from scraper import subscribers as subs_mod


def _write_local(tmp_path, payload):
    """Write a fake legacy subscribers.json + point the module at it."""
    p = tmp_path / "subscribers.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_local_load_returns_empty_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(subs_mod, "LEGACY_LOCAL", tmp_path / "nonexistent.json")
    out = subs_mod._local_load()
    assert out["subscribers"] == []
    assert out["count"] == 0


def test_local_load_reads_valid_file(monkeypatch, tmp_path):
    path = _write_local(tmp_path, {
        "count": 2,
        "subscribers": [
            {"email": "a@e.com", "nickname": "A"},
            {"email": "b@e.com", "nickname": "B"},
        ],
    })
    monkeypatch.setattr(subs_mod, "LEGACY_LOCAL", path)
    out = subs_mod._local_load()
    assert len(out["subscribers"]) == 2
    assert out["subscribers"][0]["email"] == "a@e.com"


def test_local_load_recovers_from_bad_json(monkeypatch, tmp_path, capsys):
    """A corrupted local file should return empty, not crash."""
    path = tmp_path / "subscribers.json"
    path.write_text("{not json}", encoding="utf-8")
    monkeypatch.setattr(subs_mod, "LEGACY_LOCAL", path)
    out = subs_mod._local_load()
    assert out["subscribers"] == []


def test_load_falls_back_to_local_when_token_unset(monkeypatch, tmp_path):
    """Without OWNER_TOKEN, load() must use the local file fallback path."""
    monkeypatch.delenv("OWNER_TOKEN", raising=False)
    path = _write_local(tmp_path, {
        "subscribers": [{"email": "fallback@e.com"}],
    })
    monkeypatch.setattr(subs_mod, "LEGACY_LOCAL", path)
    out = subs_mod.load()
    assert out["subscribers"][0]["email"] == "fallback@e.com"


def test_emails_extracts_email_strings(monkeypatch, tmp_path):
    monkeypatch.delenv("OWNER_TOKEN", raising=False)
    path = _write_local(tmp_path, {
        "subscribers": [
            {"email": "a@e.com"},
            {"email": "b@e.com"},
            {"email": ""},          # empty — filtered
            {"nickname": "c"},      # missing email — filtered
        ],
    })
    monkeypatch.setattr(subs_mod, "LEGACY_LOCAL", path)
    out = subs_mod.emails()
    assert out == ["a@e.com", "b@e.com"]


def test_count_matches_emails_length(monkeypatch, tmp_path):
    monkeypatch.delenv("OWNER_TOKEN", raising=False)
    path = _write_local(tmp_path, {
        "subscribers": [{"email": f"x{i}@e.com"} for i in range(5)],
    })
    monkeypatch.setattr(subs_mod, "LEGACY_LOCAL", path)
    assert subs_mod.count() == 5


def test_all_subscribers_returns_full_records(monkeypatch, tmp_path):
    """all_subscribers() exposes type + creator_slug for email_notify's
    creator personalization path."""
    monkeypatch.delenv("OWNER_TOKEN", raising=False)
    path = _write_local(tmp_path, {
        "subscribers": [
            {"email": "creator@e.com", "type": "creator", "creator_slug": "foo"},
            {"email": "investor@e.com", "type": "investor"},
        ],
    })
    monkeypatch.setattr(subs_mod, "LEGACY_LOCAL", path)
    out = subs_mod.all_subscribers()
    assert len(out) == 2
    assert out[0]["type"] == "creator"
    assert out[0]["creator_slug"] == "foo"


def test_email_regex_matches_valid_and_rejects_bad():
    """Quick spot-check the EMAIL_RE pattern — must mirror Worker validation."""
    re_obj = subs_mod.EMAIL_RE
    valid = ["a@b.com", "a.b@c.io", "alice+x@example.co.uk", "FOO@bar.com"]
    invalid = ["no-at-sign", "@nodomain.com", "no@.com", "no@dot", "a@b.c", "spaces in@email.com"]
    for v in valid:
        assert re_obj.match(v), f"{v} should match"
    for v in invalid:
        assert not re_obj.match(v), f"{v} should NOT match"
