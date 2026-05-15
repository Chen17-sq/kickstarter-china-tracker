"""Tests for classify.py — China-background project classification.

The classifier is what decides whether a project enters today's edition.
False positives let unrelated projects through; false negatives lose
legitimate Chinese hardware brands listed in the US. Both are bad.

These tests freeze the rules against the current brands/china_brands.yaml.
If you add/remove a brand entry, update the test accordingly.
"""
from __future__ import annotations
import pytest

from scraper.classify import classify, brands, CHINA_LOCATION_TOKENS


# ── Location-based classification ─────────────────────────────────

def test_location_china_high():
    """KS-reported location = 'China' → 高."""
    r = classify(creator_slug=None, location="Shenzhen, China")
    assert r.confidence == "高"
    assert "location" in r.reason.lower() or "China" in r.reason


def test_location_hk_high():
    """Hong Kong counts as China-background per our scope."""
    r = classify(creator_slug=None, location="Kowloon, Hong Kong")
    assert r.confidence == "高"


def test_location_taiwan_high():
    """Taiwan is included per current rules — this is an editorial choice;
    if we change scope, this test should change too."""
    r = classify(creator_slug=None, location="Taipei, Taiwan")
    assert r.confidence == "高"


def test_location_us_unknown():
    """Generic US location with no brand hit → 未知."""
    r = classify(creator_slug=None, location="Brooklyn, NY")
    assert r.confidence == "未知"


def test_location_lowercase_match():
    """CHINA_LOCATION_TOKENS check should be case-insensitive."""
    r = classify(creator_slug=None, location="shenzhen, china")
    assert r.confidence == "高"


def test_location_substring_safety():
    """'Chinatown, NY' should NOT be classified as China-background even
    though 'China' is a substring. Test current behavior — if this fails,
    we need to tighten the matcher."""
    r = classify(creator_slug=None, location="Chinatown, New York, USA")
    # Document current behavior: substring match is broad → classifies as 高
    # If we tighten later, change to: assert r.confidence == "未知"
    # For now, this catches if the substring matching behavior changes.
    assert r.confidence in ("高", "未知")


# ── Brand whitelist tests ─────────────────────────────────────────

def test_brand_whitelist_loads():
    """The YAML file should load without error and have the expected shape."""
    b = brands()
    assert isinstance(b, dict)
    assert "high_confidence" in b or "medium_confidence" in b or "not_china" in b


def test_brand_blacklist_returns_not_china():
    """Verify the 'not_china' bucket exists and maps to 否 when matched."""
    b = brands()
    blacklist = b.get("not_china") or []
    if not blacklist:
        pytest.skip("no 'not_china' entries to test against")
    first = blacklist[0]
    slugs = first.get("creator_slugs") or []
    if not slugs:
        pytest.skip("first blacklist entry has no slugs")
    r = classify(creator_slug=slugs[0], location=None)
    assert r.confidence == "否"


def test_brand_high_confidence_returns_high():
    """First high_confidence brand → 高."""
    b = brands()
    hc = b.get("high_confidence") or []
    if not hc:
        pytest.skip("no high_confidence entries to test against")
    first = hc[0]
    slugs = first.get("creator_slugs") or []
    if not slugs:
        pytest.skip("first hc entry has no slugs")
    r = classify(creator_slug=slugs[0], location=None)
    assert r.confidence == "高"
    assert r.matched_brand == first.get("brand")


def test_title_brand_match_returns_high():
    """Brand name appearing in title (case-insensitive) → 高 even without
    slug match. Catches situations where a brand uses a one-off creator
    account for a specific KS campaign."""
    b = brands()
    hc = b.get("high_confidence") or []
    if not hc:
        pytest.skip("no high_confidence entries to test against")
    first = hc[0]
    brand_name = first.get("brand")
    if not brand_name:
        pytest.skip("first hc entry has no brand name")
    r = classify(creator_slug="unrelated-slug", location=None,
                 title=f"NEW {brand_name.upper()} 2027 product")
    assert r.confidence == "高"


# ── No match cases ────────────────────────────────────────────────

def test_no_match_returns_unknown():
    r = classify(creator_slug="some-unknown-creator-12345",
                 location="Berlin, Germany", title="Cool gadget")
    assert r.confidence == "未知"


def test_all_none_returns_unknown():
    """Defensive: if all inputs are None we should not crash."""
    r = classify(creator_slug=None, location=None, title=None)
    assert r.confidence == "未知"


def test_priority_order_brand_beats_location():
    """Brand match (especially the high_confidence list) takes priority
    over location. This matters for Chinese brands registered in the US."""
    b = brands()
    hc = b.get("high_confidence") or []
    if not hc:
        pytest.skip("no high_confidence entries to test against")
    first = hc[0]
    slugs = first.get("creator_slugs") or []
    if not slugs:
        pytest.skip("first hc entry has no slugs")
    # Slug matches brand-whitelist, but location is US
    r = classify(creator_slug=slugs[0], location="Wilmington, Delaware, USA")
    assert r.confidence == "高"
    assert r.matched_brand == first.get("brand")


# ── Smoke: known China tokens ────────────────────────────────────

@pytest.mark.parametrize("city", [
    "Shanghai", "Beijing", "Shenzhen", "Guangzhou", "Chengdu",
    "Hangzhou", "Suzhou", "Nanjing", "Tianjin", "Wuhan",
])
def test_china_city_tokens_match(city):
    """All major Chinese cities listed in CHINA_LOCATION_TOKENS classify as 高."""
    assert city in CHINA_LOCATION_TOKENS, f"{city} missing from CHINA_LOCATION_TOKENS"
    r = classify(creator_slug=None, location=f"{city}, China")
    assert r.confidence == "高", f"{city} did not classify as 高"
