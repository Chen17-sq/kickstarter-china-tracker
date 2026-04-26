"""Send a daily HTML-email summary via Resend.

Drives off two env vars (set as repo secrets):
  - RESEND_API_KEY     — get one at https://resend.com (free tier 3000/mo)
  - NOTIFY_EMAIL_TO    — recipient address(es), comma-separated

Optional:
  - NOTIFY_EMAIL_FROM  — default 'KS Tracker <onboarding@resend.dev>'.
                         Resend's sandbox sender works only to addresses
                         verified in the Resend dashboard. To send to
                         arbitrary addresses, verify your own domain at
                         https://resend.com/domains and set this to
                         'KS Tracker <reports@yourdomain.com>'.

Style aligned with the Pages site (Editorial / Swiss): Inter typography,
warm off-white background, near-black ink, single restrained accent red,
hairline rules, tabular numerals.

Run locally:
  python -m scraper.email_notify --dry-run    # writes preview to data/.tmp/
  python -m scraper.email_notify              # POST to Resend
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

import httpx

from .notify import (
    get_summary_data, fmt_usd, fmt_int,
    PAGES_URL, LATEST_URL, REPO_ROOT, PROJECTS,
)

RESEND_API_URL = "https://api.resend.com/emails"


def _row_html(p: dict, *, kind: str) -> str:
    """Render one project row as a table row.
    kind ∈ {'prelaunch', 'live'} — controls which numeric columns to show.
    """
    star = '<span style="color:#c8102e;font-weight:700">★</span>' if p.get("project_we_love") else ""
    title = (p.get("title") or "(untitled)").replace("<", "&lt;").replace(">", "&gt;")
    blurb_zh = (p.get("blurb_zh") or "").replace("<", "&lt;").replace(">", "&gt;")
    url = p.get("url") or "#"
    brand = p.get("matched_brand_zh") or p.get("matched_brand") or p.get("creator_name") or ""
    country = p.get("country") or ""
    head = (
        f'<a href="{url}" style="color:#0d0d0d;text-decoration:none;font-weight:600">'
        f'{star} {title}</a>'
    )
    sub_parts = []
    if blurb_zh:
        sub_parts.append(f'<span style="color:#3a3a3a">{blurb_zh}</span>')
    meta_parts = [x for x in (brand, country) if x]
    if meta_parts:
        sub_parts.append(f'<span style="color:#9a9a96;font-size:12px">{" · ".join(meta_parts)}</span>')

    if kind == "prelaunch":
        right = f'<div style="font-family:monospace;font-variant-numeric:tabular-nums;font-weight:600">{fmt_int(p.get("followers"))}</div>'
        right_label = '<div style="color:#9a9a96;font-size:11px;letter-spacing:.05em;text-transform:uppercase">followers</div>'
    else:  # live
        right = f'<div style="font-family:monospace;font-variant-numeric:tabular-nums;font-weight:600">{fmt_usd(p.get("pledged_usd"))}</div>'
        right_label = f'<div style="color:#9a9a96;font-size:11px;letter-spacing:.05em">{fmt_int(p.get("backers"))} backers</div>'

    return (
        '<tr>'
        '<td style="padding:11px 0;border-bottom:1px solid #ebebe7;vertical-align:top">'
        f'{head}'
        f'<div style="margin-top:3px;line-height:1.45">{"<br>".join(sub_parts)}</div>'
        '</td>'
        '<td style="padding:11px 0 11px 12px;border-bottom:1px solid #ebebe7;vertical-align:top;text-align:right;white-space:nowrap">'
        f'{right}{right_label}'
        '</td>'
        '</tr>'
    )


def _signal_html(line: str) -> str:
    """Convert a CHANGELOG.md '- **Title** — detail' line into HTML."""
    s = line.lstrip("- ").rstrip()
    # "**Title** — detail" → bold + light text
    if s.startswith("**"):
        end = s.find("**", 2)
        if end > 0:
            title = s[2:end]
            rest = s[end + 2:].lstrip(" —")
            return (
                f'<li style="margin:4px 0;line-height:1.5">'
                f'<span style="font-weight:600">{title}</span>'
                f'<span style="color:#6b6b6b"> — {rest}</span>'
                f'</li>'
            )
    return f'<li style="margin:4px 0">{s}</li>'


def build_html(curr: dict) -> tuple[str, str]:
    """Returns (subject, html_body)."""
    d = get_summary_data(curr)
    today = d["today"]
    counts = d["counts"]
    subject = (
        f"[KS China Tracker] {today} · "
        f"{d['total']} 项 · {counts['live']} 在筹 · "
        f"{counts['prelaunch']} 未发布"
    )

    kpi_cell = lambda label, value, color="#0d0d0d": (
        '<td style="padding:18px 14px;border-right:1px solid #d6d6d1;vertical-align:top;width:25%">'
        f'<div style="font-family:Inter Tight,Inter,sans-serif;font-weight:700;font-size:30px;letter-spacing:-.02em;color:{color};line-height:1">{value}</div>'
        f'<div style="margin-top:6px;font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:#6b6b6b">{label}</div>'
        '</td>'
    )

    signals_html = ""
    if d["signals"]:
        signals_html = (
            '<h2 style="font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:#6b6b6b;margin:32px 0 10px">🔥 24 小时异动</h2>'
            f'<ul style="list-style:none;padding:0;margin:0 0 0 0;font-size:13px">'
            + "".join(_signal_html(s) for s in d["signals"])
            + '</ul>'
        )

    prelaunch_rows = "".join(_row_html(p, kind="prelaunch") for p in d["prelaunch"][:5])
    live_rows = "".join(_row_html(p, kind="live") for p in d["live"][:5])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>{subject}</title></head>
<body style="margin:0;padding:24px 16px;background:#fafaf7;font-family:Inter,-apple-system,'PingFang SC',sans-serif;color:#0d0d0d;line-height:1.5">

<div style="max-width:680px;margin:0 auto;background:#ffffff;padding:32px 28px 28px;border:1px solid #d6d6d1">

  <div style="font-size:11px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:#6b6b6b;margin-bottom:8px">
    <span style="display:inline-block;width:7px;height:7px;background:#c8102e;border-radius:50%;vertical-align:1px;margin-right:8px"></span>
    Daily Briefing · 北京时间 09:30 自动发送
  </div>
  <h1 style="font-family:Inter Tight,Inter,sans-serif;font-weight:800;letter-spacing:-.025em;font-size:32px;line-height:1.05;margin:0 0 12px;color:#0d0d0d">
    Kickstarter China Tracker
  </h1>
  <p style="font-size:13.5px;color:#3a3a3a;margin:0 0 24px">
    今日（{today}）追踪到 <b>{d['total']}</b> 个中国背景消费硬件项目。
  </p>

  <table style="width:100%;border-collapse:collapse;border-top:1px solid #0d0d0d;border-bottom:1px solid #0d0d0d;margin-bottom:0">
    <tr>
      {kpi_cell("未发布", counts['prelaunch'], "#c8102e")}
      {kpi_cell("在筹中", counts['live'], "#1c4ed8")}
      {kpi_cell("已成功", counts['successful'])}
      <td style="padding:18px 14px;vertical-align:top;width:25%">
        <div style="font-family:Inter Tight,Inter,sans-serif;font-weight:700;font-size:30px;letter-spacing:-.02em;line-height:1">★ {d['pwl']}</div>
        <div style="margin-top:6px;font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:#6b6b6b">KS 精选</div>
      </td>
    </tr>
  </table>
  <p style="font-size:12px;color:#6b6b6b;margin:10px 0 0">
    在筹合计已筹 <b style="color:#0d0d0d">{fmt_usd(d['total_live_usd'])}</b> · 中国背景置信度高 <b style="color:#0d0d0d">{d['high']}</b> / {d['total']}
  </p>

  {signals_html}

  <h2 style="font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:#6b6b6b;margin:32px 0 6px">⏳ Prelaunch · Top 5 by followers</h2>
  <table style="width:100%;border-collapse:collapse;font-size:13.5px">
    {prelaunch_rows or '<tr><td style="color:#9a9a96;padding:14px 0">暂无</td></tr>'}
  </table>

  <h2 style="font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:#6b6b6b;margin:32px 0 6px">🔴 Live · Top 5 by USD raised</h2>
  <table style="width:100%;border-collapse:collapse;font-size:13.5px">
    {live_rows or '<tr><td style="color:#9a9a96;padding:14px 0">暂无</td></tr>'}
  </table>

  <p style="margin:32px 0 0;padding-top:20px;border-top:1px solid #0d0d0d;font-size:12px;color:#6b6b6b">
    <a href="{PAGES_URL}" style="color:#0d0d0d;border-bottom:1px solid #d6d6d1;text-decoration:none">完整看板</a>
    &nbsp;·&nbsp;
    <a href="{LATEST_URL}" style="color:#0d0d0d;border-bottom:1px solid #d6d6d1;text-decoration:none">完整 Markdown 报告</a>
    &nbsp;·&nbsp;
    <a href="https://github.com/Chen17-sq/kickstarter-china-tracker" style="color:#0d0d0d;border-bottom:1px solid #d6d6d1;text-decoration:none">GitHub</a>
  </p>
  <p style="margin:8px 0 0;font-size:11px;color:#9a9a96">
    退订：在仓库 Settings → Secrets → Actions 把 NOTIFY_EMAIL_TO 删掉或者改一下。
  </p>

</div>
</body>
</html>"""
    return subject, html


def post_resend(api_key: str, sender: str, to: list[str], subject: str, html: str) -> None:
    resp = httpx.post(
        RESEND_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"from": sender, "to": to, "subject": subject, "html": html},
        timeout=30,
    )
    if resp.status_code >= 400:
        # Surface the Resend error verbatim so debugging is fast in CI.
        print(f"Resend error {resp.status_code}: {resp.text}", file=sys.stderr)
        resp.raise_for_status()


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

    if args.dry_run:
        preview = REPO_ROOT / "data" / ".tmp" / "email_preview.html"
        preview.parent.mkdir(parents=True, exist_ok=True)
        preview.write_text(html, encoding="utf-8")
        print(f"Subject: {subject}")
        print(f"HTML: {len(html):,} chars")
        print(f"Preview written to {preview}")
        print(f"Open: file://{preview}")
        return 0

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print("RESEND_API_KEY not set — email skipped")
        return 0

    raw_to = os.environ.get("NOTIFY_EMAIL_TO", "")
    to = [e.strip() for e in raw_to.split(",") if e.strip()]
    if not to:
        print("NOTIFY_EMAIL_TO empty — no recipients, skipping")
        return 0

    sender = os.environ.get(
        "NOTIFY_EMAIL_FROM",
        "KS Tracker <onboarding@resend.dev>",
    )
    post_resend(api_key, sender, to, subject, html)
    print(f"Email sent: subject={subject!r}, to={to}, from={sender}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
