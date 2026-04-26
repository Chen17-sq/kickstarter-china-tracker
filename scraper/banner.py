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


def write_banner() -> Path:
    if not PROJECTS.exists():
        raise SystemExit("data/projects.json not found — run scraper first")
    curr = json.loads(PROJECTS.read_text(encoding="utf-8"))
    svg = build_svg(curr)
    ASSETS.mkdir(parents=True, exist_ok=True)
    out_path = ASSETS / "banner.svg"
    out_path.write_text(svg, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    p = write_banner()
    print(f"wrote {p.relative_to(REPO_ROOT)}")
