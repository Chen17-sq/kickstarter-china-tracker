"""Generate 7 portrait PNG slides (1080×1350) for 小红书 / Xiaohongshu carousel.

Each cron run emits a complete carousel:
  site/social/latest/slide-01.png  cover (masthead + KPIs)
  site/social/latest/slide-02.png  ⏳ Pre-launch · Featured Top 3 (image+highlights)
  site/social/latest/slide-03.png  ⏳ Pre-launch · Top 10 list (text)
  site/social/latest/slide-04.png  🔴 Live · Featured Top 3 (image+highlights)
  site/social/latest/slide-05.png  🔴 Live · Top 10 list (text)
  site/social/latest/slide-06.png  ✅ Recently funded · Top 10 list (text)
  site/social/latest/slide-07.png  Subscribe CTA + URL

Also dated under site/social/<date>/ for permanent archiving.

Pages public URLs:
  https://chen17-sq.github.io/kickstarter-china-tracker/social/latest/slide-01.png
  https://chen17-sq.github.io/kickstarter-china-tracker/social/2026-04-26/slide-01.png

Visual rules echo the rest of the system: Newsprint paper #F9F9F7,
Playfair Display 900 nameplate, Lora italic dek, JetBrains Mono numbers,
NYT-red accent on prelaunch / ★ / 'breaking'.
"""
from __future__ import annotations
import asyncio
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOCIAL = REPO_ROOT / "site" / "social"
PROJECTS = REPO_ROOT / "data" / "projects.json"
HIGHLIGHTS_ZH = REPO_ROOT / "data" / "highlights_zh.json"


def load_highlights_zh() -> dict[str, list[str]]:
    """Load curated 4-bullet Chinese highlights keyed by KS pathname."""
    if not HIGHLIGHTS_ZH.exists():
        return {}
    try:
        raw = json.loads(HIGHLIGHTS_ZH.read_text(encoding="utf-8"))
        return {k: v for k, v in raw.items()
                if isinstance(v, list) and not k.startswith("_")}
    except Exception:
        return {}

SLIDE_W, SLIDE_H = 1080, 1350

# Tokens — same as Pages site / email / banner.svg
PAPER = "#F9F9F7"
INK = "#111111"
RED = "#CC0000"
N400 = "#A3A3A3"
N500 = "#737373"
N600 = "#525252"
N700 = "#404040"
MUTED = "#E5E5E0"

from ._common import edition_number  # noqa: E402

SUBSCRIBE_URL = "chen17-sq.github.io/kickstarter-china-tracker/subscribe.html"
PAGES_URL = "chen17-sq.github.io/kickstarter-china-tracker"


def fmt_usd(n) -> str:
    if n is None or n == "":
        return "—"
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "—"
    if v >= 1_000_000:
        s = f"${v/1e6:.2f}M"
        return s.replace(".00M", "M").replace("0M", "M") if s.endswith("00M") else s
    if v >= 10_000:
        return f"${round(v/1e3)}K"
    if v >= 1_000:
        return f"${v/1e3:.1f}K"
    return f"${round(v):,}"


def fmt_int(n) -> str:
    if n is None:
        return "—"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def _esc(s: str) -> str:
    return (str(s or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# ── Shared HTML wrapper ──────────────────────────────────────────
SHARED_CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&family=Playfair+Display:ital,wght@0,700;0,900;1,700&family=Lora:ital,wght@0,400;0,600;1,400&display=swap');
*{{box-sizing:border-box;border-radius:0!important;margin:0;padding:0}}
html,body{{width:{SLIDE_W}px;height:{SLIDE_H}px;background:{PAPER};color:{INK};
  font-family:'Lora','Songti SC',serif;-webkit-font-smoothing:antialiased;overflow:hidden;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='5' height='5'%3E%3Cpath fill='%23111111' fill-opacity='0.05' d='M1 4h1v1H1V4zm3-2h1v1H4V2z'/%3E%3C/svg%3E")}}
.serif{{font-family:'Playfair Display','Songti SC',serif}}
.body{{font-family:'Lora','Songti SC',serif}}
.sans{{font-family:'Inter',sans-serif}}
.mono{{font-family:'JetBrains Mono',monospace}}
.slide{{position:relative;width:100%;height:100%}}

/* Edition strip — every slide top */
.strip{{position:absolute;top:0;left:0;right:0;height:54px;
  background:{INK};color:{PAPER};display:flex;align-items:center;justify-content:space-between;
  padding:0 36px;font-family:'Inter',sans-serif;font-size:13px;font-weight:700;
  letter-spacing:.22em;text-transform:uppercase}}
.strip .dot{{display:inline-block;width:8px;height:8px;background:{RED};margin-right:12px;vertical-align:1px}}

/* Footer band — every slide bottom */
.foot{{position:absolute;bottom:0;left:0;right:0;height:64px;
  border-top:1px solid {INK};display:flex;align-items:center;justify-content:space-between;
  padding:0 36px;font-family:'JetBrains Mono',monospace;font-size:13px;color:{N500};
  letter-spacing:.06em;text-transform:uppercase}}
.foot .credo{{font-family:'Playfair Display',serif;font-style:italic;font-size:14px;
  color:{INK};letter-spacing:0;text-transform:none}}

/* Section title block (used by content slides) */
.section{{padding:78px 56px 24px;border-bottom:4px solid {INK}}}
.section .kicker{{font-family:'Inter',sans-serif;font-size:13px;font-weight:700;
  letter-spacing:.22em;text-transform:uppercase;color:{RED};margin-bottom:10px}}
.section h2{{font-family:'Playfair Display',serif;font-weight:900;font-size:64px;
  line-height:1.0;letter-spacing:-2px;color:{INK}}}
.section .dek{{margin-top:14px;font-family:'Lora',serif;font-style:italic;font-size:18px;
  color:{N600};line-height:1.4}}
"""


def slide_html(body: str, *, today_long: str, edition: int) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>{SHARED_CSS}</style></head>
<body><div class="slide">
  <div class="strip">
    <span><span class="dot"></span>DAILY · {today_long}</span>
    <span class="mono" style="font-weight:500">VOL. 1 · NO. {edition}</span>
  </div>
  {body}
  <div class="foot">
    <span>{PAGES_URL}</span>
    <span class="credo">All The Crowd-Funded Hardware Fit To Print</span>
  </div>
</div></body></html>"""


# ── Slide 01 · Cover ─────────────────────────────────────────────
def slide_cover(d: dict) -> str:
    counts = d["counts"]
    body = f"""
    <div style="position:absolute;top:54px;left:0;right:0;bottom:64px;
                display:flex;flex-direction:column;justify-content:space-between;
                padding:80px 56px 48px">
      <div>
        <div class="kicker mono" style="font-size:14px;font-weight:600;letter-spacing:.22em;
             text-transform:uppercase;color:{N500};margin-bottom:30px">
          Beijing Edition · Issue No. {edition_number()}
        </div>
        <h1 class="serif" style="font-size:124px;font-weight:900;line-height:.92;
            letter-spacing:-4px;color:{INK}">Kickstarter</h1>
        <h1 class="serif" style="font-size:124px;font-weight:900;line-height:.92;
            letter-spacing:-4px;color:{INK};margin-top:6px">China Tracker</h1>
        <p class="body" style="margin-top:36px;font-style:italic;font-size:24px;line-height:1.45;
           color:{N700};max-width:24ch">每日追踪 Kickstarter 上中国背景的消费硬件项目</p>
        <p class="body" style="margin-top:14px;font-size:18px;color:{N600};line-height:1.5">
          Pre-launch · Live · 已结束 · 每日 09:00 北京时间</p>
      </div>
      <div style="border-top:4px solid {INK};border-bottom:4px solid {INK};display:flex;
                  justify-content:space-between;padding:30px 0">
        {_kpi_block("TRACKED", str(d["total"]), INK)}
        {_kpi_block("PRELAUNCH", str(counts["prelaunch"]), RED)}
        {_kpi_block("LIVE", str(counts["live"]), INK)}
        {_kpi_block("★ PICKS", str(d["pwl"]), INK)}
      </div>
    </div>"""
    return body


def _kpi_block(label: str, value: str, color: str) -> str:
    return f"""
    <div style="text-align:left">
      <div class="serif" style="font-size:74px;font-weight:900;letter-spacing:-2px;color:{color};line-height:1">
        {value}</div>
      <div class="sans" style="margin-top:10px;font-size:13px;font-weight:700;
           color:{N500};letter-spacing:.22em;text-transform:uppercase">{label}</div>
    </div>"""


# ── Highlights extraction (parses '|'-separated KS feature blurbs) ──
def _extract_highlights(p: dict, *, max_n: int = 4) -> list[str]:
    """Pull short bullet-style highlights from KS English blurb.

    KS creators often write blurbs like 'Dual Iris | 4K | RGB Laser | 7000 Lumens'.
    Split on '|' (or '·'), trim to short feature phrases. Fall back to the
    Chinese 一句话 if no English blurb has separators.
    """
    raw = p.get("blurb") or ""
    parts: list[str] = []
    if raw:
        for sep in ["|", "｜", "·", "•"]:
            if sep in raw:
                parts = [s.strip() for s in raw.split(sep) if s.strip()]
                break
    if not parts and raw:
        # No separators — single sentence; try to split on commas/periods
        parts = [raw[:80]]
    if not parts:
        zh = p.get("blurb_zh")
        if zh:
            parts = [zh]
    # Cap each highlight length so they fit nicely
    return [_truncate(s, 38) for s in parts[:max_n]]



# ── Slides 04 / 06 · Track TOP 3 (3-up product detail) ─────────
def _detail_row(rank: int, p: dict, *, kind: str, hl_map: dict) -> str:
    """One product card row: image left, title + 4 Chinese highlights right."""
    image_url = p.get("image_url") or ""
    title = _esc(_truncate(p.get("title") or "", 56))
    blurb_zh = _esc(p.get("blurb_zh") or "")
    brand = _esc(p.get("matched_brand_zh") or p.get("matched_brand") or p.get("creator_name") or "")
    country = _esc(p.get("country") or "")
    star = ('<span style="display:inline-block;background:'+RED+';color:'+PAPER+';'
            'font-family:Inter,sans-serif;font-size:10px;font-weight:700;'
            'letter-spacing:.18em;text-transform:uppercase;'
            'padding:3px 8px;margin-right:8px;vertical-align:2px">✦ KS PICK</span>'
           ) if p.get("project_we_love") else ""

    # Chinese highlights — fall back to English |-split when not curated
    pathname = p.get("pathname")
    highlights = hl_map.get(pathname) or _extract_highlights(p)
    bullets = "".join(
        f"""<li style="display:flex;gap:10px;margin:6px 0;
            font-family:'Lora','Songti SC',serif;font-size:16px;line-height:1.4;color:{INK}">
          <span style="color:{RED};font-weight:900;flex:none;font-family:'Inter',sans-serif">▸</span>
          <span>{_esc(h)}</span></li>"""
        for h in highlights[:4]
    )

    if kind == "prelaunch":
        big_value = fmt_int(p.get("followers"))
        big_label = "Watchers · 关注"
        big_color = RED
    else:  # live
        big_value = fmt_usd(p.get("pledged_usd"))
        big_label = f'{fmt_int(p.get("backers"))} Backers'
        big_color = INK

    # object-fit:contain → preserves entire product image with no crop;
    # paper-colored letterbox bars hide on Newsprint background. KS hero
    # photos vary in aspect (16:9 / 4:3 / square), so cover-cropping a
    # square container kept slicing off product features. Per user spec:
    # 'product image colors / aspect must not be modified'.
    image_html = (
        f'<img src="{_esc(image_url)}" style="width:100%;height:100%;'
        f'object-fit:contain;display:block" alt=""/>'
        if image_url else
        f'<div style="width:100%;height:100%;background:{MUTED};display:flex;'
        f'align-items:center;justify-content:center;font-family:Lora,serif;'
        f'font-style:italic;color:{N400}">No image</div>'
    )

    return f"""
    <div style="display:flex;gap:24px;padding:22px 36px;border-bottom:1px solid {INK};
                flex:1;min-height:0;align-items:stretch">

      <!-- Left: image (4:3 ratio for KS hero photos, smaller to avoid heavy crop)
           with rank badge below. No filter — original product colors preserved. -->
      <div style="flex:none;display:flex;flex-direction:column;gap:10px;width:280px">
        <div style="width:280px;height:210px;overflow:hidden;background:{PAPER};
                    border:1px solid {INK}">{image_html}</div>
        <div style="font-family:'Playfair Display',serif;font-size:32px;font-weight:900;
             color:{INK};letter-spacing:-1px;line-height:1;text-align:center">No. {rank:02d}</div>
      </div>

      <!-- Right: brand line + title + 4 bullets + big metric -->
      <div style="flex:1;min-width:0;display:flex;flex-direction:column;justify-content:space-between">
        <div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;
               color:{N500};letter-spacing:.18em;text-transform:uppercase;margin-bottom:8px">
            {star}{brand} &nbsp;·&nbsp; {country}
          </div>
          {f'<div style="font-family:Inter,sans-serif;font-size:11px;font-weight:700;color:{INK};letter-spacing:.04em;margin-bottom:8px">起步价 <span style="color:{RED}">{fmt_usd(p.get("min_pledge_usd"))}</span></div>' if p.get("min_pledge_usd") else ""}
          <h3 style="font-family:'Playfair Display',serif;font-size:24px;font-weight:900;
              line-height:1.15;letter-spacing:-.5px;color:{INK};margin:0 0 6px">{title}</h3>
          <div style="font-family:'Lora','Songti SC',serif;font-style:italic;font-size:14px;
               color:{N700};line-height:1.4;margin-bottom:8px">{blurb_zh}</div>
          <ul style="list-style:none;padding:0;margin:0">{bullets}</ul>
        </div>

        <!-- Bottom-right metric -->
        <div style="text-align:right;border-top:1px solid {INK};padding-top:10px;margin-top:10px">
          <span style="font-family:'JetBrains Mono',monospace;font-size:34px;font-weight:700;
                color:{big_color};letter-spacing:-.5px">{big_value}</span>
          <div style="font-family:'Inter',sans-serif;font-size:10px;font-weight:700;color:{N500};
               letter-spacing:.18em;text-transform:uppercase;margin-top:4px">{big_label}</div>
        </div>
      </div>
    </div>"""


def slide_track_top3(d: dict, *, kind: str) -> str:
    """Top 3 of a single track on one slide."""
    if kind == "prelaunch":
        items = sorted(
            d["prelaunch"],
            key=lambda x: (0 if x.get("project_we_love") else 1, -(int(x.get("followers") or 0))),
        )[:3]
        kicker = "⏳ TODAY'S TOP PRE-LAUNCH · BY WATCHERS"
        h2 = "未发布 · Top 3"
        kicker_color = RED
    else:  # live
        items = sorted(d["live"], key=lambda x: -float(x.get("pledged_usd") or 0))[:3]
        kicker = "🔴 TODAY'S TOP LIVE · BY USD RAISED"
        h2 = "在筹中 · Top 3"
        kicker_color = INK

    if not items:
        return _empty_section(kicker, "暂无项目")

    hl_map = load_highlights_zh()
    rows = "".join(_detail_row(i + 1, p, kind=kind, hl_map=hl_map) for i, p in enumerate(items))

    return f"""
    <div style="position:absolute;top:54px;left:0;right:0;bottom:64px;
                display:flex;flex-direction:column">
      <!-- Header band -->
      <div style="padding:18px 36px 14px;border-bottom:4px solid {INK};flex:none">
        <div style="font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;
             letter-spacing:.22em;text-transform:uppercase;color:{kicker_color};margin-bottom:4px">
          {kicker}</div>
        <h2 style="font-family:'Playfair Display',serif;font-weight:900;font-size:36px;
            letter-spacing:-1.2px;color:{INK};line-height:1;margin:0">{h2}</h2>
      </div>

      <!-- 3 product rows fill remaining space -->
      <div style="flex:1;display:flex;flex-direction:column;min-height:0">
        {rows}
      </div>
    </div>"""


# Backwards-compat aliases — generate_carousel() calls slide_track_top3 directly,
# but legacy imports might still reference these.
def slide_prelaunch_feature(d: dict) -> str:
    return slide_track_top3(d, kind="prelaunch")


def slide_live_feature(d: dict) -> str:
    return slide_track_top3(d, kind="live")




# ── Slide list (text-only) · Top 10 ─────────────────────────────
def _list_row(rank: int, p: dict, *, kind: str) -> str:
    title = _esc(_truncate(p.get("title") or "", 38))
    blurb = _esc(_truncate(p.get("blurb_zh") or p.get("blurb") or "", 28))
    star = ('<span style="color:'+RED+';font-family:Playfair Display;'
            'font-weight:900;margin-right:5px">✦</span>') if p.get("project_we_love") else ""
    if kind == "prelaunch":
        right = f'{fmt_int(p.get("followers"))}'
        right_lbl = "Watchers"
    elif kind == "live":
        right = f'{fmt_usd(p.get("pledged_usd"))}'
        right_lbl = f'{fmt_int(p.get("backers"))} backers'
    else:  # successful
        right = f'{fmt_usd(p.get("pledged_usd"))}'
        right_lbl = f'{fmt_int(p.get("backers"))} backers'
    # Compact row sizing — must fit 10 rows in 1080×1350 portrait
    return f"""
    <div style="display:flex;gap:16px;padding:11px 0;border-bottom:1px solid {INK};align-items:flex-start">
      <div class="serif" style="flex:none;font-size:32px;font-weight:900;line-height:1;
           color:{N400};letter-spacing:-1px;width:50px;font-variant-numeric:tabular-nums">{rank:02d}</div>
      <div style="flex:1;min-width:0">
        <div class="serif" style="font-size:19px;font-weight:700;line-height:1.18;color:{INK};letter-spacing:-.2px">{star}{title}</div>
        <div class="body" style="margin-top:3px;font-style:italic;font-size:13px;color:{N700};line-height:1.3">{blurb}</div>
      </div>
      <div style="flex:none;text-align:right;min-width:160px">
        <div class="mono" style="font-size:19px;font-weight:700;color:{INK};letter-spacing:-.3px">{right}</div>
        <div class="sans" style="margin-top:2px;font-size:10px;font-weight:700;color:{N500};letter-spacing:.16em;text-transform:uppercase">{right_lbl}</div>
      </div>
    </div>"""


def slide_list(d: dict, *, kind: str) -> str:
    if kind == "prelaunch":
        items = sorted(
            d["prelaunch"],
            key=lambda x: (0 if x.get("project_we_love") else 1, -(int(x.get("followers") or 0))),
        )[:10]
        kicker = "⏳ PRE-LAUNCH · TOP 10 BY WATCHERS"
        h2 = "未发布 · Top 10"
        dek = "按 watchers 排序 · KS Editor's Picks 优先"
    elif kind == "live":
        items = sorted(d["live"], key=lambda x: -float(x.get("pledged_usd") or 0))[:10]
        kicker = "🔴 LIVE · TOP 10 BY USD RAISED"
        h2 = "在筹中 · Top 10"
        dek = "按已筹 USD 排序"
    else:
        # successful from full dataset
        all_proj = d.get("_all", [])
        items = sorted(
            [p for p in all_proj if p.get("status") == "successful"],
            key=lambda x: -float(x.get("pledged_usd") or 0),
        )[:10]
        kicker = "✅ RECENTLY FUNDED · TOP 10"
        h2 = "已成功 · Top 10"
        dek = "按已筹 USD 排序"

    rows = "".join(_list_row(i + 1, p, kind=kind) for i, p in enumerate(items))
    if not rows:
        rows = f'<div class="body" style="padding:60px 0;text-align:center;font-style:italic;color:{N400};font-size:20px">暂无项目</div>'
    return f"""
    <div class="section">
      <div class="kicker">{kicker}</div>
      <h2>{h2}</h2>
      <div class="dek">{_esc(dek)}</div>
    </div>
    <div style="padding:4px 56px">{rows}</div>"""


def _empty_section(kicker: str, msg: str) -> str:
    return f"""
    <div class="section">
      <div class="kicker">{kicker}</div>
      <h2>{msg}</h2>
    </div>"""


# ── Slide 09 · Subscribe CTA ────────────────────────────────────
def slide_cta(d: dict) -> str:
    return f"""
    <div style="position:absolute;top:54px;left:0;right:0;bottom:64px;
                display:flex;flex-direction:column;justify-content:center;
                padding:0 56px;text-align:center">
      <div class="kicker mono" style="font-size:14px;font-weight:700;letter-spacing:.22em;
           text-transform:uppercase;color:{RED};margin-bottom:24px">
        Subscribe · 订阅每日邮件
      </div>
      <h1 class="serif" style="font-size:88px;font-weight:900;line-height:.95;letter-spacing:-3px;color:{INK}">
        每日清晨</h1>
      <h1 class="serif" style="font-size:88px;font-weight:900;line-height:.95;letter-spacing:-3px;color:{INK};margin-top:6px">
        一份报纸</h1>
      <p class="body" style="margin-top:30px;font-size:22px;font-style:italic;line-height:1.5;color:{N700}">
        09:00 北京时间，整份 Newsprint 头版送到你邮箱。<br>
        免费 · 无广告 · 可随时取消。</p>
      <div style="margin-top:48px;display:inline-block;border:4px solid {INK};padding:24px 36px">
        <div class="sans" style="font-size:11px;font-weight:700;color:{N500};letter-spacing:.22em;text-transform:uppercase;margin-bottom:8px">订阅地址</div>
        <div class="mono" style="font-size:22px;font-weight:700;color:{INK};letter-spacing:-.5px">{SUBSCRIBE_URL}</div>
      </div>
      <div style="margin-top:32px;font-family:'Playfair Display';font-size:32px;color:{N400};letter-spacing:24px">✦  ✦  ✦</div>
    </div>"""


# ── Render glue ─────────────────────────────────────────────────
async def _render_pngs(html_strs: list[str], paths: list[Path]) -> None:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            viewport={"width": SLIDE_W, "height": SLIDE_H},
            device_scale_factor=2,  # @2x for crisp text
        )
        page = await context.new_page()
        for html, out_path in zip(html_strs, paths):
            await page.set_content(html, wait_until="networkidle", timeout=20_000)
            await page.wait_for_timeout(900)  # web font paint
            await page.screenshot(path=str(out_path), full_page=False, type="png")
        await context.close()
        await browser.close()


def generate_carousel() -> list[Path] | None:
    """Generate 9 slide PNGs. Returns paths or None on skip."""
    if not PROJECTS.exists():
        return None
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("  social: playwright not installed — skipping", file=sys.stderr)
        return None

    curr = json.loads(PROJECTS.read_text(encoding="utf-8"))
    # Reuse summary shape from notify
    from .notify import get_summary_data
    d = get_summary_data(curr)
    d["_all"] = curr.get("projects", [])

    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    today_long = dt.datetime.now(dt.timezone.utc).strftime("%a, %b %d, %Y").upper()
    edition = edition_number()
    wrap = lambda body: slide_html(body, today_long=today_long, edition=edition)

    # 7 slides — gainer (movers) slides dropped per redesign:
    #   01 cover · 02-03 prelaunch (feature top 3 + list top 10)
    #   04-05 live (feature top 3 + list top 10) · 06 successful · 07 CTA
    slides = [
        ("01", wrap(slide_cover(d))),
        ("02", wrap(slide_prelaunch_feature(d))),
        ("03", wrap(slide_list(d, kind="prelaunch"))),
        ("04", wrap(slide_live_feature(d))),
        ("05", wrap(slide_list(d, kind="live"))),
        ("06", wrap(slide_list(d, kind="successful"))),
        ("07", wrap(slide_cta(d))),
    ]

    latest_dir = SOCIAL / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)
    # Wipe old slides in latest/ so we don't keep stale ones
    for old in latest_dir.glob("slide-*.png"):
        old.unlink()

    paths: list[Path] = []
    htmls: list[str] = []
    for num, html in slides:
        p = latest_dir / f"slide-{num}.png"
        paths.append(p)
        htmls.append(html)

    try:
        asyncio.run(_render_pngs(htmls, paths))
    except Exception as e:
        print(f"  social: render failed ({e})", file=sys.stderr)
        return None

    # Also archive dated copy
    dated_dir = SOCIAL / today
    dated_dir.mkdir(parents=True, exist_ok=True)
    for p in paths:
        shutil.copy2(p, dated_dir / p.name)

    # Build a Newsprint-styled index page that previews + links the 9 slides
    _write_carousel_index(latest_dir, today, edition, len(paths))

    return paths


def _write_carousel_index(latest_dir: Path, today: str, edition: int, n: int) -> None:
    """Write site/social/index.html: a Newsprint-styled gallery + zip download."""
    SOCIAL.mkdir(parents=True, exist_ok=True)
    serif = "'Playfair Display','Songti SC',serif"
    sans = "'Inter',sans-serif"
    mono = "'JetBrains Mono',monospace"
    body_f = "'Lora','Songti SC',serif"
    thumbs = "".join(
        f'<a href="./latest/slide-{i:02d}.png" target="_blank" '
        f'style="display:block;border:1px solid {INK};background:{PAPER};text-decoration:none">'
        f'<img src="./latest/slide-{i:02d}.png" style="display:block;width:100%;height:auto" alt="Slide {i}">'
        f'<div style="padding:8px 12px;font-family:{mono};font-size:11px;color:{N500};letter-spacing:.18em;text-transform:uppercase">SLIDE {i:02d}</div>'
        f'</a>'
        for i in range(1, n + 1)
    )
    page = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>Carousel · Kickstarter China Tracker</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&family=Playfair+Display:ital,wght@0,700;0,900;1,700&family=Lora:ital,wght@0,400;1,400&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;border-radius:0!important}}
body{{margin:0;background:{PAPER};color:{INK};font-family:{body_f};font-size:15px;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='4' height='4'%3E%3Cpath fill='%23111111' fill-opacity='0.05' d='M1 3h1v1H1V3zm2-2h1v1H3V1z'/%3E%3C/svg%3E")}}
.wrap{{max-width:1080px;margin:0 auto;background:{PAPER};border-left:1px solid {INK};border-right:1px solid {INK};min-height:100vh}}
.strip{{display:flex;justify-content:space-between;padding:8px 28px;background:{INK};color:{PAPER};font-family:{sans};font-size:10.5px;font-weight:600;letter-spacing:.2em;text-transform:uppercase}}
.strip .dot{{display:inline-block;width:6px;height:6px;background:{RED};margin-right:8px;vertical-align:1px}}
.mast{{padding:36px 28px 22px;border-bottom:4px solid {INK};text-align:center}}
.mast h1{{margin:0;font-family:{serif};font-weight:900;font-size:42px;line-height:.95;letter-spacing:-1.2px;color:{INK}}}
.mast .tag{{display:flex;justify-content:space-between;border-top:1px solid {INK};border-bottom:1px solid {INK};padding:8px 0;margin-top:14px;font-family:{mono};font-size:11px;letter-spacing:.18em;text-transform:uppercase;font-weight:500}}
.mast .center{{flex:1;text-align:center;font-style:italic;letter-spacing:0;font-family:{serif};font-size:13px;font-weight:400;text-transform:none}}
.section-h{{padding:24px 28px 12px;border-bottom:1px solid {INK}}}
.section-h .label{{font-family:{mono};font-size:11px;letter-spacing:2.5px;color:{N500}}}
.section-h h2{{margin:6px 0 0;font-family:{serif};font-weight:900;font-size:32px;letter-spacing:-1px;color:{INK}}}
.grid{{padding:24px 28px;display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}
.intro{{padding:24px 28px;font-family:{body_f};font-style:italic;color:{N700};line-height:1.55}}
.tips{{padding:8px 28px 24px;font-family:{body_f};color:{N700};font-size:14px;line-height:1.6}}
.tips code{{background:#eee;padding:1px 6px;font-family:{mono};font-size:12px}}
.foot{{margin-top:auto;padding:24px 28px 36px;border-top:4px solid {INK};font-family:{mono};font-size:10.5px;color:{N500};letter-spacing:.1em;text-transform:uppercase;text-align:center}}
.foot a{{color:{INK};text-decoration:none;border-bottom:2px solid {RED};padding-bottom:1px;font-weight:700}}
@media (max-width:680px){{.wrap{{border:0}} .grid{{grid-template-columns:repeat(2,1fr)}}}}
</style></head>
<body><div class="wrap">
<div class="strip"><span><span class="dot"></span>SOCIAL CAROUSEL · 9 SLIDES</span><span style="font-family:{mono};letter-spacing:.18em">VOL. 1 · NO. {edition}</span></div>
<header class="mast">
  <h1>Kickstarter China Tracker</h1>
  <div class="tag">
    <span style="padding:0 14px">Carousel for 小红书</span>
    <span class="center">All The Crowd-Funded Hardware Fit To Print</span>
    <span style="padding:0 14px">{today}</span>
  </div>
</header>
<div class="intro">
  9 张 1080×1350 portrait PNG · 直接发小红书 carousel post（最多 9 张）。每张图自带 Newsprint 设计 + Vol/No 编号 + 日期 · 自包含可独立分享。
</div>
<div class="section-h">
  <div class="label">SECTION · TODAY'S CAROUSEL</div>
  <h2>9 张拼图</h2>
</div>
<div class="grid">{thumbs}</div>
<div class="tips">
  <strong>下载</strong> · 点任意一张图查看，右键保存。或者整个目录拉下来：
  <code>git clone https://github.com/Chen17-sq/kickstarter-china-tracker</code>，<code>cd site/social/latest/</code>。
</div>
<footer class="foot">
  <a href="../">完整看板</a> &nbsp;·&nbsp;
  <a href="../editions/">日报存档</a> &nbsp;·&nbsp;
  <a href="../subscribe.html">订阅</a> &nbsp;·&nbsp;
  <a href="https://github.com/Chen17-sq/kickstarter-china-tracker">GitHub</a>
</footer>
</div></body></html>"""
    (SOCIAL / "index.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    paths = generate_carousel()
    if paths:
        for p in paths:
            print(f"  wrote {p.relative_to(REPO_ROOT)}")
    else:
        sys.exit(1)
