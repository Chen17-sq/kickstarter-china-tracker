"""Shared constants used across all publication surfaces.

Single source of truth for:
  - Edition number (Vol. 1 · No. N where N = days since project epoch)
  - Newsprint design tokens (color palette, font stacks)
  - Public URLs

If you want to change a color or the start date of the publication, this
is the only place to edit. See docs/DESIGN_RULES.md for the spec.
"""
from __future__ import annotations
import datetime as dt


# ─── Newsprint design tokens (also documented in docs/DESIGN_RULES.md §1) ──
PAPER = "#F9F9F7"
INK = "#111111"
RED = "#CC0000"
N100 = "#F5F5F5"
N400 = "#A3A3A3"
N500 = "#737373"
N600 = "#525252"
N700 = "#404040"
MUTED = "#E5E5E0"

# Font stacks (CJK fallbacks always last)
SERIF = "'Playfair Display','Times New Roman','Songti SC','Source Han Serif SC',serif"
BODY = "'Lora',Georgia,'Songti SC','Source Han Serif SC',serif"
SANS = "'Inter','Helvetica Neue','PingFang SC','Microsoft YaHei',sans-serif"
MONO = "'JetBrains Mono','Courier New',monospace"


# ─── Edition number — identical across banner.svg / email / social slides
# / Markdown report / stats page / docs. The user's "Vol. 1, No. N" line
# everywhere derives from this single computation. ─────────────────────
EPOCH = dt.datetime(2026, 4, 25, tzinfo=dt.timezone.utc)


def edition_number(now: dt.datetime | None = None) -> int:
    now = now or dt.datetime.now(dt.timezone.utc)
    return max(1, (now - EPOCH).days + 1)


# ─── Public URLs (used in OG tags, footers, social slides) ─────────────
PAGES_URL = "https://chen17-sq.github.io/kickstarter-china-tracker"
PAGES_HOST = "chen17-sq.github.io/kickstarter-china-tracker"
LATEST_REPORT_URL = f"{PAGES_URL}/editions/latest.html"
SUBSCRIBE_URL = f"{PAGES_URL}/subscribe.html"
GITHUB_URL = "https://github.com/Chen17-sq/kickstarter-china-tracker"
