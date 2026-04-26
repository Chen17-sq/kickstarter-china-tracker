"""Send a daily HTML-email summary via Resend, in Newsprint design.

Drives off two env vars (set as repo secrets):
  - RESEND_API_KEY     — get one at https://resend.com (free 3000/mo)
  - NOTIFY_EMAIL_TO    — recipient address(es), comma-separated

Optional:
  - NOTIFY_EMAIL_FROM  — default 'KS China Tracker <onboarding@resend.dev>'.

Visual rules echo the Pages site / banner SVG exactly:
  - Newsprint off-white #F9F9F7 paper, ink black #111111
  - Playfair Display 900 nameplate centered, Lora italic dek
  - Vol. 1 / No. N edition number, BEIJING EDITION metadata bar
  - Ornamental ✦ ✦ ✦ section dividers
  - JetBrains Mono for all numbers, Inter for labels
  - Sharp 0-radius corners, 1px solid borders, no shadows

Run locally:
  python -m scraper.email_notify --dry-run    # writes preview to data/.tmp/
  python -m scraper.email_notify              # POST to Resend
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import httpx

from .notify import (
    get_summary_data, fmt_usd, fmt_int,
    PAGES_URL, LATEST_URL, REPO_ROOT, PROJECTS,
)
from .momentum import (
    conversion_per_watcher, projected_total, top_movers_from_rows,
)

RESEND_API_URL = "https://api.resend.com/emails"

# Project birthday — same as banner.py
EPOCH = dt.datetime(2026, 4, 25, tzinfo=dt.timezone.utc)


def edition_number() -> int:
    days = (dt.datetime.now(dt.timezone.utc) - EPOCH).days + 1
    return max(1, days)


# ── Newsprint design tokens (mirror site CSS) ────────────────────
PAPER = "#F9F9F7"
INK = "#111111"
RED = "#CC0000"
N400 = "#A3A3A3"
N500 = "#737373"
N600 = "#525252"
N700 = "#404040"

SERIF = "'Playfair Display', 'Times New Roman', 'Songti SC', serif"
BODY = "'Lora', Georgia, 'Songti SC', serif"
SANS = "'Inter', 'Helvetica Neue', 'PingFang SC', sans-serif"
MONO = "'JetBrains Mono', 'Courier New', monospace"


def _esc(s: str) -> str:
    return (str(s or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _load_highlights_zh() -> dict[str, list[str]]:
    """Curated 4-bullet Chinese highlights (same source as social.py)."""
    f = REPO_ROOT / "data" / "highlights_zh.json"
    if not f.exists():
        return {}
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
        return {k: v for k, v in raw.items()
                if isinstance(v, list) and not k.startswith("_")}
    except Exception:
        return {}


def _detail_card(p: dict, *, kind: str, hl_map: dict, rank: int) -> str:
    """Top-3 detail card for email — KS hero image + brand line + Chinese
    highlight bullets + big metric. Visual rules per user spec:
      - product image colors must NOT be filtered
      - 4:3 container with object-fit:contain so the product is never cropped
    """
    image_url = p.get("image_url") or ""
    title = _esc(p.get("title") or "(untitled)")
    blurb_zh = _esc(p.get("blurb_zh") or "")
    url = _esc(p.get("url") or "#")
    brand = _esc(p.get("matched_brand_zh") or p.get("matched_brand") or p.get("creator_name") or "")
    country = _esc(p.get("country") or "")
    star = (f'<span style="display:inline-block;background:{RED};color:{PAPER};'
            f'font-family:{SANS};font-size:9px;font-weight:700;letter-spacing:.2em;'
            f'text-transform:uppercase;padding:2px 6px;margin-right:6px;'
            f'vertical-align:2px">✦ KS PICK</span>'
           ) if p.get("project_we_love") else ""

    highlights = hl_map.get(p.get("pathname")) or []
    if not highlights and p.get("blurb"):
        # Fall back to splitting English blurb on '|' so empty entries
        # in highlights_zh.json still produce something readable.
        highlights = [s.strip() for s in p["blurb"].split("|") if s.strip()][:4]
    bullets = "".join(
        f"""<li style="margin:6px 0;font-family:{BODY};font-size:13.5px;line-height:1.5;
              color:{INK};list-style:none;padding-left:18px;position:relative">
          <span style="position:absolute;left:0;color:{RED};font-weight:900">▸</span>
          {_esc(h)}</li>"""
        for h in highlights[:4]
    )

    if kind == "prelaunch":
        big_value = fmt_int(p.get("followers"))
        big_label = "WATCHERS · 关注"
        big_color = RED
    else:
        big_value = fmt_usd(p.get("pledged_usd"))
        big_label = f"{fmt_int(p.get('backers'))} BACKERS"
        big_color = INK

    img_block = (
        f'<img src="{image_url}" width="240" height="180" '
        f'style="display:block;width:240px;height:180px;object-fit:contain;'
        f'background:{PAPER};border:1px solid {INK}" alt=""/>'
        if image_url else
        f'<div style="width:240px;height:180px;background:{MUTED};'
        f'border:1px solid {INK}"></div>'
    )

    return f'''
    <table role="presentation" cellspacing="0" cellpadding="0" border="0"
           style="width:100%;margin:18px 0;border-top:1px solid {INK};
                  border-collapse:collapse">
      <tr>
        <td style="padding:18px 0 0;width:240px;vertical-align:top">
          {img_block}
          <div style="text-align:center;margin-top:6px;font-family:{SERIF};
                      font-size:24px;font-weight:900;color:{INK};letter-spacing:-.5px">
            No. {rank:02d}</div>
        </td>
        <td style="padding:18px 0 0 18px;vertical-align:top">
          <div style="font-family:{MONO};font-size:10px;font-weight:700;color:{N500};
               letter-spacing:.18em;text-transform:uppercase;margin-bottom:6px">
            {star}{brand} &nbsp;·&nbsp; {country}</div>
          <a href="{url}" style="text-decoration:none;color:{INK};
             font-family:{SERIF};font-size:18px;font-weight:700;line-height:1.2;
             letter-spacing:-.3px;display:block">{title}</a>
          <div style="margin-top:6px;font-family:{BODY};font-style:italic;
               font-size:13px;color:{N700};line-height:1.4">{blurb_zh}</div>
          <ul style="list-style:none;padding:0;margin:10px 0 0">{bullets}</ul>
          <div style="margin-top:10px">
            <span style="font-family:{MONO};font-size:24px;font-weight:700;
                  color:{big_color};letter-spacing:-.3px">{big_value}</span>
            <span style="margin-left:8px;font-family:{SANS};font-size:9px;
                  font-weight:700;color:{N500};letter-spacing:.2em">{big_label}</span>
          </div>
        </td>
      </tr>
    </table>'''


def _row(p: dict, *, kind: str) -> str:
    star = (f'<span style="color:{RED};font-family:{SERIF};font-weight:900;'
            f'margin-right:6px">✦</span>') if p.get("project_we_love") else ""
    title = _esc(p.get("title") or "(untitled)")
    blurb_zh = _esc(p.get("blurb_zh") or p.get("blurb") or "")
    url = _esc(p.get("url") or "#")
    brand = _esc(p.get("matched_brand_zh") or p.get("matched_brand") or p.get("creator_name") or "")
    country = _esc(p.get("country") or "")

    # Meta line: brand · country · [conversion ratio | projection]
    meta_parts = [x for x in (brand, country) if x]
    cpw = conversion_per_watcher(p)
    if cpw is not None and kind == "live":
        meta_parts.append(f"{fmt_usd(cpw)}/watcher")
    proj = projected_total(p) if kind == "live" else None
    if proj is not None:
        meta_parts.append(f"PROJ {fmt_usd(proj)}")
    meta = " · ".join(meta_parts)

    # Right column with optional 24h delta in red
    if kind == "prelaunch":
        main_value = f"{int(p.get('followers') or 0):,}"
        main_label = "WATCHING"
        delta = p.get("delta_followers")
        delta_str = (f' <span style="color:{RED};font-family:{MONO};font-size:13px;'
                     f'font-weight:700">+{int(delta):,}</span>') if delta and delta > 0 else ""
    else:
        main_value = fmt_usd(p.get("pledged_usd"))
        main_label = f"{int(p.get('backers') or 0):,} BACKERS"
        delta = p.get("delta_pledged_usd")
        delta_str = (f' <span style="color:{RED};font-family:{MONO};font-size:13px;'
                     f'font-weight:700">+{fmt_usd(delta)}</span>') if delta and delta > 0 else ""

    return f'''
    <tr>
      <td style="padding:14px 0;border-bottom:1px solid {INK};vertical-align:top">
        <a href="{url}" style="color:{INK};text-decoration:none;
                font-family:{SERIF};font-weight:700;font-size:17px;line-height:1.25;
                letter-spacing:-.005em">{star}{title}</a>
        <div style="margin-top:6px;font-family:{BODY};font-style:italic;font-size:13px;
                    color:{N700};line-height:1.5;text-align:justify">{blurb_zh}</div>
        <div style="margin-top:8px;font-family:{MONO};font-size:10.5px;color:{N500};
                    letter-spacing:.08em;text-transform:uppercase;font-weight:500">{meta}</div>
      </td>
      <td style="padding:14px 0 14px 14px;border-bottom:1px solid {INK};
                 vertical-align:top;text-align:right;white-space:nowrap;width:170px">
        <div style="font-family:{MONO};font-size:22px;font-weight:700;color:{INK};
                    letter-spacing:-.02em">{main_value}{delta_str}</div>
        <div style="margin-top:4px;font-family:{SANS};font-size:9.5px;font-weight:700;
                    color:{N500};letter-spacing:2px">{main_label}</div>
      </td>
    </tr>'''


def _kpi_cell(label: str, value: str, color: str = INK, *, last: bool = False) -> str:
    border = "" if last else f"border-right:1px solid {INK};"
    return f'''
    <td style="padding:24px 18px 20px;{border}vertical-align:top;text-align:left">
      <div style="font-family:{SERIF};font-weight:900;font-size:48px;letter-spacing:-1px;
                  line-height:1;color:{color}">{value}</div>
      <div style="margin-top:8px;font-family:{SANS};font-size:10px;font-weight:700;
                  color:{N500};letter-spacing:2.5px">{label}</div>
    </td>'''


def _signal_line(line: str) -> str:
    """Convert a CHANGELOG '- **Title** — detail' line into a newsprint bullet."""
    s = line.lstrip("- ").rstrip()
    if s.startswith("**"):
        end = s.find("**", 2)
        if end > 0:
            title = _esc(s[2:end])
            rest = _esc(s[end + 2:].lstrip(" —"))
            return (f'<li style="margin:10px 0;font-family:{BODY};font-size:14px;'
                    f'line-height:1.55;color:{INK};list-style:none;padding-left:18px;'
                    f'position:relative">'
                    f'<span style="position:absolute;left:0;color:{RED};font-weight:900">▸</span>'
                    f'<span style="font-family:{SERIF};font-weight:700">{title}</span>'
                    f' <span style="color:{N600};font-style:italic"> — {rest}</span>'
                    f'</li>')
    return (f'<li style="margin:10px 0;font-family:{BODY};font-size:14px;'
            f'line-height:1.55;color:{INK};list-style:none;padding-left:18px;'
            f'position:relative">'
            f'<span style="position:absolute;left:0;color:{RED};font-weight:900">▸</span>'
            f'{_esc(s)}</li>')


def build_html(curr: dict) -> tuple[str, str]:
    d = get_summary_data(curr)
    today = d["today"]
    counts = d["counts"]
    edition = edition_number()
    today_long = dt.datetime.now(dt.timezone.utc).strftime("%A, %B %d, %Y").upper()

    subject = (
        f"[Vol. 1, No. {edition}] {today} · "
        f"{d['total']} 项 · {counts['live']} 在筹 · "
        f"{counts['prelaunch']} 未发布"
    )

    # Drop cap on the lede paragraph (first paragraph after the masthead)
    lede_text = (
        f"今日（{today}）追踪到 <strong>{d['total']}</strong> 个中国背景消费硬件项目。"
        f"其中 <strong style=\"color:{RED}\">{counts['prelaunch']}</strong> 个 prelaunch、"
        f"<strong>{counts['live']}</strong> 个 live、"
        f"<strong>{counts['successful']}</strong> 个 successful。"
        f"在筹合计已筹 <strong>{fmt_usd(d['total_live_usd'])}</strong>，"
        f"中国背景置信度高 <strong>{d['high']}</strong> / {d['total']}，"
        f"获 KS Editor's Pick 标签 <strong>{d['pwl']}</strong> 项。"
    )

    # Top Movers: real Δ since prev snapshot, replaces the old CHANGELOG dump
    movers_pledged = top_movers_from_rows(d["prelaunch"] + d["live"], "delta_pledged_usd", 3)
    movers_followers = top_movers_from_rows(d["prelaunch"] + d["live"], "delta_followers", 3)
    movers_backers = top_movers_from_rows(d["prelaunch"] + d["live"], "delta_backers", 3)

    def _mover_line(p, *, value):
        url = _esc(p.get("url") or "#")
        title = _esc(p.get("title") or "")
        blurb = _esc(p.get("blurb_zh") or "")
        return (f'<li style="margin:8px 0;font-family:{BODY};font-size:14px;'
                f'line-height:1.55;color:{INK};list-style:none;padding-left:18px;'
                f'position:relative">'
                f'<span style="position:absolute;left:0;color:{RED};font-weight:900">▸</span>'
                f'<a href="{url}" style="color:{INK};text-decoration:none;'
                f'font-family:{SERIF};font-weight:700">{title}</a>'
                f'{(" — <i>" + blurb + "</i>") if blurb else ""}'
                f' <span style="color:{RED};font-family:{MONO};font-weight:700">{value}</span>'
                f'</li>')

    movers_html_parts = []
    if movers_pledged:
        items = "".join(
            _mover_line(p, value=f'+{fmt_usd(p.get("delta_pledged_usd"))}')
            for p in movers_pledged
        )
        movers_html_parts.append(
            f'<div style="margin-top:18px"><div style="font-family:{SANS};font-size:10px;'
            f'font-weight:700;color:{N500};letter-spacing:2.5px;margin-bottom:6px">'
            f'💰 USD GAINERS</div><ul style="margin:0;padding:0">{items}</ul></div>'
        )
    if movers_followers:
        items = "".join(
            _mover_line(p, value=f'+{int(p.get("delta_followers") or 0):,} watch')
            for p in movers_followers
        )
        movers_html_parts.append(
            f'<div style="margin-top:18px"><div style="font-family:{SANS};font-size:10px;'
            f'font-weight:700;color:{N500};letter-spacing:2.5px;margin-bottom:6px">'
            f'👀 WATCHER GAINERS</div><ul style="margin:0;padding:0">{items}</ul></div>'
        )
    if movers_backers:
        items = "".join(
            _mover_line(p, value=f'+{int(p.get("delta_backers") or 0):,} backers')
            for p in movers_backers
        )
        movers_html_parts.append(
            f'<div style="margin-top:18px"><div style="font-family:{SANS};font-size:10px;'
            f'font-weight:700;color:{N500};letter-spacing:2.5px;margin-bottom:6px">'
            f'👥 BACKER GAINERS</div><ul style="margin:0;padding:0">{items}</ul></div>'
        )

    signals_html = ""
    if movers_html_parts:
        signals_html = f'''
        <div style="margin-top:48px">
          <div style="font-family:{MONO};font-size:11px;font-weight:500;color:{N500};
                      letter-spacing:2.5px;margin-bottom:6px">SECTION A</div>
          <h2 style="margin:0 0 4px;font-family:{SERIF};font-weight:900;font-size:28px;
                     letter-spacing:-.5px;color:{INK}">Breaking · Top Movers</h2>
          <p style="margin:0 0 12px;font-family:{BODY};font-style:italic;font-size:13px;color:{N500}">
            Δ since previous snapshot · biggest jumps in pledged $, watcher count, and backer count.
          </p>
          <div style="border-top:4px solid {INK};border-bottom:1px solid {INK};padding:14px 0">
            {"".join(movers_html_parts)}
          </div>
        </div>'''

    # Top 3 of each track get FULL detail cards (KS hero image + brand line +
    # 4 Chinese highlights from data/highlights_zh.json + big metric). Each
    # card is its own <table>, so they're concatenated as block siblings —
    # no outer wrapping table (otherwise Outlook nested-table fragility).
    hl_map = _load_highlights_zh()
    pre_detail = "".join(
        _detail_card(p, kind="prelaunch", hl_map=hl_map, rank=i + 1)
        for i, p in enumerate(d["prelaunch"][:3])
    )
    live_detail = "".join(
        _detail_card(p, kind="live", hl_map=hl_map, rank=i + 1)
        for i, p in enumerate(d["live"][:3])
    )

    return subject, f'''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>{_esc(subject)}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&family=JetBrains+Mono:wght@500;700&family=Playfair+Display:ital,wght@0,700;0,900;1,700&family=Lora:ital,wght@0,400;1,400&display=swap');
</style></head>
<body style="margin:0;padding:24px 12px;background:{PAPER};
             background-image:url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='4' height='4'%3E%3Cpath fill='%23111111' fill-opacity='0.05' d='M1 3h1v1H1V3zm2-2h1v1H3V1z'/%3E%3C/svg%3E\");
             font-family:{BODY};color:{INK};line-height:1.6">

<table role="presentation" cellspacing="0" cellpadding="0" border="0"
       style="max-width:680px;margin:0 auto;background:{PAPER};
              border-left:1px solid {INK};border-right:1px solid {INK}">
  <tr>
    <td style="padding:0">

      <!-- Edition strip -->
      <div style="background:{INK};color:{PAPER};padding:10px 28px;
                  font-family:{SANS};font-size:10px;font-weight:700;
                  letter-spacing:2.5px;display:flex;justify-content:space-between;
                  align-items:center;flex-wrap:wrap;gap:8px">
        <span>
          <span style="display:inline-block;width:6px;height:6px;background:{RED};
                       margin-right:8px;vertical-align:1px"></span>
          DAILY · LIVE EDITION · {today_long}
        </span>
        <span style="font-family:{MONO};font-weight:500">VOL. 1 · NO. {edition} ·
          <a href="https://chen17-sq.github.io/kickstarter-china-tracker/editions/{today}.pdf"
             style="color:{PAPER};text-decoration:none;
             border-bottom:1px solid {RED};padding-bottom:1px;margin-left:6px">↓ PDF</a>
        </span>
      </div>

      <!-- Masthead -->
      <div style="padding:38px 28px 22px;border-bottom:4px solid {INK};text-align:center">
        <h1 style="margin:0;font-family:{SERIF};font-weight:900;
                   font-size:54px;line-height:.95;letter-spacing:-2px;color:{INK}">Kickstarter China Tracker</h1>
        <div style="margin-top:16px;border-top:1px solid {INK};border-bottom:1px solid {INK};
                    padding:6px 0;display:flex;justify-content:space-between;
                    font-family:{MONO};font-size:10.5px;font-weight:500;
                    letter-spacing:2px;text-transform:uppercase;color:{INK}">
          <span style="padding:0 4px">BEIJING EDITION</span>
          <span style="font-family:{SERIF};font-weight:400;font-style:italic;
                       letter-spacing:0;text-transform:none;font-size:13px">
            All The Crowd-Funded Hardware Fit To Print
          </span>
          <span style="padding:0 4px">PLEDGED · {fmt_usd(d['total_live_usd'])}</span>
        </div>
        <p style="margin:18px auto 0;max-width:50ch;font-family:{BODY};font-style:italic;
                  font-size:14.5px;color:{N700};line-height:1.5">
          每日追踪 Kickstarter 上中国背景的消费硬件项目 · pre-launch · live · 已结束
        </p>
      </div>

      <!-- Lede paragraph with drop cap -->
      <div style="padding:28px 28px 8px">
        <span style="float:left;font-family:{SERIF};font-weight:900;font-size:64px;
                     line-height:.85;color:{INK};margin:6px 10px 0 0">今</span>
        <p style="margin:0;font-family:{BODY};font-size:15px;line-height:1.7;
                  color:{INK};text-align:justify">{lede_text}</p>
        <div style="clear:both"></div>
      </div>

      <!-- KPI band -->
      <table role="presentation" cellspacing="0" cellpadding="0" border="0"
             style="width:100%;margin-top:24px;border-top:4px solid {INK};
                    border-bottom:4px solid {INK};border-collapse:collapse">
        <tr>
          {_kpi_cell("TRACKED", str(d['total']))}
          {_kpi_cell("PRELAUNCH", str(counts['prelaunch']), RED)}
          {_kpi_cell("LIVE", str(counts['live']))}
          {_kpi_cell("FUNDED", str(counts['successful']))}
          {_kpi_cell("EDITOR'S", f"★ {d['pwl']}", last=True)}
        </tr>
      </table>

      <div style="padding:0 28px">

        {signals_html}

        <!-- Prelaunch section -->
        <div style="margin-top:48px">
          <div style="font-family:{MONO};font-size:11px;font-weight:500;color:{N500};
                      letter-spacing:2.5px;margin-bottom:6px">SECTION B</div>
          <h2 style="margin:0 0 4px;font-family:{SERIF};font-weight:900;font-size:28px;
                     letter-spacing:-.5px;color:{INK}">⏳ Prelaunch · Top 3</h2>
          <p style="margin:0 0 4px;font-family:{BODY};font-style:italic;font-size:13px;color:{N500}">
            按关注数排序 · KS Editor's Picks 优先 · 含 4 条中文产品亮点
          </p>
          <div style="border-top:4px solid {INK}">
            {pre_detail or '<p style="padding:14px 0;color:'+N400+'">暂无</p>'}
          </div>
        </div>

        <!-- Live section -->
        <div style="margin-top:48px">
          <div style="font-family:{MONO};font-size:11px;font-weight:500;color:{N500};
                      letter-spacing:2.5px;margin-bottom:6px">SECTION C</div>
          <h2 style="margin:0 0 4px;font-family:{SERIF};font-weight:900;font-size:28px;
                     letter-spacing:-.5px;color:{INK}">🔴 Live · Top 3 by USD Raised</h2>
          <p style="margin:0 0 4px;font-family:{BODY};font-style:italic;font-size:13px;color:{N500}">
            按已筹排序 · {counts['live']} 个 live 项目中的前 3
          </p>
          <div style="border-top:4px solid {INK}">
            {live_detail or '<p style="padding:14px 0;color:'+N400+'">暂无</p>'}
          </div>
        </div>

        <!-- Ornament -->
        <div style="padding:40px 0 16px;text-align:center;
                    font-family:{SERIF};font-size:20px;color:{N400};letter-spacing:14px">
          ✦ &nbsp; ✦ &nbsp; ✦
        </div>

        <!-- Footer -->
        <div style="border-top:4px solid {INK};padding:22px 0 32px;
                    font-family:{MONO};font-size:10.5px;color:{N500};
                    letter-spacing:1.5px;text-transform:uppercase">
          <a href="{PAGES_URL}" style="color:{INK};text-decoration:none;
              border-bottom:2px solid {RED};padding-bottom:1px;font-weight:700">FULL PAPER</a>
          &nbsp;·&nbsp;
          <a href="{LATEST_URL}" style="color:{INK};text-decoration:none;
              border-bottom:2px solid {RED};padding-bottom:1px;font-weight:700">LATEST REPORT</a>
          &nbsp;·&nbsp;
          <a href="https://github.com/Chen17-sq/kickstarter-china-tracker"
             style="color:{INK};text-decoration:none;border-bottom:2px solid {RED};
             padding-bottom:1px;font-weight:700">GITHUB</a>
          <div style="margin-top:14px;font-family:{SERIF};font-style:italic;
                      font-size:13px;color:{N500};letter-spacing:0;text-transform:none">
            All the news that's fit to print, every morning at 09:00 Beijing.
          </div>
          <div style="margin-top:10px;font-size:10px">
            退订 · 在仓库 SETTINGS → SECRETS → ACTIONS 把 NOTIFY_EMAIL_TO 删掉
          </div>
        </div>

      </div>
    </td>
  </tr>
</table>

</body>
</html>'''


def post_resend(api_key: str, sender: str, to: list[str], subject: str, html: str) -> None:
    resp = httpx.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"from": sender, "to": to, "subject": subject, "html": html},
        timeout=30,
    )
    if resp.status_code >= 400:
        print(f"Resend error {resp.status_code}: {resp.text}", file=sys.stderr)
        resp.raise_for_status()


def write_archive(html: str) -> None:
    """Save today's HTML edition to site/editions/ + rebuild the index page.

    Pages URL pattern:
      https://chen17-sq.github.io/kickstarter-china-tracker/editions/
      https://chen17-sq.github.io/kickstarter-china-tracker/editions/2026-04-26.html
      https://chen17-sq.github.io/kickstarter-china-tracker/editions/latest.html
    """
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    out_dir = REPO_ROOT / "site" / "editions"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{today}.html").write_text(html, encoding="utf-8")
    (out_dir / "latest.html").write_text(html, encoding="utf-8")
    # Rebuild the directory index from disk so it always matches the file list
    _write_editions_index(out_dir)


def _write_editions_index(out_dir: Path) -> None:
    """Generate site/editions/index.html — a Newsprint-styled archive list."""
    dated = sorted(
        (f.stem for f in out_dir.glob("*.html") if f.stem not in ("latest", "index")),
        reverse=True,
    )
    rows = []
    for stem in dated:
        try:
            d = dt.datetime.strptime(stem, "%Y-%m-%d")
            label = d.strftime("%A · %B %d, %Y")
            edition = (d - dt.datetime(2026, 4, 25)).days + 1
        except ValueError:
            label = stem
            edition = "—"
        rows.append(
            f'<li style="display:flex;justify-content:space-between;align-items:baseline;'
            f'padding:14px 0;border-bottom:1px solid {INK}">'
            f'<a href="./{stem}.html" style="font-family:{SERIF};font-weight:700;'
            f'font-size:20px;color:{INK};text-decoration:none">{label}</a>'
            f'<span style="font-family:{MONO};font-size:11px;color:{N500};'
            f'letter-spacing:.18em">VOL. 1 · NO. {edition}</span>'
            f'</li>'
        )
    items = "".join(rows) or (
        f'<li style="font-family:{BODY};font-style:italic;color:{N500};'
        f'padding:24px 0">No editions archived yet — first one ships tomorrow.</li>'
    )

    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>Editions · Kickstarter China Tracker</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Playfair+Display:ital,wght@0,400;0,600;0,700;0,900;1,400;1,700&family=Lora:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;border-radius:0!important}}
body{{margin:0;padding:0;background:{PAPER};color:{INK};font-family:{BODY};font-size:15px;line-height:1.625;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='4' height='4'%3E%3Cpath fill='%23111111' fill-opacity='0.05' d='M1 3h1v1H1V3zm2-2h1v1H3V1z'/%3E%3C/svg%3E")}}
.wrap{{max-width:840px;margin:0 auto;background:{PAPER};border-left:1px solid {INK};border-right:1px solid {INK};min-height:100vh}}
.strip{{display:flex;justify-content:space-between;padding:8px 28px;background:{INK};color:{PAPER};
  font-family:{SANS};font-size:10.5px;font-weight:600;letter-spacing:.2em;text-transform:uppercase}}
.strip .dot{{display:inline-block;width:6px;height:6px;background:{RED};margin-right:8px;vertical-align:1px}}
.mast{{padding:36px 28px 22px;border-bottom:4px solid {INK};text-align:center}}
.mast h1{{margin:0;font-family:{SERIF};font-weight:900;font-size:42px;line-height:.95;
  letter-spacing:-1.2px;color:{INK}}}
.mast .tag{{display:flex;justify-content:space-between;border-top:1px solid {INK};
  border-bottom:1px solid {INK};padding:8px 0;margin-top:14px;
  font-family:{MONO};font-size:11px;letter-spacing:.18em;text-transform:uppercase;font-weight:500}}
.mast .center{{flex:1;text-align:center;font-style:italic;letter-spacing:0;
  font-family:{SERIF};font-size:13px;font-weight:400;text-transform:none}}
.section-h{{padding:28px 28px 12px;border-bottom:1px solid {INK}}}
.section-h .label{{font-family:{MONO};font-size:11px;letter-spacing:2.5px;color:{N500}}}
.section-h h2{{margin:6px 0 0;font-family:{SERIF};font-weight:900;font-size:32px;
  letter-spacing:-1px;color:{INK}}}
ul{{list-style:none;margin:0;padding:0 28px}}
.foot{{margin-top:auto;padding:24px 28px 36px;border-top:4px solid {INK};
  font-family:{MONO};font-size:10.5px;color:{N500};letter-spacing:.1em;text-transform:uppercase;text-align:center}}
.foot a{{color:{INK};text-decoration:none;border-bottom:2px solid {RED};padding-bottom:1px;font-weight:700}}
@media (max-width:680px){{
  .wrap{{border:0}}
  .mast h1{{font-size:30px}}
  .mast .tag{{flex-direction:column;gap:4px}}
}}
</style></head>
<body><div class="wrap">
<div class="strip"><span><span class="dot"></span>EDITIONS · 永久存档</span><span style="font-family:{MONO};letter-spacing:.18em">{len(dated)} ISSUES</span></div>
<header class="mast">
  <h1>Kickstarter China Tracker</h1>
  <div class="tag">
    <span style="padding:0 14px">Editions Archive</span>
    <span class="center">All The Crowd-Funded Hardware Fit To Print</span>
    <span style="padding:0 14px">{len(dated)} 期已发刊</span>
  </div>
</header>
<div class="section-h">
  <div class="label">SECTION · BACK ISSUES</div>
  <h2>过往日报 · Daily Editions</h2>
</div>
<ul>{items}</ul>
<footer class="foot">
  <a href="../">完整看板</a> &nbsp;·&nbsp;
  <a href="../subscribe.html">订阅</a> &nbsp;·&nbsp;
  <a href="../stats.html">公开数据</a> &nbsp;·&nbsp;
  <a href="https://github.com/Chen17-sq/kickstarter-china-tracker">GitHub</a>
</footer>
</div></body></html>"""
    (out_dir / "index.html").write_text(page, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Build the email, write a preview HTML, no POST.")
    args = ap.parse_args(argv)

    if not PROJECTS.exists():
        print("data/projects.json not found", file=sys.stderr)
        return 1
    curr = json.loads(PROJECTS.read_text(encoding="utf-8"))
    subject, html = build_html(curr)

    # Always archive — even on dry-run / no-API-key — so Pages always has the
    # latest visual edition viewable at /editions/<date>.html.
    write_archive(html)

    if args.dry_run:
        preview = REPO_ROOT / "data" / ".tmp" / "email_preview.html"
        preview.parent.mkdir(parents=True, exist_ok=True)
        preview.write_text(html, encoding="utf-8")
        print(f"Subject: {subject}")
        print(f"HTML: {len(html):,} chars")
        print(f"Preview: file://{preview}")
        return 0

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print("RESEND_API_KEY not set — email skipped")
        return 0

    raw_to = os.environ.get("NOTIFY_EMAIL_TO", "")
    to_owner = [e.strip() for e in raw_to.split(",") if e.strip()]

    # Subscriber broadcast: enabled by default. Set BROADCAST=0 to disable.
    # Each subscriber is sent the email separately so unsubscribe / bounce
    # tracking is per-recipient. Resend sandbox will reject unverified
    # recipients (422) — we print + continue rather than abort the run.
    broadcast = os.environ.get("BROADCAST", "1") != "0"
    sub_emails: list[str] = []
    if broadcast:
        try:
            from .subscribers import emails as load_subscriber_emails
            sub_emails = load_subscriber_emails()
        except Exception as e:
            print(f"  warn: subscribers load failed ({e}); broadcast off")
            sub_emails = []

    # Dedupe: subscribers union owner addresses.
    seen = set(e.lower() for e in to_owner)
    recipients = list(to_owner)
    for s in sub_emails:
        if s.lower() not in seen:
            recipients.append(s)
            seen.add(s.lower())

    if not recipients:
        print("No recipients (NOTIFY_EMAIL_TO empty + no subscribers) — skipping")
        return 0

    sender = (os.environ.get("NOTIFY_EMAIL_FROM") or
              "KS China Tracker <onboarding@resend.dev>")
    sent = 0
    failed = 0
    for r in recipients:
        try:
            post_resend(api_key, sender, [r], subject, html)
            sent += 1
        except Exception as e:
            # Most likely cause in sandbox mode: 422 'You can only send testing
            # emails to your own email address'. Don't fail the cron — the
            # owner email is always first in the list and almost always works.
            print(f"  ! send to {r} failed: {e}", file=sys.stderr)
            failed += 1
    print(f"Email broadcast: sent={sent}, failed={failed}, from={sender}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
