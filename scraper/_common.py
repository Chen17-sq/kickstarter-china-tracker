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


# ─── Number formatters · single source of truth ─────────────────────────
# Previously duplicated (with subtle drift) across notify.py / report.py
# / social.py. Edit here and every surface picks it up.

def fmt_usd(n) -> str:
    """Format a USD value with K/M suffix. None / non-numeric → em-dash."""
    if n is None or n == "":
        return "—"
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "—"
    if v >= 1_000_000:
        s = f"${v/1e6:.2f}M"
        # Trim: $1.00M → $1M, $1.20M → $1.2M (only when ending in 00M)
        return s.replace(".00M", "M").replace("0M", "M") if s.endswith("00M") else s
    if v >= 10_000:
        return f"${round(v/1e3)}K"
    if v >= 1_000:
        return f"${v/1e3:.1f}K"
    return f"${round(v):,}"


def fmt_int(n) -> str:
    """Format an integer with thousands separators. None → em-dash."""
    if n is None:
        return "—"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def fmt_pct(p) -> str:
    """Format KS percent_funded (already in % units; 100 = goal hit)."""
    if p is None or p == "":
        return "—"
    try:
        v = float(p)
    except (TypeError, ValueError):
        return "—"
    if v >= 10000:
        return f"{round(v/100):,}× goal"
    if v >= 1000:
        return f"{round(v):,}%"
    return f"{round(v)}%"
