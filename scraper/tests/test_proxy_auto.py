"""Tests for proxy_auto.py — free public proxy discovery + caching."""
from __future__ import annotations

import datetime as dt
import json

from scraper import proxy_auto


def test_load_cache_returns_empty_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(proxy_auto, "CACHE_FILE", tmp_path / "pc.json")
    assert proxy_auto._load_cache() == []


def test_save_then_load_roundtrip(monkeypatch, tmp_path):
    fake = tmp_path / "pc.json"
    monkeypatch.setattr(proxy_auto, "CACHE_FILE", fake)
    proxy_auto._save_cache(["http://1.1.1.1:80", "http://2.2.2.2:8080"])
    assert proxy_auto._load_cache() == ["http://1.1.1.1:80", "http://2.2.2.2:8080"]


def test_load_cache_rejects_stale(monkeypatch, tmp_path):
    """Entries older than CACHE_TTL_HOURS are dropped."""
    fake = tmp_path / "pc.json"
    monkeypatch.setattr(proxy_auto, "CACHE_FILE", fake)
    stale = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=48)).isoformat()
    fake.write_text(json.dumps({
        "updated_at": stale,
        "proxies": ["http://9.9.9.9:80"],
    }))
    assert proxy_auto._load_cache() == []


def test_load_cache_handles_corrupt_json(monkeypatch, tmp_path):
    fake = tmp_path / "pc.json"
    monkeypatch.setattr(proxy_auto, "CACHE_FILE", fake)
    fake.write_text("not json {{{")
    assert proxy_auto._load_cache() == []


def test_fetch_candidates_filters_garbage(monkeypatch):
    """Only IPv4:PORT lines survive parsing."""
    class FakeResp:
        status_code = 200
        text = (
            "1.2.3.4:8080\n"
            "not-a-proxy\n"
            "5.6.7.8:9090\n"
            "::1:8080\n"               # IPv6, rejected
            "10.0.0.1:notaport\n"      # non-numeric port
            "11.22.33.44:1\n"
        )

    def fake_get(*a, **kw):
        return FakeResp()

    monkeypatch.setattr("curl_cffi.requests.get", fake_get)
    out = proxy_auto.fetch_candidates()
    assert "http://1.2.3.4:8080" in out
    assert "http://5.6.7.8:9090" in out
    assert "http://11.22.33.44:1" in out
    assert all("not-a-proxy" not in p for p in out)
    assert all("notaport" not in p for p in out)


def test_fetch_candidates_returns_empty_on_non_200(monkeypatch):
    class FakeResp:
        status_code = 503
        text = ""

    monkeypatch.setattr("curl_cffi.requests.get", lambda *a, **kw: FakeResp())
    assert proxy_auto.fetch_candidates() == []


def test_fetch_candidates_returns_empty_on_exception(monkeypatch):
    def boom(*a, **kw):
        raise OSError("network down")

    monkeypatch.setattr("curl_cffi.requests.get", boom)
    assert proxy_auto.fetch_candidates() == []


def test_discover_uses_cache_first(monkeypatch, tmp_path):
    """If cache has a working proxy, skip fetching fresh candidates."""
    fake = tmp_path / "pc.json"
    monkeypatch.setattr(proxy_auto, "CACHE_FILE", fake)
    fake.write_text(json.dumps({
        "updated_at": dt.datetime.now(dt.UTC).isoformat(),
        "proxies": ["http://cached:1"],
    }))
    monkeypatch.setattr(proxy_auto, "validate_proxy", lambda p: p == "http://cached:1")
    # If fetch_candidates were called it would explode — proving cache short-circuits
    monkeypatch.setattr(proxy_auto, "fetch_candidates", lambda: 1 / 0)
    assert proxy_auto.discover() == "http://cached:1"


def test_discover_validates_fresh_candidates(monkeypatch, tmp_path):
    """Cache miss → fetch fresh, validate, return first working."""
    fake = tmp_path / "pc.json"
    monkeypatch.setattr(proxy_auto, "CACHE_FILE", fake)
    monkeypatch.setattr(
        proxy_auto, "fetch_candidates",
        lambda: ["http://a:1", "http://b:2", "http://c:3"],
    )
    # Only b works
    monkeypatch.setattr(proxy_auto, "validate_proxy", lambda p: p == "http://b:2")
    # Disable shuffle for deterministic test
    monkeypatch.setattr(proxy_auto.random, "shuffle", lambda lst: None)
    result = proxy_auto.discover(max_test=10)
    assert result == "http://b:2"
    # Saved to cache
    assert fake.exists()
    cached = json.loads(fake.read_text())
    assert "http://b:2" in cached["proxies"]


def test_discover_returns_none_when_nothing_works(monkeypatch, tmp_path):
    fake = tmp_path / "pc.json"
    monkeypatch.setattr(proxy_auto, "CACHE_FILE", fake)
    monkeypatch.setattr(proxy_auto, "fetch_candidates", lambda: ["http://x:1", "http://y:2"])
    monkeypatch.setattr(proxy_auto, "validate_proxy", lambda p: False)
    assert proxy_auto.discover(max_test=10) is None


def test_discover_returns_none_when_no_candidates(monkeypatch, tmp_path):
    fake = tmp_path / "pc.json"
    monkeypatch.setattr(proxy_auto, "CACHE_FILE", fake)
    monkeypatch.setattr(proxy_auto, "fetch_candidates", lambda: [])
    assert proxy_auto.discover() is None


def test_discover_falls_through_when_cache_proxies_all_dead(monkeypatch, tmp_path):
    """Cache entries fail validation → discover fetches fresh list."""
    fake = tmp_path / "pc.json"
    monkeypatch.setattr(proxy_auto, "CACHE_FILE", fake)
    fake.write_text(json.dumps({
        "updated_at": dt.datetime.now(dt.UTC).isoformat(),
        "proxies": ["http://dead:1", "http://dead:2"],
    }))
    monkeypatch.setattr(
        proxy_auto, "fetch_candidates",
        lambda: ["http://live:99"],
    )
    monkeypatch.setattr(
        proxy_auto, "validate_proxy",
        lambda p: p == "http://live:99",
    )
    monkeypatch.setattr(proxy_auto.random, "shuffle", lambda lst: None)
    assert proxy_auto.discover(max_test=10) == "http://live:99"
