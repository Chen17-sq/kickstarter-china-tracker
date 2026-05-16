"""Weekly digest — Sunday-morning summary email.

Triggered by .github/workflows/weekly.yml every Sunday at 00:00 UTC
(= 08:00 Beijing), after that morning's daily cron has finished writing
its history snapshot.

Goes to the SAME subscriber list as the daily email. Content is
DIFFERENT from daily — covers the past 7 days rather than today:

  · KPI line: 本周新增 / 状态跃迁 / 累计 USD
  · 本周新发现 (new in discovery this week — first-seen path tracking)
  · 本周新上线 (status: prelaunch → live transitions this week)
  · 本周筹款成功 (live → successful transitions this week)
  · 本周涨幅榜 · followers (top 5 by weekly_delta_followers)
  · 本周筹款榜 · USD (top 5 by weekly_delta_pledged_usd)
  · 本周持续热度 · Sleeper (sleeper picks seen in 3+ history files)
  · 本周新候选品牌 (brand_candidates that appeared ≥2 days this week)

Mirrors the daily edition's newsprint aesthetic but with a "weekly"
masthead variation (different volume indicator: "WEEK 21 · MAY 11–17").

The owner can choose to skip a week by deleting that Sunday's history
file before the cron fires — but normally just let it run.

Archived at site/weekly/<week-ending-date>.html (parallel to
site/editions/<date>.html for daily). Indexed in the sitemap.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

from ._common import fmt_int, fmt_usd

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECTS = REPO_ROOT / "data" / "projects.json"
HISTORY = REPO_ROOT / "data" / "history"
WEEKLY_DIR = REPO_ROOT / "site" / "weekly"
HIGHLIGHTS_FILE = REPO_ROOT / "data" / "highlights_zh.json"

RESEND_API_URL = "https://api.resend.com/emails"

# Match the daily edition's design tokens
PAPER = "#F9F9F7"
INK = "#111111"
RED = "#CC0000"
MUTED = "#E5E5E0"
N400 = "#A3A3A3"
N500 = "#737373"
N700 = "#404040"
SERIF = "'Playfair Display', Georgia, serif"
SANS = "'Inter', system-ui, sans-serif"
MONO = "'JetBrains Mono', ui-monospace, monospace"
BODY = "Lora, Georgia, serif"


def _load_highlights_zh() -> dict[str, list[str]]:
    """Same source as the daily — curated 4-bullet Chinese highlights
    keyed by KS pathname. Returns {} if file missing."""
    if not HIGHLIGHTS_FILE.exists():
        return {}
    try:
        return json.loads(HIGHLIGHTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _esc(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _num(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _load_snapshots_for_week() -> list[tuple[dt.datetime, dict]]:
    """Load the snapshots that fall within the past 7 days.

    Returns (timestamp, snapshot) tuples sorted oldest-first. Missing
    days (cron skipped) just mean fewer tuples in the list — we don't
    synthesize anything.
    """
    if not HISTORY.exists():
        return []
    now = dt.datetime.now(dt.UTC)
    cutoff = now - dt.timedelta(days=8)  # 7-day window + 1d slack
    out: list[tuple[dt.datetime, dict]] = []
    for p in sorted(HISTORY.glob("*.json")):
        try:
            ts = dt.datetime.strptime(p.stem, "%Y-%m-%dT%H-%M-%SZ").replace(
                tzinfo=dt.UTC
            )
        except ValueError:
            continue
        if ts < cutoff:
            continue
        try:
            out.append((ts, json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return out


def compute_weekly_stats(week: list[tuple[dt.datetime, dict]]) -> dict:
    """Crunch the week's snapshots into a structured digest payload.

    Comparison anchor: the OLDEST snapshot in `week` is "start of week",
    NEWEST is "today". Status transitions are computed by comparing the
    same pathname's status at both ends.
    """
    out: dict[str, Any] = {
        "today": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d"),
        "week_start": None,
        "week_end": None,
        "days_in_window": len(week),
        "new_in_discovery": [],     # pathnames seen for first time this week
        "newly_live": [],           # prelaunch → live transitions
        "newly_successful": [],     # live → successful transitions
        "newly_failed": [],         # live → failed transitions
        "top_follower_gainers": [], # by weekly_delta_followers
        "top_usd_gainers": [],      # by weekly_delta_pledged_usd
        "sleeper_streaks": [],      # projects appearing in sleeper N+ times
        "brand_candidates": [],     # high-signal unknowns seen this week
        "total_live_usd_change": 0.0,
        "kpi": {
            "total_now": 0,
            "total_week_start": 0,
        },
    }
    if not week:
        return out

    oldest_ts, oldest = week[0]
    newest_ts, newest = week[-1]
    out["week_start"] = oldest_ts.strftime("%Y-%m-%d")
    out["week_end"] = newest_ts.strftime("%Y-%m-%d")

    oldest_by_path = {
        p.get("pathname"): p
        for p in (oldest.get("projects") or [])
        if p.get("pathname")
    }
    newest_by_path = {
        p.get("pathname"): p
        for p in (newest.get("projects") or [])
        if p.get("pathname")
    }

    out["kpi"]["total_now"] = len(newest_by_path)
    out["kpi"]["total_week_start"] = len(oldest_by_path)

    # ── New in discovery: pathname in newest but not in oldest, AND
    #    not in any intermediate snapshot before it appeared.
    # We carry the FULL project dict through (with image_url, blurb_zh,
    # brand, country, etc.) so the email renderer can build rich detail
    # cards instead of bare title rows. Prefer the freshest (newest)
    # version of each project's data — newest has up-to-date follower
    # counts, vs the version at first-discovery which may be 0.
    ever_seen: set[str] = set(oldest_by_path.keys())
    for ts, snap in week[1:]:
        snap_paths = {p.get("pathname") for p in (snap.get("projects") or []) if p.get("pathname")}
        new_today = snap_paths - ever_seen
        for path in new_today:
            # Pull the FRESHEST data for this project (from newest snapshot
            # if it's still there, else from first-discovery snapshot).
            fresh = newest_by_path.get(path) or next(
                (p for p in snap.get("projects") or [] if p.get("pathname") == path),
                None,
            )
            if fresh:
                # Shallow copy + add first_seen metadata so renderer can
                # decorate without mutating the snapshot data
                row = dict(fresh)
                row["first_seen"] = ts.strftime("%Y-%m-%d")
                out["new_in_discovery"].append(row)
        ever_seen |= snap_paths

    # Sort new discoveries by followers desc (then PWL first)
    out["new_in_discovery"].sort(
        key=lambda x: (
            0 if x.get("project_we_love") else 1,
            -(int(x.get("followers") or 0)),
        ),
    )

    # ── Status transitions: compare oldest vs newest only.
    # Carry the full project dict (image, blurb, brand, etc.) so renderer
    # can build detail cards. Tag with `_from` / `_to` so the renderer
    # knows which transition this represents.
    for path, new in newest_by_path.items():
        old = oldest_by_path.get(path)
        if not old:
            continue
        old_status = old.get("status")
        new_status = new.get("status")
        if old_status == new_status:
            continue
        record = dict(new)
        record["_from"] = old_status
        record["_to"] = new_status
        # Coerce pledged_usd to float (KS API sometimes returns string)
        record["pledged_usd"] = _num(new.get("pledged_usd"))
        if old_status == "prelaunch" and new_status == "live":
            out["newly_live"].append(record)
        elif new_status == "successful":
            out["newly_successful"].append(record)
        elif new_status == "failed":
            out["newly_failed"].append(record)

    # Sort newly_live by followers (the prelaunch signal that mattered
    # before they launched), newly_successful by USD raised.
    out["newly_live"].sort(key=lambda x: -(int(x.get("followers") or 0)))
    out["newly_successful"].sort(key=lambda x: -_num(x.get("pledged_usd")))

    # ── Top gainers: weekly Δ in followers / pledged_usd vs start of
    # window. Carry full project dict so renderer can show image/blurb.
    f_gainers: list[dict] = []
    u_gainers: list[dict] = []
    for path, new in newest_by_path.items():
        old = oldest_by_path.get(path)
        if not old:
            continue
        try:
            df = int(new.get("followers") or 0) - int(old.get("followers") or 0)
        except (TypeError, ValueError):
            df = 0
        try:
            du = _num(new.get("pledged_usd")) - _num(old.get("pledged_usd"))
        except (TypeError, ValueError):
            du = 0.0
        if df > 0:
            row = dict(new)
            row["delta_followers"] = df
            f_gainers.append(row)
        if du > 1.0:
            row = dict(new)
            row["delta_pledged_usd"] = du
            row["pledged_usd"] = _num(new.get("pledged_usd"))
            u_gainers.append(row)
    f_gainers.sort(key=lambda x: -x["delta_followers"])
    u_gainers.sort(key=lambda x: -x["delta_pledged_usd"])
    out["top_follower_gainers"] = f_gainers[:5]
    out["top_usd_gainers"] = u_gainers[:5]

    # Aggregate live USD growth (sum of positive deltas on live projects)
    for path, new in newest_by_path.items():
        if new.get("status") != "live":
            continue
        old = oldest_by_path.get(path)
        if not old:
            continue
        try:
            du = _num(new.get("pledged_usd")) - _num(old.get("pledged_usd"))
            if du > 0:
                out["total_live_usd_change"] += du
        except (TypeError, ValueError):
            pass

    return out


def build_html(stats: dict) -> tuple[str, str]:
    """Render the weekly digest HTML. Returns (subject, html)."""
    week_label = (
        f"{stats.get('week_start', '?')} – {stats.get('week_end', '?')}"
    )
    week_no = (
        dt.datetime.strptime(stats["week_end"], "%Y-%m-%d").isocalendar()[1]
        if stats.get("week_end")
        else "?"
    )
    subject = (
        f"[Week {week_no}] {week_label} · "
        f"+{len(stats.get('new_in_discovery', []))} new · "
        f"+{len(stats.get('newly_live', []))} live · "
        f"+{len(stats.get('newly_successful', []))} 成功"
    )

    hl_map = _load_highlights_zh()

    def _detail_card(
        p: dict, *, rank: int, big_value: str, big_label: str,
        big_color: str = INK, subtitle: str = "",
    ) -> str:
        """Image + brand line + Chinese highlights + big metric.
        Mirrors the daily edition's `_detail_card` so weekly reads like
        a "longer-window edition" rather than a plaintext changelog.
        """
        image_url = p.get("image_url") or ""
        title = _esc((p.get("title") or "(untitled)")[:80])
        blurb_zh = _esc(p.get("blurb_zh") or "")
        url = _esc(p.get("url") or "#")
        brand = _esc(
            p.get("matched_brand_zh") or p.get("matched_brand")
            or p.get("creator_name") or ""
        )
        country = _esc(p.get("country") or "")
        star = (
            f'<span style="display:inline-block;background:{RED};color:{PAPER};'
            f'font-family:{SANS};font-size:9px;font-weight:700;letter-spacing:.2em;'
            f'text-transform:uppercase;padding:2px 6px;margin-right:6px;'
            f'vertical-align:2px">✦ KS PICK</span>'
        ) if p.get("project_we_love") else ""

        # Curated 4-bullet highlights from data/highlights_zh.json keyed by
        # pathname — same source the daily edition uses.
        highlights = hl_map.get(p.get("pathname")) or []
        if not highlights and p.get("blurb"):
            highlights = [s.strip() for s in p["blurb"].split("|") if s.strip()][:4]
        bullets = "".join(
            f"""<li style="margin:6px 0;font-family:{BODY};font-size:13.5px;
                line-height:1.5;color:{INK};list-style:none;padding-left:18px;
                position:relative">
              <span style="position:absolute;left:0;color:{RED};font-weight:900">▸</span>
              {_esc(h)}</li>"""
            for h in highlights[:4]
        )

        img_block = (
            f'<img src="{image_url}" width="240" height="180" '
            f'style="display:block;width:240px;height:180px;object-fit:contain;'
            f'background:{PAPER};border:1px solid {INK}" alt=""/>'
            if image_url else
            f'<div style="width:240px;height:180px;background:{MUTED};'
            f'border:1px solid {INK}"></div>'
        )

        subtitle_chip = (
            f'<div style="font-family:{MONO};font-size:10px;font-weight:700;'
            f'letter-spacing:.15em;color:{N500};text-transform:uppercase;'
            f'margin-bottom:6px">{subtitle}</div>'
            if subtitle else ""
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
                {star}{brand}{' · ' + country if brand and country else country}</div>
              {subtitle_chip}
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
                      font-weight:700;letter-spacing:.2em;color:{N500};
                      text-transform:uppercase">{big_label}</span>
              </div>
            </td>
          </tr>
        </table>'''

    def _short_blurb(p: dict, *, max_chars: int = 90) -> str:
        """One-line description, in fallback order:
            blurb_zh (curated 中文, ~40% coverage)
          → blurb (English from KS Discover, always present)
          → title's tail after ':' / '—' (e.g. "PenN — Minimal by design")
          → empty string
        Truncated to max_chars with ellipsis on overflow.
        """
        for cand in (p.get("blurb_zh"), p.get("blurb")):
            if cand and cand.strip():
                s = cand.strip().replace("\n", " ")
                if len(s) > max_chars:
                    s = s[: max_chars - 1].rstrip() + "…"
                return s
        # Title-tail fallback: take the part after the first separator
        title = (p.get("title") or "").strip()
        for sep in (":", "—", "–", "-", "·"):
            if sep in title:
                tail = title.split(sep, 1)[1].strip()
                if tail:
                    if len(tail) > max_chars:
                        tail = tail[: max_chars - 1].rstrip() + "…"
                    return tail
        return ""

    def _compact_row(p: dict, *, rank: int, right_label: str, right_value: str) -> str:
        """Compact text row for rank 4+ items — no image, just title +
        description (Chinese-preferred, English-fallback) + metric."""
        # Trim title to keep the row a single visual line on most clients
        title_full = (p.get("title") or "?").strip()
        # If title has a colon/dash, the head is usually the product name and
        # the tail is the descriptor we'll show as blurb. Keep the head only.
        title = title_full
        for sep in (":", "—", "–"):
            if sep in title_full:
                title = title_full.split(sep, 1)[0].strip()
                break
        title = _esc(title[:60])
        blurb = _esc(_short_blurb(p, max_chars=85))
        star = (f'<span style="color:{RED};margin-right:5px">✦</span>'
                if p.get("project_we_love") else "")
        url = _esc(p.get("url") or "#")
        return f"""
        <tr><td style="padding:13px 0;border-bottom:1px solid {MUTED}">
          <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="width:100%">
            <tr>
              <td style="width:40px;vertical-align:top;font-family:{SERIF};
                  font-size:22px;font-weight:900;color:{N400};line-height:1;
                  letter-spacing:-.5px">{rank:02d}</td>
              <td style="vertical-align:top">
                <a href="{url}" style="text-decoration:none;color:{INK};
                   font-family:{SERIF};font-size:16px;font-weight:700;line-height:1.25">{star}{title}</a>
                <div style="font-family:{BODY};font-style:italic;font-size:12.5px;
                     color:{N700};line-height:1.45;margin-top:3px">{blurb}</div>
              </td>
              <td style="text-align:right;vertical-align:top;font-family:{MONO};
                  font-size:14px;font-weight:700;color:{RED};white-space:nowrap;padding-left:12px">
                {right_value}
                <div style="font-family:{SANS};font-size:9px;color:{N500};
                     letter-spacing:.15em;margin-top:2px;text-transform:uppercase">{right_label}</div>
              </td>
            </tr>
          </table>
        </td></tr>"""

    def _section(title_en: str, title_zh: str, dek: str, body_html: str) -> str:
        """Section wrapper — only renders if there's a body."""
        if not body_html.strip():
            return ""
        return f"""
        <div style="margin-top:48px">
          <div style="font-family:{MONO};font-size:10px;font-weight:700;
               letter-spacing:.22em;color:{RED};text-transform:uppercase;
               margin-bottom:4px">{title_en}</div>
          <h2 style="font-family:{SERIF};font-weight:900;font-size:36px;
              color:{INK};line-height:1;margin:0 0 6px;letter-spacing:-.8px">{title_zh}</h2>
          <div style="font-family:{BODY};font-style:italic;font-size:13px;
               color:{N700};margin-bottom:14px">{_esc(dek)}</div>
          {body_html}
        </div>"""

    def _build_mixed_section(
        items: list[dict],
        *,
        n_detail: int = 3,
        n_compact: int = 5,
        big_value_fn=None,
        big_label_fn=None,
        right_value_fn=None,
        right_label_fn=None,
        subtitle_fn=None,
    ) -> str:
        """Top N as detail cards + next M as compact rows + table wrapper.
        Empty → returns empty string so the section vanishes."""
        if not items:
            return ""
        detail_items = items[:n_detail]
        compact_items = items[n_detail:n_detail + n_compact]
        detail_html = "".join(
            _detail_card(
                p, rank=i + 1,
                big_value=big_value_fn(p) if big_value_fn else "",
                big_label=big_label_fn(p) if big_label_fn else "",
                subtitle=subtitle_fn(p) if subtitle_fn else "",
            )
            for i, p in enumerate(detail_items)
        )
        compact_html = ""
        if compact_items:
            rows = "".join(
                _compact_row(
                    p, rank=n_detail + i + 1,
                    right_value=right_value_fn(p) if right_value_fn else "",
                    right_label=right_label_fn(p) if right_label_fn else "",
                )
                for i, p in enumerate(compact_items)
            )
            compact_html = f"""
            <table role="presentation" cellspacing="0" cellpadding="0" border="0"
                   style="width:100%;margin-top:18px;border-top:2px solid {INK};
                          border-collapse:collapse">
              <tbody>{rows}</tbody>
            </table>"""
        return detail_html + compact_html

    # Section layout: Top 3 as full detail cards (image + bullets + big metric)
    # then ranks 4-10 as compact rows (title + 1-line description + metric).
    # Beyond top 10 is truncated — weekly is a digest, not the archive.
    #
    # ── Section 1: New in discovery
    new_html = _build_mixed_section(
        stats.get("new_in_discovery", []),
        n_detail=3, n_compact=7,
        big_value_fn=lambda p: fmt_int(p.get("followers") or 0),
        big_label_fn=lambda _p: "WATCHERS · 关注",
        right_value_fn=lambda p: f"{fmt_int(p.get('followers') or 0)} 关注",
        right_label_fn=lambda p: f"首见 {p.get('first_seen','?')}",
        subtitle_fn=lambda p: f"首见 {p.get('first_seen','?')} · {p.get('status','?')}",
    )
    # ── Section 2: Newly live
    live_html = _build_mixed_section(
        stats.get("newly_live", []),
        n_detail=3, n_compact=7,
        big_value_fn=lambda p: fmt_usd(p.get("pledged_usd") or 0),
        big_label_fn=lambda p: f"{fmt_int(p.get('backers') or 0)} BACKERS",
        right_value_fn=lambda p: fmt_usd(p.get("pledged_usd") or 0),
        right_label_fn=lambda p: f"{fmt_int(p.get('backers') or 0)} backers",
        subtitle_fn=lambda _p: "PRELAUNCH → LIVE",
    )
    # ── Section 3: Newly successful
    success_html = _build_mixed_section(
        stats.get("newly_successful", []),
        n_detail=3, n_compact=7,
        big_value_fn=lambda p: fmt_usd(p.get("pledged_usd") or 0),
        big_label_fn=lambda p: f"{fmt_int(p.get('backers') or 0)} BACKERS",
        right_value_fn=lambda p: fmt_usd(p.get("pledged_usd") or 0),
        right_label_fn=lambda p: f"{fmt_int(p.get('backers') or 0)} backers",
        subtitle_fn=lambda _p: "FUNDED ✓",
    )
    # ── Section 4: Top follower gainers (capped at 5 in compute_weekly_stats)
    f_html = _build_mixed_section(
        stats.get("top_follower_gainers", []),
        n_detail=3, n_compact=2,
        big_value_fn=lambda p: f"+{fmt_int(p.get('delta_followers'))}",
        big_label_fn=lambda p: f"周净增 · NOW {fmt_int(p.get('followers') or 0)}",
        right_value_fn=lambda p: f"+{fmt_int(p.get('delta_followers'))}",
        right_label_fn=lambda p: f"now {fmt_int(p.get('followers') or 0)}",
        subtitle_fn=lambda _p: "TOP FOLLOWER GAINER",
    )
    # ── Section 5: Top USD gainers
    u_html = _build_mixed_section(
        stats.get("top_usd_gainers", []),
        n_detail=3, n_compact=2,
        big_value_fn=lambda p: f"+{fmt_usd(p.get('delta_pledged_usd') or 0)}",
        big_label_fn=lambda p: f"周净增 · NOW {fmt_usd(p.get('pledged_usd') or 0)}",
        right_value_fn=lambda p: f"+{fmt_usd(p.get('delta_pledged_usd') or 0)}",
        right_label_fn=lambda p: f"now {fmt_usd(p.get('pledged_usd') or 0)}",
        subtitle_fn=lambda _p: "TOP USD GAINER",
    )

    kpi = stats.get("kpi") or {}
    growth = kpi.get("total_now", 0) - kpi.get("total_week_start", 0)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{_esc(subject)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{_esc(subject)} — Kickstarter China Tracker 周报.">
<link rel="canonical" href="https://ks.aldrich.fyi/weekly/{stats.get('week_end','latest')}.html">
<link rel="alternate" type="application/atom+xml" title="Atom feed" href="https://ks.aldrich.fyi/feed.xml">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&family=JetBrains+Mono:wght@500;700&family=Playfair+Display:ital,wght@0,700;0,900;1,700&family=Lora:ital,wght@0,400;1,400&display=swap');
</style></head>
<body style="margin:0;padding:24px 12px;background:{PAPER};
             background-image:url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='4' height='4'%3E%3Cpath fill='%23111111' fill-opacity='0.05' d='M1 3h1v1H1V3zm2-2h1v1H3V1z'/%3E%3C/svg%3E\");
             font-family:{BODY};color:{INK};line-height:1.6">

<!-- Preheader -->
<div style="display:none;max-height:0;overflow:hidden;font-size:1px;line-height:1px;color:transparent;opacity:0">
Week {week_no} · {week_label} · {len(stats.get('new_in_discovery', []))} new projects discovered · {len(stats.get('newly_successful', []))} funded
&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;
</div>

<table role="presentation" cellspacing="0" cellpadding="0" border="0"
       style="max-width:680px;margin:0 auto;background:{PAPER};
              border-left:1px solid {INK};border-right:1px solid {INK}">
  <tr><td style="padding:0">

    <!-- Edition strip -->
    <div style="background:{INK};color:{PAPER};padding:10px 28px;
                font-family:{SANS};font-size:10px;font-weight:700;
                letter-spacing:2.5px;display:flex;justify-content:space-between;
                align-items:center;flex-wrap:wrap;gap:8px">
      <span><span style="display:inline-block;width:6px;height:6px;background:{RED};border-radius:50%;margin-right:8px;vertical-align:1px"></span>WEEKLY · BEIJING EDITION</span>
      <span>WEEK {week_no} · {week_label}</span>
    </div>

    <!-- Masthead -->
    <div style="padding:32px 28px 16px;text-align:center;border-bottom:4px double {INK}">
      <div style="font-family:{MONO};font-size:11px;letter-spacing:.22em;color:{RED};font-weight:700;text-transform:uppercase">本周精选 · This Week in Review</div>
      <h1 style="font-family:{SERIF};font-weight:900;font-size:48px;letter-spacing:-1.5px;line-height:1;margin:8px 0 0;color:{INK}">Weekly · 周报</h1>
      <div style="font-family:{BODY};font-style:italic;font-size:14px;color:{N700};margin-top:8px">
        过去 7 天 · {kpi.get('total_now', 0)} 项追踪
        ({'+' if growth >= 0 else ''}{growth} 项变化) ·
        在筹累计净增 {fmt_usd(stats.get('total_live_usd_change', 0))}
      </div>
    </div>

    <!-- Body -->
    <div style="padding:8px 28px 28px">

      {_section(
        "★ NEW IN DISCOVERY · 本周新发现",
        "本周新发现",
        f"过去 7 天首次出现在追踪列表里的 {len(stats.get('new_in_discovery', []))} 个项目（按 watchers 排序）",
        new_html,
      )}

      {_section(
        "🔴 NEWLY LIVE · 本周新上线",
        "本周新上线",
        f"prelaunch → live · {len(stats.get('newly_live', []))} 项过去 7 天进入筹款期",
        live_html,
      )}

      {_section(
        "✅ NEWLY FUNDED · 本周筹款成功",
        "本周筹款成功",
        f"{len(stats.get('newly_successful', []))} 项 live → successful · 已达目标金额",
        success_html,
      )}

      {_section(
        "📈 TOP FOLLOWER GAINERS · 本周关注涨幅榜",
        "本周关注涨幅",
        "按本周 watchers 净增排序 · prelaunch 项目最相关",
        f_html,
      )}

      {_section(
        "💰 TOP USD GAINERS · 本周筹款涨幅榜",
        "本周筹款涨幅",
        "按本周已筹 USD 净增排序",
        u_html,
      )}

    </div>

    <!-- CTA + footer -->
    <div style="background:{INK};color:{PAPER};padding:24px 28px;text-align:center">
      <div style="font-family:{SERIF};font-size:18px;font-style:italic;margin-bottom:10px">
        想看每天的版本？
      </div>
      <a href="https://ks.aldrich.fyi/editions/latest.html"
         style="display:inline-block;padding:12px 24px;background:{RED};
                color:{PAPER};text-decoration:none;font-family:{SANS};
                font-size:13px;font-weight:700;letter-spacing:.18em;
                text-transform:uppercase">阅读今日日报 →</a>
      <div style="margin-top:16px;font-family:{MONO};font-size:10px;letter-spacing:.15em;color:#A3A3A3">
        Atom feed: ks.aldrich.fyi/feed.xml · JSON API: ks.aldrich.fyi/api/today.json
      </div>
    </div>

  </td></tr>
</table>

</body>
</html>"""

    return subject, html


def build_plaintext(stats: dict) -> str:
    """Plaintext alt for multipart messages."""
    week_label = f"{stats.get('week_start','?')} – {stats.get('week_end','?')}"
    week_no = (
        dt.datetime.strptime(stats["week_end"], "%Y-%m-%d").isocalendar()[1]
        if stats.get("week_end")
        else "?"
    )
    rule = "─" * 60
    lines = [
        "KICKSTARTER CHINA TRACKER · 周报",
        f"Week {week_no} · {week_label}",
        "",
        rule,
        f"过去 7 天 · {stats.get('kpi',{}).get('total_now',0)} 项追踪 · "
        f"{len(stats.get('new_in_discovery',[]))} 新发现 · "
        f"{len(stats.get('newly_live',[]))} 新上线 · "
        f"{len(stats.get('newly_successful',[]))} 筹款成功 · "
        f"在筹净增 {fmt_usd(stats.get('total_live_usd_change',0))}",
        rule,
        "",
    ]

    def _list(header: str, items: list[dict], get_right):
        if not items:
            return
        lines.append(header)
        lines.append("")
        for i, p in enumerate(items[:10], 1):
            title = (p.get("title") or "?")[:55]
            lines.append(f"{i:2d}. {title}  {get_right(p)}")
            if p.get("blurb_zh"):
                lines.append(f"     {p['blurb_zh'][:55]}")
            if p.get("url"):
                lines.append(f"     {p['url']}")
            lines.append("")

    _list("★ NEW IN DISCOVERY · 本周新发现",
          stats.get("new_in_discovery", []),
          lambda p: f"{fmt_int(p.get('followers') or 0)} watchers (first seen {p.get('first_seen','?')})")
    _list("🔴 NEWLY LIVE · 本周新上线",
          stats.get("newly_live", []),
          lambda p: f"{fmt_usd(p.get('pledged_usd') or 0)} · {fmt_int(p.get('backers') or 0)} backers")
    _list("✅ NEWLY FUNDED · 本周筹款成功",
          stats.get("newly_successful", []),
          lambda p: f"{fmt_usd(p.get('pledged_usd') or 0)} · {fmt_int(p.get('backers') or 0)} backers")
    _list("📈 TOP FOLLOWER GAINERS · 本周关注涨幅榜",
          stats.get("top_follower_gainers", []),
          lambda p: f"+{fmt_int(p.get('delta_followers'))} this week (now {fmt_int(p.get('followers') or 0)})")
    _list("💰 TOP USD GAINERS · 本周筹款涨幅榜",
          stats.get("top_usd_gainers", []),
          lambda p: f"+{fmt_usd(p.get('delta_pledged_usd') or 0)} this week (now {fmt_usd(p.get('pledged_usd') or 0)})")

    lines.append(rule)
    lines.append("VIEW VISUAL · https://ks.aldrich.fyi/weekly/latest.html")
    lines.append("DAILY EDITIONS · https://ks.aldrich.fyi/editions/latest.html")
    lines.append("RSS FEED · https://ks.aldrich.fyi/feed.xml")
    lines.append("")
    lines.append("Reply 'unsubscribe' to stop receiving these.")
    return "\n".join(lines)


def write_archive(html: str, stats: dict) -> Path:
    """Archive the weekly digest at site/weekly/<week-end>.html + latest.html.

    Also refreshes site/weekly/index.html — a simple listing of every
    weekly digest ever produced, so visitors landing on /weekly/ get a
    table of contents instead of a 404.
    """
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    week_end = stats.get("week_end") or dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    archive_path = WEEKLY_DIR / f"{week_end}.html"
    archive_path.write_text(html, encoding="utf-8")
    (WEEKLY_DIR / "latest.html").write_text(html, encoding="utf-8")
    _write_weekly_index()
    return archive_path


def _write_weekly_index() -> Path:
    """Build site/weekly/index.html — chronological list of past weeklies.

    Light Newsprint styling, mirrors site/editions/index.html (built by
    email_notify._write_editions_index).
    """
    weeks: list[tuple[str, dt.datetime]] = []
    for f in sorted(WEEKLY_DIR.glob("*.html"), reverse=True):
        stem = f.stem
        if stem in ("latest", "index"):
            continue
        try:
            d = dt.datetime.strptime(stem, "%Y-%m-%d")
            weeks.append((stem, d))
        except ValueError:
            continue

    rows_html = "\n".join(
        f'<li style="margin:8px 0"><a href="{stem}.html" '
        f'style="color:{INK};text-decoration:none;font-family:{SERIF};font-weight:700">'
        f'Week of {stem}</a> '
        f'<span style="font-family:{MONO};font-size:11px;color:{N400};letter-spacing:.05em">'
        f'· week {d.isocalendar()[1]}</span></li>'
        for stem, d in weeks
    ) or '<li style="font-style:italic;color:#737373">No weekly digests yet — first one ships Sunday morning.</li>'

    body = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Weekly Archive · Kickstarter China Tracker</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="All past weekly digests of the Kickstarter China Tracker.">
<link rel="alternate" type="application/atom+xml" title="Atom feed" href="https://ks.aldrich.fyi/feed.xml">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&family=JetBrains+Mono:wght@500;700&family=Playfair+Display:ital,wght@0,700;0,900&family=Lora:ital,wght@0,400;1,400&display=swap');
</style>
</head>
<body style="margin:0;padding:24px;background:{PAPER};font-family:{BODY};color:{INK};line-height:1.6">
  <div style="max-width:680px;margin:0 auto">
    <div style="font-family:{MONO};font-size:11px;font-weight:700;letter-spacing:.22em;color:{RED};text-transform:uppercase;margin-bottom:4px">
      ✦ WEEKLY ARCHIVE
    </div>
    <h1 style="font-family:{SERIF};font-weight:900;font-size:48px;letter-spacing:-1.5px;line-height:1;margin:0;color:{INK}">
      周报存档
    </h1>
    <div style="font-family:{BODY};font-style:italic;color:{N700};font-size:14px;margin-top:8px">
      每周日早上 8 点北京时间，一份过去 7 天的精华回顾。
    </div>
    <hr style="border:none;border-top:4px double {INK};margin:24px 0">
    <ul style="list-style:none;padding:0;margin:0">{rows_html}</ul>
    <hr style="border:none;border-top:1px solid {N400};margin:36px 0 12px">
    <div style="font-family:{MONO};font-size:11px;color:{N400};letter-spacing:.05em">
      <a href="/" style="color:{N700};text-decoration:none">完整看板</a> ·
      <a href="/editions/" style="color:{N700};text-decoration:none">每日存档</a> ·
      <a href="/feed.xml" style="color:{N700};text-decoration:none">Atom feed</a> ·
      <a href="/api/today.json" style="color:{N700};text-decoration:none">JSON API</a>
    </div>
  </div>
</body>
</html>"""

    index_path = WEEKLY_DIR / "index.html"
    index_path.write_text(body, encoding="utf-8")
    return index_path


def post_resend(api_key: str, sender: str, to: list[str], subject: str,
                html: str, text: str | None = None) -> None:
    payload = {"from": sender, "to": to, "subject": subject, "html": html}
    if text:
        payload["text"] = text
    resp = httpx.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 400:
        print(f"Resend error {resp.status_code}: {resp.text}", file=sys.stderr)
        resp.raise_for_status()


def main(argv: list[str] | None = None) -> int:
    """Build + send the weekly digest. --dry-run prints to disk only."""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Build digest + archive to disk; no email send.")
    args = ap.parse_args(argv)

    week = _load_snapshots_for_week()
    if len(week) < 2:
        print(
            f"weekly: only {len(week)} snapshot(s) in past 7 days — "
            "need at least 2 to compute deltas. Skipping send.",
            file=sys.stderr,
        )
        return 0

    stats = compute_weekly_stats(week)
    subject, html = build_html(stats)
    text = build_plaintext(stats)

    archive_path = write_archive(html, stats)
    print(f"  archived → {archive_path.relative_to(REPO_ROOT)}")

    if args.dry_run:
        preview = REPO_ROOT / "data" / ".tmp" / "weekly_preview.html"
        preview.parent.mkdir(parents=True, exist_ok=True)
        preview.write_text(html, encoding="utf-8")
        print(f"Subject: {subject}")
        print(f"HTML: {len(html):,} chars · plaintext: {len(text):,} chars")
        print(f"Preview: file://{preview}")
        return 0

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print("RESEND_API_KEY not set — weekly digest archived but not sent.")
        return 0

    raw_to = os.environ.get("NOTIFY_EMAIL_TO", "")
    to_owner = [e.strip() for e in raw_to.split(",") if e.strip()]
    broadcast = os.environ.get("BROADCAST", "1") != "0"

    sub_emails: list[str] = []
    if broadcast:
        try:
            from .subscribers import emails as load_subscriber_emails
            sub_emails = load_subscriber_emails()
        except Exception as e:
            print(f"  warn: subscribers load failed ({e}); broadcast off")
            sub_emails = []

    # Dedupe: owner addresses first, then subscribers
    seen = set(e.lower() for e in to_owner)
    recipients = list(to_owner)
    for s in sub_emails:
        if s.lower() not in seen:
            recipients.append(s)
            seen.add(s.lower())

    if not recipients:
        print("No recipients — weekly digest archived but not sent.")
        return 0

    sender = os.environ.get("NOTIFY_EMAIL_FROM") or "KS China Tracker <onboarding@resend.dev>"
    sent = 0
    failed = 0
    for r in recipients:
        try:
            post_resend(api_key, sender, [r], subject, html, text=text)
            sent += 1
        except Exception as e:
            print(f"  ! send to {r} failed: {e}", file=sys.stderr)
            failed += 1
    print(f"Weekly broadcast: sent={sent}, failed={failed}, from={sender}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
