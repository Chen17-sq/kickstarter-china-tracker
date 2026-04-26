"""Generate assets/banner.svg — an Editorial / Swiss masthead with live KPIs.

GitHub README renders embedded SVGs via <img>, which gives us typography +
hairline layout that plain markdown can't express. The cron writes a fresh
banner each run so the numbers always reflect the latest snapshot.

Visual rules echo the Pages site:
  - Warm off-white canvas, near-black ink
  - One restrained accent (NYT red #c8102e) — pulse dot, prelaunch number
  - 1px hairlines as section dividers, no shadows or rounded corners
  - Inter / Inter Tight stack (system fallback when fonts not installed)
"""
from __future__ import annotations
import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECTS = REPO_ROOT / "data" / "projects.json"
ASSETS = REPO_ROOT / "assets"

W = 1280
H = 360


def fmt_usd_short(n: float) -> str:
    if n >= 1_000_000:
        s = f"${n/1e6:.1f}M"
        return s.replace(".0M", "M")
    if n >= 1_000:
        return f"${round(n/1e3)}K"
    return f"${round(n):,}"


def kpi_cell(x: int, label: str, value: str, color: str = "#0d0d0d", *, last: bool = False) -> str:
    """A single KPI column: big number + small uppercase label."""
    cell_w = (W - 120) // 5  # 5 columns, 60px gutters left/right
    out = []
    out.append(
        f'<text x="{x}" y="282" font-family="Inter Tight, Inter, -apple-system, sans-serif" '
        f'font-size="42" font-weight="700" fill="{color}" letter-spacing="-1">{value}</text>'
    )
    out.append(
        f'<text x="{x}" y="316" font-size="11" font-weight="600" fill="#6b6b6b" '
        f'letter-spacing="1.5">{label.upper()}</text>'
    )
    if not last:
        # vertical hairline divider
        out.append(
            f'<line x1="{x + cell_w - 24}" y1="248" x2="{x + cell_w - 24}" y2="328" '
            f'stroke="#d6d6d1" stroke-width="1"/>'
        )
    return "\n  ".join(out)


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

    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    cell_w = (W - 120) // 5

    kpis = [
        ("追踪总数", str(len(projects)), "#0d0d0d"),
        ("未发布", str(counts["prelaunch"]), "#c8102e"),
        ("在筹中", str(counts["live"]), "#1c4ed8"),
        ("已成功", str(counts["successful"]), "#0d0d0d"),
        ("KS 精选", f"★ {pwl}", "#0d0d0d"),
    ]
    kpi_svg = []
    for i, (label, value, color) in enumerate(kpis):
        x = 60 + i * cell_w
        kpi_svg.append(kpi_cell(x, label, value, color, last=(i == 4)))

    return f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="Kickstarter China Tracker — {today} · {len(projects)} projects tracked">
  <rect width="{W}" height="{H}" fill="#fafaf7"/>

  <!-- Pulse dot + kicker -->
  <circle cx="64" cy="56" r="4" fill="#c8102e"/>
  <text x="78" y="60" font-family="Inter, -apple-system, sans-serif" font-size="13"
        font-weight="600" fill="#6b6b6b" letter-spacing="2">DAILY · UPDATED {today}</text>

  <!-- Top hairline -->
  <line x1="60" y1="80" x2="{W-60}" y2="80" stroke="#0d0d0d" stroke-width="1"/>

  <!-- Display title -->
  <text x="60" y="158" font-family="Inter Tight, Inter, -apple-system, sans-serif"
        font-size="58" font-weight="800" fill="#0d0d0d" letter-spacing="-1.5">Kickstarter China Tracker</text>

  <!-- Dek -->
  <text x="60" y="194" font-family="Inter, -apple-system, sans-serif" font-size="17" fill="#3a3a3a">每日追踪 Kickstarter 上中国背景的消费硬件项目 — pre-launch · live · 已结束</text>
  <text x="60" y="218" font-family="Inter, -apple-system, sans-serif" font-size="13" fill="#6b6b6b">在筹合计已筹 {fmt_usd_short(total_live_usd)} · 直接读取 KS Discover JSON · GitHub Actions 每日 01:00 UTC 刷新</text>

  <!-- KPI hairline -->
  <line x1="60" y1="240" x2="{W-60}" y2="240" stroke="#0d0d0d" stroke-width="1"/>

  <!-- KPI cells -->
  {chr(10).join(kpi_svg)}

  <!-- Bottom hairline -->
  <line x1="60" y1="{H-12}" x2="{W-60}" y2="{H-12}" stroke="#0d0d0d" stroke-width="1"/>
</svg>
'''


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _xml_escape(s: str) -> str:
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\"", "&quot;"))


def _highlight_card(y: int, rank: int, p: dict, *, kind: str) -> str:
    """One row of the snapshot card: rank, title, blurb, right-aligned metric."""
    title = _xml_escape(_truncate(p.get("title") or "", 52))
    blurb = _xml_escape(_truncate(p.get("blurb_zh") or p.get("blurb") or "", 42))
    star = '<tspan fill="#c8102e" font-weight="700">★ </tspan>' if p.get("project_we_love") else ""
    if kind == "prelaunch":
        right_value = f'{int(p.get("followers") or 0):,}'
        right_label = "FOLLOWERS"
    else:
        right_value = fmt_usd_short(float(p.get("pledged_usd") or 0))
        right_label = f'{int(p.get("backers") or 0):,} BACKERS'
    return (
        f'<text x="40" y="{y + 4}" font-family="Inter Tight, Inter, sans-serif" '
        f'font-size="32" font-weight="800" fill="#9a9a96" letter-spacing="-1">{rank}</text>'
        f'<text x="84" y="{y - 6}" font-family="Inter, -apple-system, sans-serif" '
        f'font-size="14" font-weight="600" fill="#0d0d0d">{star}{title}</text>'
        f'<text x="84" y="{y + 14}" font-family="Inter, -apple-system, sans-serif" '
        f'font-size="12" fill="#3a3a3a">{blurb}</text>'
        f'<text x="600" y="{y - 6}" text-anchor="end" '
        f'font-family="Inter Tight, Inter, sans-serif" font-size="22" font-weight="700" '
        f'fill="#0d0d0d" letter-spacing="-.5">{right_value}</text>'
        f'<text x="600" y="{y + 14}" text-anchor="end" '
        f'font-family="Inter, sans-serif" font-size="10" font-weight="600" '
        f'fill="#9a9a96" letter-spacing="1.5">{right_label}</text>'
    )


def build_snapshot_svg(curr: dict) -> str:
    """Two-column 'Today's snapshot' SVG: top-3 prelaunch and top-3 live."""
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
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    W = 1280
    H = 460

    pre_rows = "\n  ".join(
        _highlight_card(110 + i * 100, i + 1, p, kind="prelaunch")
        for i, p in enumerate(prelaunch)
    )
    live_rows = "\n  ".join(
        _highlight_card(110 + i * 100, i + 1, p, kind="live")
        for i, p in enumerate(live)
    )

    return f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="Kickstarter China Tracker · Today's snapshot · {today}">
  <rect width="{W}" height="{H}" fill="#fafaf7"/>

  <!-- Header band -->
  <text x="40" y="48" font-family="Inter, sans-serif" font-size="11"
        font-weight="600" fill="#6b6b6b" letter-spacing="2">TODAY · {today}</text>
  <text x="40" y="84" font-family="Inter Tight, Inter, sans-serif" font-size="28"
        font-weight="800" fill="#0d0d0d" letter-spacing="-1">今日快照</text>

  <!-- Top hairline -->
  <line x1="40" y1="100" x2="{W-40}" y2="100" stroke="#0d0d0d" stroke-width="1"/>

  <!-- Left column: Prelaunch -->
  <g transform="translate(0, 0)">
    <text x="40" y="138" font-family="Inter, sans-serif" font-size="10"
          font-weight="600" fill="#c8102e" letter-spacing="2.5">⏳ PRELAUNCH · TOP BY FOLLOWERS</text>
    {pre_rows}
  </g>

  <!-- Vertical divider -->
  <line x1="640" y1="118" x2="640" y2="{H-40}" stroke="#d6d6d1" stroke-width="1"/>

  <!-- Right column: Live -->
  <g transform="translate(640, 0)">
    <text x="40" y="138" font-family="Inter, sans-serif" font-size="10"
          font-weight="600" fill="#1c4ed8" letter-spacing="2.5">🔴 LIVE · TOP BY USD RAISED</text>
    {live_rows}
  </g>

  <!-- Bottom hairline -->
  <line x1="40" y1="{H-20}" x2="{W-40}" y2="{H-20}" stroke="#0d0d0d" stroke-width="1"/>
</svg>
'''


def build_og_svg(curr: dict) -> str:
    """1280×640 social preview card. Larger typography for thumbnail rendering."""
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
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    return f'''<svg viewBox="0 0 1280 640" xmlns="http://www.w3.org/2000/svg" role="img">
  <rect width="1280" height="640" fill="#fafaf7"/>

  <circle cx="80" cy="100" r="6" fill="#c8102e"/>
  <text x="100" y="106" font-family="Inter, sans-serif" font-size="18"
        font-weight="600" fill="#6b6b6b" letter-spacing="3">DAILY · UPDATED {today}</text>

  <line x1="80" y1="138" x2="1200" y2="138" stroke="#0d0d0d" stroke-width="2"/>

  <text x="80" y="248" font-family="Inter Tight, Inter, sans-serif"
        font-size="80" font-weight="800" fill="#0d0d0d" letter-spacing="-2.5">Kickstarter</text>
  <text x="80" y="332" font-family="Inter Tight, Inter, sans-serif"
        font-size="80" font-weight="800" fill="#0d0d0d" letter-spacing="-2.5">China Tracker</text>

  <text x="80" y="396" font-family="Inter, sans-serif" font-size="22" fill="#3a3a3a">每日追踪 Kickstarter 上中国背景的消费硬件项目</text>
  <text x="80" y="430" font-family="Inter, sans-serif" font-size="18" fill="#6b6b6b">pre-launch · live · 已结束 · 数据每日 01:00 UTC 自动刷新</text>

  <line x1="80" y1="478" x2="1200" y2="478" stroke="#0d0d0d" stroke-width="2"/>

  <text x="80" y="556" font-family="Inter Tight, Inter, sans-serif" font-size="56"
        font-weight="700" fill="#0d0d0d" letter-spacing="-1.5">{len(projects)}</text>
  <text x="80" y="588" font-size="13" font-weight="600" fill="#6b6b6b" letter-spacing="2">追踪总数</text>

  <text x="320" y="556" font-family="Inter Tight, Inter, sans-serif" font-size="56"
        font-weight="700" fill="#c8102e" letter-spacing="-1.5">{counts['prelaunch']}</text>
  <text x="320" y="588" font-size="13" font-weight="600" fill="#6b6b6b" letter-spacing="2">未发布</text>

  <text x="540" y="556" font-family="Inter Tight, Inter, sans-serif" font-size="56"
        font-weight="700" fill="#1c4ed8" letter-spacing="-1.5">{counts['live']}</text>
  <text x="540" y="588" font-size="13" font-weight="600" fill="#6b6b6b" letter-spacing="2">在筹中</text>

  <text x="760" y="556" font-family="Inter Tight, Inter, sans-serif" font-size="56"
        font-weight="700" fill="#0d0d0d" letter-spacing="-1.5">{counts['successful']}</text>
  <text x="760" y="588" font-size="13" font-weight="600" fill="#6b6b6b" letter-spacing="2">已成功</text>

  <text x="980" y="556" font-family="Inter Tight, Inter, sans-serif" font-size="56"
        font-weight="700" fill="#0d0d0d" letter-spacing="-1.5">★ {pwl}</text>
  <text x="980" y="588" font-size="13" font-weight="600" fill="#6b6b6b" letter-spacing="2">KS 精选</text>

  <line x1="80" y1="612" x2="1200" y2="612" stroke="#0d0d0d" stroke-width="2"/>
</svg>
'''


def write_banner() -> Path:
    """Write all three editorial SVGs derived from data/projects.json."""
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
    return paths[0]  # for backwards compat


if __name__ == "__main__":
    p = write_banner()
    print(f"wrote {p.relative_to(REPO_ROOT)} (and snapshot.svg, og-card.svg)")
