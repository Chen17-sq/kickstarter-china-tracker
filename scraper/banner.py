"""Generate Newsprint-styled SVG mastheads for the README.

Three artefacts, all refreshed on every cron run:
  - assets/banner.svg     — wide masthead embedded at top of README
  - assets/snapshot.svg   — 'Inside this issue' two-column highlights card
  - assets/og-card.svg    — 1280×640 social-preview card

Visual rules echo the Pages site:
  - Newsprint off-white #F9F9F7 paper with subtle dot grid
  - Ink black #111111 borders + text
  - One accent — Editorial Red #CC0000 — used sparingly for ★ / EDITION
  - Playfair Display 900 nameplate, JetBrains Mono metadata, Lora italic dek
  - Sharp 90° corners, hairlines, ornamental ✦✦✦ dividers
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECTS = REPO_ROOT / "data" / "projects.json"
ASSETS = REPO_ROOT / "assets"

PAPER = "#F9F9F7"
INK = "#111111"
RED = "#CC0000"
N400 = "#A3A3A3"
N500 = "#737373"
N700 = "#404040"

# Project birthday — used to compute the daily edition number
EPOCH = dt.datetime(2026, 4, 25, tzinfo=dt.timezone.utc)


def edition_number() -> int:
    days = (dt.datetime.now(dt.timezone.utc) - EPOCH).days + 1
    return max(1, days)


def fmt_usd_short(n: float) -> str:
    if n >= 1_000_000:
        s = f"${n/1e6:.1f}M"
        return s.replace(".0M", "M")
    if n >= 1_000:
        return f"${round(n/1e3)}K"
    return f"${round(n):,}"


def _xml_escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# ─── 1. Wide masthead banner (README top) ────────────────────────
def build_svg(curr: dict) -> str:
    projects = curr.get("projects", []) or []
    counts = {"prelaunch": 0, "live": 0, "successful": 0}
    pwl = 0
    total_live_usd = 0.0
    for p in projects:
        st = p.get("status")
        if st in counts:
            counts[st] += 1
        if p.get("project_we_love"):
            pwl += 1
        if st == "live":
            try:
                total_live_usd += float(p.get("pledged_usd") or 0)
            except (TypeError, ValueError):
                pass
    today = dt.datetime.now(dt.timezone.utc).strftime("%A, %B %d, %Y").upper()
    edition = edition_number()

    W, H = 1280, 460
    serif = "Playfair Display, Times New Roman, serif"
    body = "Lora, Georgia, serif"
    sans = "Inter, Helvetica, sans-serif"
    mono = "JetBrains Mono, Courier New, monospace"
    cell_w = (W - 80) // 5

    kpis = [
        ("TRACKED",    str(len(projects)),       INK),
        ("PRELAUNCH",  str(counts["prelaunch"]), RED),
        ("LIVE",       str(counts["live"]),      INK),
        ("FUNDED",     str(counts["successful"]),INK),
        ("EDITOR'S",   f"★ {pwl}",                INK),
    ]
    kpi_svg = []
    for i, (label, value, color) in enumerate(kpis):
        x = 40 + i * cell_w
        kpi_svg.append(
            f'<text x="{x + 14}" y="402" font-family="{serif}" font-size="48" '
            f'font-weight="900" fill="{color}" letter-spacing="-1">{value}</text>'
            f'<text x="{x + 14}" y="430" font-family="{sans}" font-size="10" '
            f'font-weight="700" fill="{N500}" letter-spacing="3">{label}</text>'
        )
        if i < 4:
            kpi_svg.append(
                f'<line x1="{x + cell_w}" y1="332" x2="{x + cell_w}" y2="448" '
                f'stroke="{INK}" stroke-width="1"/>'
            )

    return f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="Kickstarter China Tracker · Vol. 1 · No. {edition}">
  <rect width="{W}" height="{H}" fill="{PAPER}"/>

  <!-- Edition strip (top, ink reverse) -->
  <rect x="0" y="0" width="{W}" height="32" fill="{INK}"/>
  <circle cx="32" cy="16" r="3" fill="{RED}"/>
  <text x="44" y="20" font-family="{sans}" font-size="11" font-weight="700"
        fill="{PAPER}" letter-spacing="3">DAILY · LIVE EDITION · {today}</text>
  <text x="{W-40}" y="20" text-anchor="end" font-family="{mono}" font-size="11"
        font-weight="500" fill="{PAPER}" letter-spacing="2.5">VOL. 1 · NO. {edition}</text>

  <!-- Nameplate -->
  <text x="{W//2}" y="148" text-anchor="middle" font-family="{serif}" font-size="92"
        font-weight="900" fill="{INK}" letter-spacing="-3.5">Kickstarter China Tracker</text>

  <!-- Tag rules -->
  <line x1="40" y1="178" x2="{W-40}" y2="178" stroke="{INK}" stroke-width="1"/>
  <line x1="40" y1="216" x2="{W-40}" y2="216" stroke="{INK}" stroke-width="1"/>
  <text x="56" y="202" font-family="{mono}" font-size="11" font-weight="500"
        fill="{INK}" letter-spacing="2.5">BEIJING EDITION</text>
  <text x="{W//2}" y="202" text-anchor="middle" font-family="{serif}" font-size="14"
        font-style="italic" fill="{INK}">All The Crowd-Funded Hardware Fit To Print</text>
  <text x="{W-56}" y="202" text-anchor="end" font-family="{mono}" font-size="11"
        font-weight="500" fill="{INK}" letter-spacing="2.5">PLEDGED · {fmt_usd_short(total_live_usd)}</text>

  <!-- Dek -->
  <text x="{W//2}" y="262" text-anchor="middle" font-family="{body}" font-size="16"
        font-style="italic" fill="{N700}">每日追踪 Kickstarter 上中国背景的消费硬件项目 — Pre-launch · Live · 已结束</text>

  <!-- Ornament -->
  <text x="{W//2}" y="306" text-anchor="middle" font-family="{serif}" font-size="20"
        fill="{N400}" letter-spacing="14">✦  ✦  ✦</text>

  <!-- KPI hairline (top + bottom) -->
  <line x1="40" y1="332" x2="{W-40}" y2="332" stroke="{INK}" stroke-width="4"/>
  {chr(10).join(kpi_svg)}
  <line x1="40" y1="448" x2="{W-40}" y2="448" stroke="{INK}" stroke-width="1"/>
</svg>
'''


# ─── 2. 'Inside this issue' two-column snapshot ──────────────────
def _highlight_row(y: int, rank: int, p: dict, *, kind: str, col_x: int) -> str:
    serif = "Playfair Display, Times New Roman, serif"
    body = "Lora, Georgia, serif"
    sans = "Inter, Helvetica, sans-serif"
    mono = "JetBrains Mono, Courier New, monospace"

    title = _xml_escape(_truncate(p.get("title") or "", 50))
    blurb = _xml_escape(_truncate(p.get("blurb_zh") or p.get("blurb") or "", 38))
    star = (f'<tspan fill="{RED}" font-family="{serif}" font-weight="900">✦ </tspan>'
            if p.get("project_we_love") else "")
    if kind == "prelaunch":
        right_value = f'{int(p.get("followers") or 0):,}'
        right_label = "WATCHING"
    else:
        right_value = fmt_usd_short(float(p.get("pledged_usd") or 0))
        right_label = f'{int(p.get("backers") or 0):,} BACKERS'

    return (
        f'<text x="{col_x + 12}" y="{y + 6}" font-family="{serif}" font-size="36" '
        f'font-weight="900" fill="{N400}" letter-spacing="-1">{rank:02d}</text>'
        f'<text x="{col_x + 64}" y="{y - 6}" font-family="{serif}" '
        f'font-size="16" font-weight="700" fill="{INK}">{star}{title}</text>'
        f'<text x="{col_x + 64}" y="{y + 14}" font-family="{body}" '
        f'font-size="12" font-style="italic" fill="{N700}">{blurb}</text>'
        f'<text x="{col_x + 590}" y="{y - 6}" text-anchor="end" '
        f'font-family="{mono}" font-size="22" font-weight="700" fill="{INK}" '
        f'letter-spacing="-.5">{right_value}</text>'
        f'<text x="{col_x + 590}" y="{y + 14}" text-anchor="end" '
        f'font-family="{sans}" font-size="9" font-weight="700" fill="{N500}" '
        f'letter-spacing="2">{right_label}</text>'
    )


def build_snapshot_svg(curr: dict) -> str:
    projects = curr.get("projects", []) or []
    prelaunch = sorted(
        [p for p in projects if p.get("status") == "prelaunch"],
        key=lambda x: (
            0 if x.get("project_we_love") else 1,
            -(int(x.get("followers") or 0)),
        ),
    )[:3]
    live = sorted(
        [p for p in projects if p.get("status") == "live"],
        key=lambda x: -float(x.get("pledged_usd") or 0),
    )[:3]
    today = dt.datetime.now(dt.timezone.utc).strftime("%a, %b %d").upper()

    # Layout — section header on top, then column labels, then 3 rows.
    # Y math: rule at 110, column label at 144, row 0 at 184 (title at 178).
    # No element baseline overlaps a horizontal rule anymore.
    W, H = 1280, 540
    serif = "Playfair Display, Times New Roman, serif"
    sans = "Inter, Helvetica, sans-serif"
    mono = "JetBrains Mono, Courier New, monospace"

    pre_rows = "\n  ".join(
        _highlight_row(184 + i * 110, i + 1, p, kind="prelaunch", col_x=0)
        for i, p in enumerate(prelaunch)
    )
    live_rows = "\n  ".join(
        _highlight_row(184 + i * 110, i + 1, p, kind="live", col_x=640)
        for i, p in enumerate(live)
    )

    return f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="Inside This Issue · {today}">
  <rect width="{W}" height="{H}" fill="{PAPER}"/>

  <!-- Section header band -->
  <text x="40" y="44" font-family="{mono}" font-size="11" font-weight="500"
        fill="{N500}" letter-spacing="2.5">SECTION B · INSIDE THIS ISSUE · {today}</text>
  <text x="40" y="86" font-family="{serif}" font-size="36" font-weight="900"
        fill="{INK}" letter-spacing="-1">Today's Top Stories</text>

  <line x1="40" y1="110" x2="{W-40}" y2="110" stroke="{INK}" stroke-width="4"/>

  <!-- Left column: Prelaunch (label sits ABOVE the first row) -->
  <text x="40" y="146" font-family="{sans}" font-size="11" font-weight="700"
        fill="{RED}" letter-spacing="3">⏳ PRELAUNCH · TOP BY WATCHERS</text>
  {pre_rows}

  <!-- Vertical divider between columns -->
  <line x1="640" y1="126" x2="640" y2="{H-40}" stroke="{INK}" stroke-width="1"/>

  <!-- Right column: Live -->
  <text x="680" y="146" font-family="{sans}" font-size="11" font-weight="700"
        fill="{INK}" letter-spacing="3">🔴 LIVE · TOP BY USD RAISED</text>
  {live_rows}

  <!-- Bottom hairline -->
  <line x1="40" y1="{H-20}" x2="{W-40}" y2="{H-20}" stroke="{INK}" stroke-width="1"/>
</svg>
'''


# ─── 3. Social preview card 1280×640 ─────────────────────────────
def build_og_svg(curr: dict) -> str:
    projects = curr.get("projects", []) or []
    counts = {"prelaunch": 0, "live": 0, "successful": 0}
    pwl = 0
    total_live_usd = 0.0
    for p in projects:
        st = p.get("status")
        if st in counts:
            counts[st] += 1
        if p.get("project_we_love"):
            pwl += 1
        if st == "live":
            try:
                total_live_usd += float(p.get("pledged_usd") or 0)
            except (TypeError, ValueError):
                pass
    today = dt.datetime.now(dt.timezone.utc).strftime("%a · %b %d · %Y").upper()
    edition = edition_number()

    serif = "Playfair Display, Times New Roman, serif"
    body = "Lora, Georgia, serif"
    sans = "Inter, Helvetica, sans-serif"
    mono = "JetBrains Mono, Courier New, monospace"

    return f'''<svg viewBox="0 0 1280 640" xmlns="http://www.w3.org/2000/svg" role="img">
  <rect width="1280" height="640" fill="{PAPER}"/>

  <!-- Top edition strip -->
  <rect x="0" y="0" width="1280" height="46" fill="{INK}"/>
  <circle cx="50" cy="23" r="5" fill="{RED}"/>
  <text x="68" y="28" font-family="{sans}" font-size="14" font-weight="700"
        fill="{PAPER}" letter-spacing="3.5">DAILY · LIVE EDITION · {today}</text>
  <text x="1230" y="28" text-anchor="end" font-family="{mono}" font-size="14"
        font-weight="500" fill="{PAPER}" letter-spacing="3">VOL. 1 · NO. {edition}</text>

  <!-- Nameplate -->
  <text x="640" y="200" text-anchor="middle" font-family="{serif}" font-size="118"
        font-weight="900" fill="{INK}" letter-spacing="-4">Kickstarter</text>
  <text x="640" y="312" text-anchor="middle" font-family="{serif}" font-size="118"
        font-weight="900" fill="{INK}" letter-spacing="-4">China Tracker</text>

  <!-- Italic dek -->
  <text x="640" y="362" text-anchor="middle" font-family="{body}" font-size="20"
        font-style="italic" fill="{N700}">All the crowd-funded hardware fit to print, every morning at 09:00 Beijing.</text>

  <!-- Ornament + rule -->
  <text x="640" y="420" text-anchor="middle" font-family="{serif}" font-size="22"
        fill="{N400}" letter-spacing="20">✦  ✦  ✦</text>
  <line x1="80" y1="450" x2="1200" y2="450" stroke="{INK}" stroke-width="4"/>

  <!-- KPI strip -->
  <text x="160" y="544" text-anchor="middle" font-family="{serif}" font-size="64"
        font-weight="900" fill="{INK}" letter-spacing="-2">{len(projects)}</text>
  <text x="160" y="582" text-anchor="middle" font-family="{sans}" font-size="13"
        font-weight="700" fill="{N500}" letter-spacing="3">TRACKED</text>

  <text x="380" y="544" text-anchor="middle" font-family="{serif}" font-size="64"
        font-weight="900" fill="{RED}" letter-spacing="-2">{counts['prelaunch']}</text>
  <text x="380" y="582" text-anchor="middle" font-family="{sans}" font-size="13"
        font-weight="700" fill="{N500}" letter-spacing="3">PRELAUNCH</text>

  <text x="600" y="544" text-anchor="middle" font-family="{serif}" font-size="64"
        font-weight="900" fill="{INK}" letter-spacing="-2">{counts['live']}</text>
  <text x="600" y="582" text-anchor="middle" font-family="{sans}" font-size="13"
        font-weight="700" fill="{N500}" letter-spacing="3">LIVE</text>

  <text x="820" y="544" text-anchor="middle" font-family="{serif}" font-size="64"
        font-weight="900" fill="{INK}" letter-spacing="-2">{counts['successful']}</text>
  <text x="820" y="582" text-anchor="middle" font-family="{sans}" font-size="13"
        font-weight="700" fill="{N500}" letter-spacing="3">FUNDED</text>

  <text x="1080" y="544" text-anchor="middle" font-family="{serif}" font-size="64"
        font-weight="900" fill="{INK}" letter-spacing="-2">★ {pwl}</text>
  <text x="1080" y="582" text-anchor="middle" font-family="{sans}" font-size="13"
        font-weight="700" fill="{N500}" letter-spacing="3">EDITOR'S PICKS</text>

  <line x1="80" y1="612" x2="1200" y2="612" stroke="{INK}" stroke-width="1"/>
</svg>
'''


def write_banner() -> Path:
    if not PROJECTS.exists():
        raise SystemExit("data/projects.json not found — run scraper first")
    curr = json.loads(PROJECTS.read_text(encoding="utf-8"))
    ASSETS.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, builder in [
        ("banner.svg", build_svg),
        ("snapshot.svg", build_snapshot_svg),
        ("og-card.svg", build_og_svg),
    ]:
        p = ASSETS / name
        p.write_text(builder(curr), encoding="utf-8")
        paths.append(p)
    return paths[0]


if __name__ == "__main__":
    p = write_banner()
    print(f"wrote {p.relative_to(REPO_ROOT)} (and snapshot.svg, og-card.svg)")
