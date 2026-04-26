"""Push a daily Slack / Discord summary of the latest snapshot.

Reads:
  - data/projects.json   — current snapshot
  - CHANGELOG.md          — diff vs. previous run (optional, may be absent)

Builds a compact Markdown summary (KPI line + 🔥 today's signals + Top 5
prelaunch by followers + Top 5 live by USD pledged) and posts it to:
  - SLACK_WEBHOOK    — if set, posts as Slack mrkdwn
  - DISCORD_WEBHOOK  — if set, posts as Discord markdown

Both env vars are read from process env (set as repo secrets in the
GitHub Actions workflow). If neither is configured, prints to stdout and
exits 0 — safe to run in any environment.

Run locally:
  python -m scraper.notify --dry-run        # build + print, no POST
  python -m scraper.notify                  # POST to whichever webhooks are set
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECTS = REPO_ROOT / "data" / "projects.json"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

PAGES_URL = "https://chen17-sq.github.io/kickstarter-china-tracker/"
LATEST_URL = "https://github.com/Chen17-sq/kickstarter-china-tracker/blob/main/reports/latest.md"


def fmt_usd(n) -> str:
    if n is None or n == "":
        return "—"
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "—"
    if v >= 1_000_000:
        return f"${v/1e6:.2f}M".replace(".00M", "M")
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


def project_label(p: dict) -> str:
    """The 'product · 中文一句话' line, suitable for Slack mrkdwn link text."""
    title = p.get("title") or "(untitled)"
    blurb_zh = p.get("blurb_zh")
    return f"{title} — {blurb_zh}" if blurb_zh else title


def link(p: dict) -> str:
    label = project_label(p)
    url = p.get("url") or ""
    return f"<{url}|{label}>" if url else label


def discord_link(p: dict) -> str:
    """Discord uses [text](url) syntax."""
    label = project_label(p)
    url = p.get("url") or ""
    return f"[{label}]({url})" if url else label


def parse_changelog_signals(max_items: int = 6) -> list[str]:
    """Pull the most newsworthy lines from CHANGELOG.md.

    diff.py emits sections '## new', '## status_change', '## followers_delta',
    '## backers_delta'. We surface up to N of the most actionable lines.
    Format kept neutral so it works for both Slack and Discord (markdown).
    """
    if not CHANGELOG.exists():
        return []
    text = CHANGELOG.read_text(encoding="utf-8")
    out: list[str] = []
    # Order of priority: new > status_change > followers_delta > backers_delta
    section_priorities = ["status_change", "new", "followers_delta", "backers_delta"]
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].split(" ", 1)[0]
            sections[current] = []
        elif line.startswith("- ") and current:
            sections[current].append(line)
    for kind in section_priorities:
        for line in sections.get(kind, []):
            if len(out) >= max_items:
                return out
            out.append(line)
    return out


def get_summary_data(curr: dict) -> dict:
    """Pull a structured summary from the snapshot, reusable across notifiers.

    Returns: {today, total, counts, pwl, high, total_live_usd, prelaunch, live, signals}
    """
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    projects = curr.get("projects", []) or []

    counts = {"prelaunch": 0, "live": 0, "successful": 0, "failed": 0}
    pwl = high = 0
    total_live_usd = 0.0
    for p in projects:
        st = p.get("status")
        if st in counts:
            counts[st] += 1
        if p.get("project_we_love"):
            pwl += 1
        if p.get("china_confidence") == "高":
            high += 1
        if st == "live":
            try:
                total_live_usd += float(p.get("pledged_usd") or 0)
            except (TypeError, ValueError):
                pass

    prelaunch = sorted(
        [p for p in projects if p.get("status") == "prelaunch"],
        key=lambda x: (
            0 if x.get("project_we_love") else 1,
            -(int(x.get("followers") or 0)),
        ),
    )
    live = sorted(
        [p for p in projects if p.get("status") == "live"],
        key=lambda x: -float(x.get("pledged_usd") or 0),
    )

    return {
        "today": today,
        "total": len(projects),
        "counts": counts,
        "pwl": pwl,
        "high": high,
        "total_live_usd": total_live_usd,
        "prelaunch": prelaunch,
        "live": live,
        "signals": parse_changelog_signals(),
    }


def build_summary(curr: dict, *, dialect: str = "slack") -> str:
    """Build the daily summary message in either 'slack' or 'discord' dialect.

    Both flavours use the same structure but slightly different link syntax.
    """
    data = get_summary_data(curr)
    today = data["today"]
    counts = data["counts"]
    prelaunch = data["prelaunch"]
    live = data["live"]
    pwl = data["pwl"]
    total_live_usd = data["total_live_usd"]

    fmt_link = link if dialect == "slack" else discord_link

    lines: list[str] = []
    lines.append(f"*📊 Kickstarter China Tracker · {today}*")
    lines.append(
        f"`{data['total']}` 项追踪 · "
        f"`{counts['prelaunch']}` 未发布 · "
        f"`{counts['live']}` 在筹 ({fmt_usd(total_live_usd)} 合计) · "
        f"`{counts['successful']}` 成功 · "
        f"★ `{pwl}` KS 精选"
    )

    signals = data["signals"]
    if signals:
        lines.append("")
        lines.append("*🔥 24h 异动*")
        lines.extend(signals)

    if prelaunch:
        lines.append("")
        lines.append("*⏳ Prelaunch · Top 5 by followers*")
        for p in prelaunch[:5]:
            star = "★ " if p.get("project_we_love") else ""
            lines.append(f"• {star}{fmt_link(p)} · {fmt_int(p.get('followers'))} followers")

    if live:
        lines.append("")
        lines.append("*🔴 Live · Top 5 by USD raised*")
        for p in live[:5]:
            star = "★ " if p.get("project_we_love") else ""
            lines.append(
                f"• {star}{fmt_link(p)} · {fmt_usd(p.get('pledged_usd'))} · "
                f"{fmt_int(p.get('backers'))} backers"
            )

    lines.append("")
    if dialect == "slack":
        lines.append(f"<{PAGES_URL}|完整看板> · <{LATEST_URL}|今日报告>")
    else:
        lines.append(f"[完整看板]({PAGES_URL}) · [今日报告]({LATEST_URL})")

    return "\n".join(lines)


def post_slack(webhook: str, body: str) -> None:
    httpx.post(
        webhook,
        json={"text": body, "mrkdwn": True},
        timeout=15,
    ).raise_for_status()


def post_discord(webhook: str, body: str) -> None:
    # Discord caps at 2000 chars per message — send in chunks if needed.
    chunks: list[str] = []
    cur = ""
    for line in body.split("\n"):
        if len(cur) + len(line) + 1 > 1900:
            chunks.append(cur)
            cur = line
        else:
            cur = cur + "\n" + line if cur else line
    if cur:
        chunks.append(cur)
    for chunk in chunks:
        httpx.post(webhook, json={"content": chunk}, timeout=15).raise_for_status()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Build the summary and print it, but do NOT POST.")
    ap.add_argument("--slack-only", action="store_true")
    ap.add_argument("--discord-only", action="store_true")
    args = ap.parse_args(argv)

    if not PROJECTS.exists():
        print("data/projects.json not found — nothing to summarize", file=sys.stderr)
        return 1
    curr = json.loads(PROJECTS.read_text(encoding="utf-8"))

    slack_url = os.getenv("SLACK_WEBHOOK")
    discord_url = os.getenv("DISCORD_WEBHOOK")

    if args.dry_run:
        print("--- SLACK DIALECT ---")
        print(build_summary(curr, dialect="slack"))
        print()
        print("--- DISCORD DIALECT ---")
        print(build_summary(curr, dialect="discord"))
        return 0

    posted = 0
    if slack_url and not args.discord_only:
        body = build_summary(curr, dialect="slack")
        post_slack(slack_url, body)
        print(f"Slack OK ({len(body)} chars)")
        posted += 1
    if discord_url and not args.slack_only:
        body = build_summary(curr, dialect="discord")
        post_discord(discord_url, body)
        print(f"Discord OK ({len(body)} chars)")
        posted += 1
    if posted == 0:
        print("No webhook configured (SLACK_WEBHOOK / DISCORD_WEBHOOK) — nothing posted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
