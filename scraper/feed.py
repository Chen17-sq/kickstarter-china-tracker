"""Generate site/feed.xml — Atom 1.0 feed of all archived editions.

Why Atom and not RSS 2.0? Atom is more strictly specified (RSS 2.0 has
ambiguities around date formats and HTML escaping), is better supported
in modern readers, and is unambiguously UTF-8.

Each archived edition (site/editions/<YYYY-MM-DD>.html) becomes one feed
entry. Title = "Vol. N, No. X · YYYY-MM-DD". Content is intentionally a
short summary plus a link — we don't inline the full edition HTML
because most readers can't render our newsprint CSS faithfully anyway,
and a short summary keeps the feed small + ranks better in aggregators.

Subscribers who don't want email can point any RSS reader at:
  https://ks.aldrich.fyi/feed.xml

This is the second-fastest path to a new reader after the daily email,
and unlike email it doesn't require giving us an address (privacy
preserving — important for some readers).
"""
from __future__ import annotations
import datetime as dt
import html as _html
import re
from pathlib import Path

from ._common import edition_number, EPOCH

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"
EDITIONS = SITE / "editions"

# Canonical user-facing domain. Same content is also served from the
# github.io URL but we want feed readers to follow the nicer one.
BASE_URL = "https://ks.aldrich.fyi"

# Max entries in feed. Older editions are still on the site at their
# dated URLs; readers that care about backfill can crawl those.
MAX_ENTRIES = 30


def _extract_subject(html: str) -> str:
    """Pull the email subject line out of an archived edition's <title>.

    The archive writer (write_archive in email_notify.py) sets
    <title> to the same string used as the email subject — that's our
    most editorial summary in <40 chars.
    """
    m = re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
    if not m:
        return ""
    title = m.group(1).strip()
    # Subjects look like "[Vol. 1, No. 21] 2026-05-15 · 234 项 · …"
    # Keep it as-is — it's already the human-readable line we want.
    return title


def _summary_from_html(html: str, max_chars: int = 280) -> str:
    """Pull the KPI line out of the body. Falls back to a generic line."""
    # We render a KPI-style line near the top: "234 项追踪 · 76 在筹 …"
    # Find the first run of "<NUM> 项" in body text.
    m = re.search(r"(\d{1,5})\s*项追踪", html)
    if m:
        # Take 280 chars around it as the summary
        idx = m.start()
        snippet = re.sub(r"<[^>]+>", " ", html[max(0, idx-40):idx+280])
        snippet = re.sub(r"\s+", " ", snippet).strip()
        return snippet[:max_chars]
    return "Daily edition of the Kickstarter China Tracker."


def _edition_iso_date(stem: str) -> dt.datetime | None:
    try:
        d = dt.datetime.strptime(stem, "%Y-%m-%d")
        # Treat the date as 08:00 Beijing (00:00 UTC) — when the cron fires
        return d.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def write_feed() -> Path | None:
    """Generate site/feed.xml from the archived editions. Returns the path,
    or None if there are no editions yet."""
    if not EDITIONS.exists():
        return None

    entries: list[tuple[dt.datetime, str, Path]] = []  # (date, stem, path)
    for f in EDITIONS.glob("*.html"):
        if f.stem in ("latest", "index"):
            continue
        d = _edition_iso_date(f.stem)
        if d is None:
            continue
        entries.append((d, f.stem, f))
    if not entries:
        return None

    entries.sort(key=lambda t: -t[0].timestamp())  # newest first
    entries = entries[:MAX_ENTRIES]
    latest = entries[0][0]

    feed_id = f"{BASE_URL}/"  # Atom feed id — must be stable URI
    now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    body: list[str] = []
    body.append('<?xml version="1.0" encoding="UTF-8"?>')
    body.append('<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="zh-CN">')
    body.append("  <title>Kickstarter China Tracker</title>")
    body.append("  <subtitle>All The Crowd-Funded Hardware Fit To Print.</subtitle>")
    body.append(f'  <link rel="alternate" type="text/html" href="{BASE_URL}/"/>')
    body.append(f'  <link rel="self" type="application/atom+xml" href="{BASE_URL}/feed.xml"/>')
    body.append(f"  <id>{feed_id}</id>")
    body.append(f"  <updated>{latest.strftime('%Y-%m-%dT%H:%M:%SZ')}</updated>")
    body.append("  <author>")
    body.append("    <name>Aldrich Chen · 陈思蕲</name>")
    body.append("    <uri>https://aldrich.fyi</uri>")
    body.append("  </author>")
    body.append(
        '  <rights>© Kickstarter China Tracker. Project data © Kickstarter, PBC.</rights>'
    )
    body.append(f'  <generator uri="https://github.com/Chen17-sq/kickstarter-china-tracker">scraper.feed</generator>')

    for d, stem, path in entries:
        try:
            html = path.read_text(encoding="utf-8")
        except Exception:
            html = ""
        title = _extract_subject(html) or f"KS Tracker · {stem}"
        summary = _summary_from_html(html)
        url = f"{BASE_URL}/editions/{stem}.html"
        # Use the edition URL + date as a stable entry id
        entry_id = f"{BASE_URL}/editions/{stem}"
        # File mtime can drift if the archive is re-written; the date stem
        # is the canonical signal.
        published = d.strftime("%Y-%m-%dT%H:%M:%SZ")

        body.append("  <entry>")
        body.append(f"    <title>{_html.escape(title)}</title>")
        body.append(f'    <link rel="alternate" type="text/html" href="{url}"/>')
        body.append(f"    <id>{entry_id}</id>")
        body.append(f"    <updated>{published}</updated>")
        body.append(f"    <published>{published}</published>")
        body.append(f'    <summary type="text">{_html.escape(summary)}</summary>')
        body.append("  </entry>")

    body.append("</feed>")

    out = SITE / "feed.xml"
    out.write_text("\n".join(body) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    p = write_feed()
    if p:
        print(f"wrote {p.relative_to(REPO_ROOT)} (now={dt.datetime.now(dt.timezone.utc)})")
    else:
        print("no editions found — nothing to write")
