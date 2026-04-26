"""Generate site/sitemap.xml from the current state.

Lists every page Pages serves so search engines can discover them all:
  - index.html (front page)
  - subscribe.html
  - stats.html
  - editions/ (archive index)
  - editions/<date>.html (every past edition)

Cron writes a fresh sitemap each run so newly-archived editions are
indexed within a day.
"""
from __future__ import annotations
import datetime as dt
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"
EDITIONS = SITE / "editions"
BASE_URL = "https://chen17-sq.github.io/kickstarter-china-tracker"


def write_sitemap() -> Path:
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    urls: list[tuple[str, str, str]] = [
        # (url, lastmod, changefreq)
        (f"{BASE_URL}/", today, "daily"),
        (f"{BASE_URL}/subscribe.html", today, "monthly"),
        (f"{BASE_URL}/stats.html", today, "daily"),
        (f"{BASE_URL}/editions/", today, "daily"),
        (f"{BASE_URL}/editions/latest.html", today, "daily"),
    ]
    # Add every dated edition
    if EDITIONS.exists():
        for f in sorted(EDITIONS.glob("*.html")):
            stem = f.stem
            if stem in ("latest", "index"):
                continue
            try:
                d = dt.datetime.strptime(stem, "%Y-%m-%d")
                lastmod = d.strftime("%Y-%m-%d")
                urls.append((f"{BASE_URL}/editions/{stem}.html", lastmod, "yearly"))
            except ValueError:
                continue

    body = ['<?xml version="1.0" encoding="UTF-8"?>']
    body.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for url, lastmod, changefreq in urls:
        body.append("  <url>")
        body.append(f"    <loc>{url}</loc>")
        body.append(f"    <lastmod>{lastmod}</lastmod>")
        body.append(f"    <changefreq>{changefreq}</changefreq>")
        body.append("  </url>")
    body.append("</urlset>")

    SITE.mkdir(parents=True, exist_ok=True)
    out = SITE / "sitemap.xml"
    out.write_text("\n".join(body) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    p = write_sitemap()
    print(f"wrote {p.relative_to(REPO_ROOT)}")
