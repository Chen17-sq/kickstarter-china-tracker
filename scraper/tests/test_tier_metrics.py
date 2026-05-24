"""Tests for tier_metrics.py — rolling success rate + adaptive routing."""
from __future__ import annotations

import datetime as dt
import json

from scraper import tier_metrics


def test_record_writes_to_file(monkeypatch, tmp_path):
    fake = tmp_path / "tm.json"
    monkeypatch.setattr(tier_metrics, "METRICS_FILE", fake)
    tier_metrics.record("watches", "curl_cffi")
    assert fake.exists()
    data = json.loads(fake.read_text(encoding="utf-8"))
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    assert today in data["days"]
    assert data["days"][today]["watches"]["curl_cffi"] == 1


def test_record_accumulates(monkeypatch, tmp_path):
    """Multiple records for same path+tier+day → count goes up."""
    fake = tmp_path / "tm.json"
    monkeypatch.setattr(tier_metrics, "METRICS_FILE", fake)
    tier_metrics.record("watches", "curl_cffi")
    tier_metrics.record("watches", "curl_cffi")
    tier_metrics.record("watches", "playwright")
    data = json.loads(fake.read_text(encoding="utf-8"))
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    assert data["days"][today]["watches"]["curl_cffi"] == 2
    assert data["days"][today]["watches"]["playwright"] == 1


def test_record_handles_empty_tier(monkeypatch, tmp_path):
    """Empty tier defaults to 'failed' so we still record the attempt."""
    fake = tmp_path / "tm.json"
    monkeypatch.setattr(tier_metrics, "METRICS_FILE", fake)
    tier_metrics.record("watches", "")
    data = json.loads(fake.read_text(encoding="utf-8"))
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    assert data["days"][today]["watches"]["failed"] == 1


def test_rolling_stats_aggregates_across_days(monkeypatch, tmp_path):
    fake = tmp_path / "tm.json"
    monkeypatch.setattr(tier_metrics, "METRICS_FILE", fake)
    # Pre-seed with multi-day data
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    yesterday = (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    fake.write_text(json.dumps({
        "days": {
            today: {"watches": {"curl_cffi": 1}},
            yesterday: {"watches": {"curl_cffi": 1, "playwright": 1}},
        }
    }))
    stats = tier_metrics.rolling_stats(window_days=30)
    assert stats["watches"]["curl_cffi"] == 2
    assert stats["watches"]["playwright"] == 1
    assert stats["watches"]["_total"] == 3


def test_rolling_stats_excludes_old(monkeypatch, tmp_path):
    """Records older than window_days should NOT count in rolling stats."""
    fake = tmp_path / "tm.json"
    monkeypatch.setattr(tier_metrics, "METRICS_FILE", fake)
    old_day = (dt.datetime.now(dt.UTC) - dt.timedelta(days=10)).strftime("%Y-%m-%d")
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    fake.write_text(json.dumps({
        "days": {
            old_day: {"watches": {"curl_cffi": 100}},  # very old
            today: {"watches": {"curl_cffi": 1}},
        }
    }))
    stats = tier_metrics.rolling_stats(window_days=3)  # narrow window
    assert stats["watches"]["curl_cffi"] == 1  # old day excluded


def test_success_rate_computed_correctly(monkeypatch, tmp_path):
    fake = tmp_path / "tm.json"
    monkeypatch.setattr(tier_metrics, "METRICS_FILE", fake)
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    fake.write_text(json.dumps({
        "days": {
            today: {"watches": {"curl_cffi": 7, "failed": 3}},
        }
    }))
    stats = tier_metrics.rolling_stats()
    # 7 successes out of 10 total = 70%
    assert stats["watches"]["_success_rate"] == 0.7


def test_recommended_tier_returns_none_when_no_data(monkeypatch, tmp_path):
    fake = tmp_path / "tm.json"
    monkeypatch.setattr(tier_metrics, "METRICS_FILE", fake)
    assert tier_metrics.recommended_tier("watches") is None


def test_recommended_tier_returns_curl_cffi_when_healthy(monkeypatch, tmp_path):
    fake = tmp_path / "tm.json"
    monkeypatch.setattr(tier_metrics, "METRICS_FILE", fake)
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    fake.write_text(json.dumps({
        "days": {today: {"watches": {"curl_cffi": 10}}},
    }))
    assert tier_metrics.recommended_tier("watches") == "curl_cffi"


def test_recommended_tier_picks_better_tier_when_curl_cffi_degraded(monkeypatch, tmp_path):
    """If curl_cffi succeeded < threshold, recommend the strongest working tier."""
    fake = tmp_path / "tm.json"
    monkeypatch.setattr(tier_metrics, "METRICS_FILE", fake)
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    # curl_cffi 1/10 = 10%, patchright 7/10, nodriver 2/10
    fake.write_text(json.dumps({
        "days": {today: {"watches": {
            "curl_cffi": 1, "patchright": 7, "nodriver": 2,
        }}},
    }))
    # 10% is below MIN_SUCCESS_RATE (0.40), so should pick the next best
    assert tier_metrics.recommended_tier("watches") == "patchright"


def test_recommended_tier_insufficient_data_returns_none(monkeypatch, tmp_path):
    """Less than 5 total observations → don't make confident recommendation."""
    fake = tmp_path / "tm.json"
    monkeypatch.setattr(tier_metrics, "METRICS_FILE", fake)
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    fake.write_text(json.dumps({
        "days": {today: {"watches": {"curl_cffi": 2}}},
    }))
    assert tier_metrics.recommended_tier("watches") is None


def test_format_digest_lines_empty_when_no_data(monkeypatch, tmp_path):
    fake = tmp_path / "tm.json"
    monkeypatch.setattr(tier_metrics, "METRICS_FILE", fake)
    assert tier_metrics.format_digest_lines() == []


def test_format_digest_lines_includes_each_path(monkeypatch, tmp_path):
    fake = tmp_path / "tm.json"
    monkeypatch.setattr(tier_metrics, "METRICS_FILE", fake)
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    fake.write_text(json.dumps({
        "days": {today: {
            "watches": {"curl_cffi": 5, "playwright": 2},
            "pledge": {"playwright": 3, "failed": 1},
        }},
    }))
    lines = tier_metrics.format_digest_lines(window_days=7)
    text = "\n".join(lines)
    assert "watches" in text
    assert "pledge" in text
    assert "curl_cffi" in text
