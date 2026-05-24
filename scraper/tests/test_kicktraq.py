"""Tests for kicktraq.py — RSS feed parser + dedup logic."""
from __future__ import annotations

from scraper.kicktraq import parse_feed


def _feed(items_xml: str) -> str:
    return f"""<?xml version="1.0"?>
<rss>
<channel>
<title>Test Feed</title>
{items_xml}
</channel>
</rss>"""


def test_parse_single_item():
    xml = _feed("""
        <item>
            <title><![CDATA[Cool Project]]></title>
            <link>http://www.kicktraq.com/projects/alice/cool-project/</link>
        </item>
    """)
    hits = parse_feed(xml, "test.rss")
    assert len(hits) == 1
    assert hits[0].pathname == "/projects/alice/cool-project"
    assert hits[0].title == "Cool Project"
    assert hits[0].source_feed == "test.rss"


def test_parse_multiple_items():
    xml = _feed("""
        <item>
            <title>First</title>
            <link>http://www.kicktraq.com/projects/a/one/</link>
        </item>
        <item>
            <title>Second</title>
            <link>http://www.kicktraq.com/projects/b/two/</link>
        </item>
        <item>
            <title>Third</title>
            <link>http://www.kicktraq.com/projects/c/three/</link>
        </item>
    """)
    hits = parse_feed(xml, "feed.rss")
    assert len(hits) == 3
    assert {h.pathname for h in hits} == {"/projects/a/one", "/projects/b/two", "/projects/c/three"}


def test_dedup_within_feed():
    """Same KS pathname appearing twice in one feed → kept once."""
    xml = _feed("""
        <item>
            <title>First mention</title>
            <link>http://www.kicktraq.com/projects/x/dupe/</link>
        </item>
        <item>
            <title>Second mention</title>
            <link>http://www.kicktraq.com/projects/x/dupe/</link>
        </item>
    """)
    hits = parse_feed(xml, "feed.rss")
    assert len(hits) == 1
    assert hits[0].title == "First mention"  # first wins


def test_skip_items_without_link():
    xml = _feed("""
        <item><title>No link here</title></item>
        <item>
            <title>Has link</title>
            <link>http://www.kicktraq.com/projects/a/b/</link>
        </item>
    """)
    hits = parse_feed(xml, "feed.rss")
    assert len(hits) == 1
    assert hits[0].title == "Has link"


def test_skip_non_project_links():
    """Non-/projects/ links (e.g. blog posts) should be skipped."""
    xml = _feed("""
        <item>
            <title>Blog post</title>
            <link>http://www.kicktraq.com/blog/some-article</link>
        </item>
        <item>
            <title>Real project</title>
            <link>http://www.kicktraq.com/projects/creator/slug/</link>
        </item>
    """)
    hits = parse_feed(xml, "feed.rss")
    assert len(hits) == 1
    assert hits[0].title == "Real project"


def test_handles_cdata_title():
    """KS titles often contain special chars wrapped in CDATA."""
    xml = _feed("""
        <item>
            <title><![CDATA[Title with <em>HTML</em> & ampersands]]></title>
            <link>http://www.kicktraq.com/projects/x/y/</link>
        </item>
    """)
    hits = parse_feed(xml, "feed.rss")
    assert len(hits) == 1
    assert "HTML" in hits[0].title


def test_ks_url_derivation():
    """KicktraqHit.ks_url should derive the canonical KS URL from pathname."""
    xml = _feed("""
        <item>
            <title>X</title>
            <link>http://www.kicktraq.com/projects/alice/cool/</link>
        </item>
    """)
    hits = parse_feed(xml, "feed.rss")
    assert hits[0].ks_url == "https://www.kickstarter.com/projects/alice/cool"


def test_empty_feed_returns_empty_list():
    xml = _feed("")
    hits = parse_feed(xml, "feed.rss")
    assert hits == []


def test_handles_trailing_slash_or_not():
    """Kicktraq sometimes adds trailing slash, sometimes not — both must
    produce the same KS pathname."""
    xml_with_slash = _feed("""
        <item><title>A</title><link>http://www.kicktraq.com/projects/x/y/</link></item>
    """)
    xml_no_slash = _feed("""
        <item><title>A</title><link>http://www.kicktraq.com/projects/x/y</link></item>
    """)
    a = parse_feed(xml_with_slash, "f.rss")
    b = parse_feed(xml_no_slash, "f.rss")
    assert a[0].pathname == b[0].pathname == "/projects/x/y"


def test_parser_is_tolerant_of_https_or_http():
    """Both http:// and https:// in <link> should be accepted."""
    xml = _feed("""
        <item><title>http one</title><link>http://www.kicktraq.com/projects/a/b/</link></item>
        <item><title>https one</title><link>https://www.kicktraq.com/projects/c/d/</link></item>
    """)
    hits = parse_feed(xml, "f.rss")
    assert len(hits) == 2
