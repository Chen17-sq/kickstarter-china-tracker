"""Tests for api.py — public JSON API output stability + field whitelist.

The whole point of having a separate API surface is that the schema is
STABLE. These tests pin down what external consumers can rely on. If you
break one of them, you're breaking someone's bot/dashboard — bump
SCHEMA_VERSION in api.py and document the change.
"""
from __future__ import annotations

import json

from scraper.api import (
    PUBLIC_PROJECT_FIELDS,
    SCHEMA_VERSION,
    _slim_project,
    build_payload,
    write_api,
)


def _curr(projects=None, generated_at="2026-05-16T02:00:00Z"):
    return {
        "generated_at": generated_at,
        "projects": projects or [],
    }


def _full_project(**kw):
    """A project with all whitelisted fields PLUS internal fields that must
    be dropped from the public output."""
    base = {
        # whitelisted ↓
        "pathname": "/projects/x/widget",
        "title": "Widget",
        "blurb_zh": "小工具",
        "status": "live",
        "url": "https://www.kickstarter.com/projects/x/widget",
        "country": "CN",
        "creator": "X",
        "followers": 1000,
        "backers": 500,
        "pledged_usd": 50000.0,
        "goal_usd": 30000.0,
        "percent_funded": 166,
        "deadline": "2026-06-01T12:00:00Z",
        "launched_at": "2026-04-15T12:00:00Z",
        "project_we_love": True,
        "china_confidence": "高",
        "delta_followers": 12,
        "delta_backers": 4,
        "delta_pledged_usd": 1200.0,
        # internal ↓ (must NOT appear in API output)
        "photo": "https://...",
        "blurb": "English blurb",
        "matched_brand": "Widget Inc",
        "matched_brand_zh": "小工具厂",
        "_internal_field": "secret",
    }
    base.update(kw)
    return base


# ── _slim_project field whitelist ─────────────────────────────────

def test_slim_project_drops_internal_fields():
    """Only PUBLIC_PROJECT_FIELDS keys survive."""
    p = _full_project()
    slim = _slim_project(p)
    for k in ["photo", "blurb", "matched_brand", "matched_brand_zh", "_internal_field"]:
        assert k not in slim, f"internal field {k} leaked into API output"


def test_slim_project_keeps_all_present_whitelisted_fields():
    """Every whitelisted field that exists on the input must survive.
    Whitelisted fields that ARE NOT on input are simply absent — that's
    correct (e.g., _sleeper_reason is only present on sleeper picks).
    """
    p = _full_project()
    slim = _slim_project(p)
    for k in PUBLIC_PROJECT_FIELDS:
        if k in p:
            assert k in slim, f"public field {k} present on input but dropped from API output"


def test_slim_project_keeps_sleeper_annotations_when_present():
    """Sleeper-only fields survive when present."""
    p = _full_project(_sleeper_reason="AI 硬件 · 连续 2 天上榜", _sleeper_score=170)
    slim = _slim_project(p)
    assert slim["_sleeper_reason"] == "AI 硬件 · 连续 2 天上榜"
    assert slim["_sleeper_score"] == 170


def test_slim_project_missing_input_field_is_simply_absent():
    """If a project doesn't have a whitelisted field, it just doesn't show up.
    We don't synthesize None placeholders."""
    p = {"pathname": "/x", "title": "Y"}  # only 2 fields
    slim = _slim_project(p)
    assert slim == {"pathname": "/x", "title": "Y"}


# ── build_payload top-level shape ─────────────────────────────────

def test_payload_has_schema_version():
    payload = build_payload(_curr())
    assert payload["schema_version"] == SCHEMA_VERSION


def test_payload_includes_edition_number():
    payload = build_payload(_curr([_full_project()]))
    assert "edition" in payload
    assert isinstance(payload["edition"], int)
    assert payload["edition"] > 0


def test_payload_counts_status_buckets():
    projects = [
        _full_project(pathname="/a", status="live"),
        _full_project(pathname="/b", status="live"),
        _full_project(pathname="/c", status="prelaunch"),
        _full_project(pathname="/d", status="successful"),
    ]
    payload = build_payload(_curr(projects))
    assert payload["counts"]["live"] == 2
    assert payload["counts"]["prelaunch"] == 1
    assert payload["counts"]["successful"] == 1
    assert payload["counts"]["failed"] == 0
    assert payload["counts"]["total"] == 4


def test_payload_counts_pwl():
    projects = [
        _full_project(pathname="/a", project_we_love=True),
        _full_project(pathname="/b", project_we_love=False),
        _full_project(pathname="/c", project_we_love=True),
    ]
    payload = build_payload(_curr(projects))
    assert payload["counts"]["pwl"] == 2


def test_payload_sums_live_usd_only():
    """total_live_usd is the sum of pledged_usd over LIVE projects only."""
    projects = [
        _full_project(pathname="/a", status="live", pledged_usd=10000.0),
        _full_project(pathname="/b", status="live", pledged_usd=20000.0),
        _full_project(pathname="/c", status="successful", pledged_usd=99999.0),  # excluded
        _full_project(pathname="/d", status="prelaunch", pledged_usd=12345.0),    # excluded
    ]
    payload = build_payload(_curr(projects))
    assert payload["total_live_usd"] == 30000.0


def test_payload_handles_bad_pledged_usd_types():
    """Non-numeric pledged_usd should be silently treated as 0, not crash."""
    projects = [
        _full_project(pathname="/a", status="live", pledged_usd="garbage"),
        _full_project(pathname="/b", status="live", pledged_usd=None),
        _full_project(pathname="/c", status="live", pledged_usd=5000.0),
    ]
    payload = build_payload(_curr(projects))
    assert payload["total_live_usd"] == 5000.0


def test_payload_preserves_generated_at():
    payload = build_payload(_curr(generated_at="2026-05-15T02:00:00Z"))
    assert payload["generated_at"] == "2026-05-15T02:00:00Z"


def test_payload_synthesizes_generated_at_when_missing():
    """If curr lacks generated_at, we still set one — never emit None."""
    payload = build_payload({"projects": []})
    assert payload["generated_at"] is not None
    # ISO-like timestamp
    assert "T" in payload["generated_at"]


def test_payload_projects_are_slimmed():
    """Each project in the output goes through _slim_project."""
    payload = build_payload(_curr([_full_project()]))
    p = payload["projects"][0]
    assert "photo" not in p
    assert "blurb" not in p
    assert "title" in p


# ── write_api round-trip ──────────────────────────────────────────

def test_write_api_creates_today_index_dated_and_sleepers(monkeypatch, tmp_path):
    """write_api should produce 4 files: today.json, <date>.json, sleepers.json, index.json."""
    api_mod = __import__("scraper.api", fromlist=["api"])
    monkeypatch.setattr(api_mod, "API_DIR", tmp_path / "api")
    paths = write_api(_curr([_full_project()]))
    names = sorted(p.name for p in paths)
    assert "today.json" in names
    assert "index.json" in names
    assert "sleepers.json" in names
    # The remaining one is the dated file — verify it ends in .json
    other = [n for n in names if n not in ("today.json", "index.json", "sleepers.json")]
    assert len(other) == 1
    assert other[0].endswith(".json")


def test_write_api_today_and_dated_have_identical_content(monkeypatch, tmp_path):
    api_mod = __import__("scraper.api", fromlist=["api"])
    monkeypatch.setattr(api_mod, "API_DIR", tmp_path / "api")
    write_api(_curr([_full_project()]))
    today = (tmp_path / "api" / "today.json").read_text(encoding="utf-8")
    # Exclude the meta files; only the dated <YYYY-MM-DD>.json should match today.json
    others = [
        f for f in (tmp_path / "api").iterdir()
        if f.name not in ("today.json", "index.json", "sleepers.json")
    ]
    assert len(others) == 1
    dated = others[0].read_text(encoding="utf-8")
    assert today == dated


def test_write_api_sleepers_endpoint_is_well_formed(monkeypatch, tmp_path):
    """sleepers.json has schema_version, count, projects array."""
    api_mod = __import__("scraper.api", fromlist=["api"])
    monkeypatch.setattr(api_mod, "API_DIR", tmp_path / "api")
    write_api(_curr([_full_project()]))
    s = json.loads((tmp_path / "api" / "sleepers.json").read_text(encoding="utf-8"))
    assert "schema_version" in s
    assert "count" in s
    assert "projects" in s
    assert isinstance(s["projects"], list)
    assert s["count"] == len(s["projects"])


def test_write_api_index_lists_available_dates(monkeypatch, tmp_path):
    api_mod = __import__("scraper.api", fromlist=["api"])
    monkeypatch.setattr(api_mod, "API_DIR", tmp_path / "api")
    write_api(_curr([_full_project()]))
    index = json.loads((tmp_path / "api" / "index.json").read_text(encoding="utf-8"))
    assert "latest" in index
    assert "dates" in index
    assert isinstance(index["dates"], list)
    assert index["latest"] in index["dates"]
    assert index["schema_version"] == SCHEMA_VERSION


# ── Schema stability commitment ────────────────────────────────────

def test_public_fields_list_includes_essentials():
    """If someone removes one of these from PUBLIC_PROJECT_FIELDS, we break
    every external consumer. Pin them here so the breakage shows up loudly
    in CI before going live."""
    essentials = {
        "pathname", "title", "status", "url",
        "followers", "backers", "pledged_usd", "goal_usd",
        "deadline", "project_we_love", "china_confidence",
    }
    missing = essentials - set(PUBLIC_PROJECT_FIELDS)
    assert not missing, f"essential public fields removed: {missing}"


def test_schema_version_is_versioned_int():
    assert isinstance(SCHEMA_VERSION, int)
    assert SCHEMA_VERSION >= 1
