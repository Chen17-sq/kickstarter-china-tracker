"""Generate a daily Markdown report from the latest snapshot.

Compares against the previous history snapshot to surface:
  - 今日新增 / 状态变化（vs yesterday）
  - Prelaunch top — sorted by ★ KS picks then by followers
  - Live top — sorted by USD pledged
  - 已结束（24h 内）

Output: reports/YYYY-MM-DD.md (committed by the cron workflow).
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS = REPO_ROOT / "reports"
HISTORY = REPO_ROOT / "data" / "history"
PROJECTS = REPO_ROOT / "data" / "projects.json"

PWL = "✦"

from ._common import edition_number, fmt_usd, fmt_int, fmt_pct  # noqa: E402  shared


def days_since(epoch) -> int | None:
    if not epoch:
        return None
    try:
        return max(0, int((dt.datetime.now(dt.timezone.utc).timestamp() - float(epoch)) / 86400))
    except (TypeError, ValueError):
        return None


def days_until(epoch) -> int | None:
    if not epoch:
        return None
    try:
        return max(0, int((float(epoch) - dt.datetime.now(dt.timezone.utc).timestamp()) / 86400))
    except (TypeError, ValueError):
        return None


def fmt_epoch_date(epoch) -> str:
    if not epoch:
        return "—"
    try:
        return dt.datetime.fromtimestamp(float(epoch), tz=dt.timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return "—"


def timeline_text(p: dict) -> str:
    st = p.get("status")
    if st == "prelaunch":
        # Prefer state_changed_at (when project entered "submitted" prelaunch
        # state) — created_at can be years old when creators draft early.
        d = days_since(p.get("state_changed_at") or p.get("created_at"))
        return f"已预热 {d} 天" if d is not None else ""
    if st == "live":
        parts = []
        d_in = days_since(p.get("launched_at"))
        if d_in is not None:
            parts.append(f"上线 {d_in} 天")
        d_left = days_until(p.get("deadline"))
        if d_left is not None:
            parts.append(f"剩 {d_left} 天")
        return " · ".join(parts)
    if st in ("successful", "failed", "canceled"):
        d = days_since(p.get("deadline"))
        if d is None:
            return ""
        if d < 1:
            return "今日结束"
        if d < 60:
            return f"{d} 天前结束"
        return f"结束于 {fmt_epoch_date(p.get('deadline'))}"
    return ""


def project_link(p: dict) -> str:
    title = p.get("title") or "(untitled)"
    blurb_zh = p.get("blurb_zh")
    label = title
    if blurb_zh:
        label = f"{title} — {blurb_zh}"
    url = p.get("url")
    return f"[{label}]({url})" if url else label


def find_prev_snapshot() -> dict | None:
    """Return the second-most-recent snapshot from data/history/, if any.

    Under daily cron this is yesterday's. Under more frequent cron it is
    the immediately previous run — still useful for diff signals.
    """
    if not HISTORY.exists():
        return None
    snaps = sorted(HISTORY.glob("*.json"))
    if len(snaps) < 2:
        return None
    try:
        return json.loads(snaps[-2].read_text(encoding="utf-8"))
    except Exception:
        return None


def make_report(curr: dict, prev: dict | None) -> str:
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    projects = curr.get("projects", []) or []
    prev_by_path = {}
    if prev:
        prev_by_path = {p["pathname"]: p for p in prev.get("projects", []) if p.get("pathname")}

    counts = {"prelaunch": 0, "live": 0, "successful": 0, "failed": 0}
    pwl_count = high = 0
    total_live_usd = 0.0
    for p in projects:
        st = p.get("status")
        if st in counts:
            counts[st] += 1
        if p.get("project_we_love"):
            pwl_count += 1
        if p.get("china_confidence") == "高":
            high += 1
        if st == "live":
            try:
                total_live_usd += float(p.get("pledged_usd") or 0)
            except (TypeError, ValueError):
                pass

    new_today = []
    status_changes = []
    if prev_by_path:
        for p in projects:
            path = p.get("pathname")
            if not path:
                continue
            prev_p = prev_by_path.get(path)
            if prev_p is None:
                new_today.append(p)
            elif prev_p.get("status") != p.get("status"):
                status_changes.append((p, prev_p.get("status")))

    edition = edition_number()
    today_long = dt.datetime.now(dt.timezone.utc).strftime("%A, %B %d, %Y").upper()

    out: list[str] = []
    # Newsprint masthead
    out.append("```")
    out.append(f"VOL. 1 · NO. {edition}                                    BEIJING EDITION")
    out.append(f"DAILY · LIVE EDITION · {today_long}")
    out.append("```")
    out.append("")
    out.append(f"# Kickstarter China Tracker")
    out.append("")
    out.append(f"> *All The Crowd-Funded Hardware Fit To Print* — Vol. 1, No. {edition} · {today}")
    out.append("")
    out.append(f"_Auto-generated at {curr.get('generated_at','—')} · [完整看板](https://chen17-sq.github.io/kickstarter-china-tracker/) · [JSON](../data/projects.json)_")
    out.append("")
    out.append("---")
    out.append("")

    out.append("## Section A · 头版概览")
    out.append("")
    out.append("| Tracked | Prelaunch | Live | Funded | Editor's | Pledged |")
    out.append("| ---: | ---: | ---: | ---: | ---: | ---: |")
    out.append(f"| **{len(projects)}** | {counts['prelaunch']} | {counts['live']} | {counts['successful']} | {PWL} {pwl_count} | {fmt_usd(total_live_usd)} |")
    out.append("")
    out.append(f"_中国背景置信度高 · **{high}** / {len(projects)}_")
    out.append("")

    if new_today or status_changes:
        out.append("✦ &nbsp; ✦ &nbsp; ✦")
        out.append("")
    if new_today:
        out.append(f"## Section B · 🆕 今日新增 · {len(new_today)} 项")
        out.append("")
        new_today_sorted = sorted(
            new_today,
            key=lambda x: (
                0 if x.get("status") == "prelaunch" else 1,
                -float(x.get("pledged_usd") or 0),
            ),
        )
        for p in new_today_sorted[:30]:
            star = f"{PWL} " if p.get("project_we_love") else ""
            out.append(f"- {star}**`{p.get('status','?')}`** · {project_link(p)} · {p.get('country','?')}")
        if len(new_today_sorted) > 30:
            out.append(f"- _…and {len(new_today_sorted)-30} more_")
        out.append("")

    if status_changes:
        out.append(f"## Section B · 🔄 状态变化 · {len(status_changes)} 项")
        out.append("")
        for p, prev_status in status_changes[:25]:
            out.append(f"- {project_link(p)}: `{prev_status}` → `{p.get('status')}`")
        out.append("")

    prelaunch = sorted(
        [p for p in projects if p.get("status") == "prelaunch"],
        key=lambda x: (
            0 if x.get("project_we_love") else 1,
            -(int(x.get("followers") or 0)),
            x.get("title") or "",
        ),
    )
    if prelaunch:
        # Load curated 4-bullet Chinese highlights for the top-3 detail blocks
        try:
            from .social import load_highlights_zh as _load_zh
            hl_map = _load_zh()
        except Exception:
            hl_map = {}

        out.append("✦ &nbsp; ✦ &nbsp; ✦")
        out.append("")
        out.append(f"## Section C · ⏳ Prelaunch · Top 10")
        out.append("")
        # Top 3 = full detail (product image + 4 Chinese highlights), per
        # design rules in docs/DESIGN_RULES.md.
        for i, p in enumerate(prelaunch[:3]):
            rank = f"{i+1:02d}"
            star = PWL if p.get("project_we_love") else " "
            brand = p.get("matched_brand_zh") or p.get("matched_brand") or p.get("creator_name") or ""
            country = p.get("country", "?")
            blurb_zh = p.get("blurb_zh") or ""
            url = p.get("url") or ""
            title = (p.get("title") or "").replace("|", "\\|")
            out.append(f"### No. {rank} · {star} {title}")
            out.append("")
            if p.get("image_url"):
                # KS hero photo, no filter, max 360px wide for GitHub Markdown
                out.append(f'<img src="{p["image_url"]}" alt="" width="360" />')
                out.append("")
            stat_parts_pre = [
                f"**{brand}**",
                country,
                f"**{fmt_int(p.get('followers'))}** watchers",
            ]
            if p.get("min_pledge_usd"):
                stat_parts_pre.append(f"起步价 **{fmt_usd(p['min_pledge_usd'])}**")
            stat_parts_pre.append(timeline_text(p))
            out.append(" · ".join(s for s in stat_parts_pre if s))
            out.append("")
            if blurb_zh:
                out.append(f"*{blurb_zh}*")
                out.append("")
            highlights = hl_map.get(p.get("pathname")) or []
            if not highlights and p.get("blurb"):
                highlights = [s.strip() for s in p["blurb"].split("|") if s.strip()][:4]
            for h in highlights[:4]:
                out.append(f"- ▸ {h}")
            out.append("")
            out.append(f"→ [在 Kickstarter 看完整页面]({url})")
            out.append("")
            out.append("---")
            out.append("")

        # Ranks 4-10 in compact list form (text only — Top 3 上面已是图文)
        if len(prelaunch) > 3:
            out.append("**Top 4–10 · 列表形式**")
            out.append("")
            out.append("| # | 项目 / 一句话 | 公司 | 国家 | Followers | 时间 |")
            out.append("| ---: | --- | --- | --- | ---: | --- |")
            for i, p in enumerate(prelaunch[3:10], start=4):
                star = PWL if p.get("project_we_love") else ""
                brand = p.get("matched_brand_zh") or p.get("matched_brand") or p.get("creator_name") or ""
                out.append(
                    f"| {i:02d} {star} | {project_link(p)} | {brand} | {p.get('country','?')} "
                    f"| {fmt_int(p.get('followers'))} | {timeline_text(p)} |"
                )
            out.append("")
            if len(prelaunch) > 10:
                out.append(f"_…还有 {len(prelaunch)-10} 个 prelaunch 项目，完整看板见 [Pages](https://chen17-sq.github.io/kickstarter-china-tracker/) 或 [JSON](../data/projects.json)_")
                out.append("")

    live = sorted(
        [p for p in projects if p.get("status") == "live"],
        key=lambda x: -float(x.get("pledged_usd") or 0),
    )
    if live:
        from .momentum import conversion_per_watcher, projected_total

        out.append("✦ &nbsp; ✦ &nbsp; ✦")
        out.append("")
        out.append(f"## Section D · 🔴 Live · Top 10")
        out.append("")
        # Top 3 detail blocks
        for i, p in enumerate(live[:3]):
            rank = f"{i+1:02d}"
            star = PWL if p.get("project_we_love") else " "
            brand = p.get("matched_brand_zh") or p.get("matched_brand") or p.get("creator_name") or ""
            country = p.get("country", "?")
            blurb_zh = p.get("blurb_zh") or ""
            url = p.get("url") or ""
            title = (p.get("title") or "").replace("|", "\\|")
            out.append(f"### No. {rank} · {star} {title}")
            out.append("")
            if p.get("image_url"):
                out.append(f'<img src="{p["image_url"]}" alt="" width="360" />')
                out.append("")
            cpw = conversion_per_watcher(p)
            proj = projected_total(p)
            d_p = p.get("delta_pledged_usd")
            stat_parts = [
                f"**{brand}** · {country}",
                f"已筹 **{fmt_usd(p.get('pledged_usd'))}**" + (f" *(+{fmt_usd(d_p)})*" if d_p and d_p > 0 else ""),
                f"{fmt_int(p.get('backers'))} backers",
                f"完成率 **{fmt_pct(p.get('percent_funded'))}**",
            ]
            if p.get("min_pledge_usd"):
                stat_parts.append(f"起步价 **{fmt_usd(p['min_pledge_usd'])}**")
            if cpw is not None:
                stat_parts.append(f"\\${cpw:.0f}/watcher")
            if proj is not None:
                stat_parts.append(f"预计总额 {fmt_usd(proj)}")
            stat_parts.append(timeline_text(p))
            out.append(" · ".join(s for s in stat_parts if s))
            out.append("")
            if blurb_zh:
                out.append(f"*{blurb_zh}*")
                out.append("")
            highlights = hl_map.get(p.get("pathname")) or []
            if not highlights and p.get("blurb"):
                highlights = [s.strip() for s in p["blurb"].split("|") if s.strip()][:4]
            for h in highlights[:4]:
                out.append(f"- ▸ {h}")
            out.append("")
            out.append(f"→ [在 Kickstarter 看完整页面]({url})")
            out.append("")
            out.append("---")
            out.append("")

        # Ranks 4-10 in compact list form (text only)
        if len(live) > 3:
            out.append("**Top 4–10 · 列表形式**")
            out.append("")
            out.append("| # | 项目 / 一句话 | 已筹 | Backers | 完成率 | 时间 |")
            out.append("| ---: | --- | ---: | ---: | ---: | --- |")
            for i, p in enumerate(live[3:10], start=4):
                star = PWL if p.get("project_we_love") else ""
                d_p = p.get("delta_pledged_usd")
                pledged_cell = fmt_usd(p.get("pledged_usd"))
                if d_p and d_p > 0:
                    pledged_cell += f" *(+{fmt_usd(d_p)})*"
                out.append(
                    f"| {i:02d} {star} | {project_link(p)} | {pledged_cell} | "
                    f"{fmt_int(p.get('backers'))} | "
                    f"{fmt_pct(p.get('percent_funded'))} | "
                    f"{timeline_text(p)} |"
                )
            out.append("")
            if len(live) > 10:
                out.append(f"_…还有 {len(live)-10} 个 live 项目，完整看板见 [Pages](https://chen17-sq.github.io/kickstarter-china-tracker/) 或 [JSON](../data/projects.json)_")
                out.append("")

    successful = sorted(
        [p for p in projects if p.get("status") == "successful"],
        key=lambda x: -float(x.get("pledged_usd") or 0),
    )
    if successful:
        from .momentum import conversion_per_watcher
        out.append("✦ &nbsp; ✦ &nbsp; ✦")
        out.append("")
        out.append(f"## Section E · ✅ 最近已结束 · Top 10")
        out.append("")
        out.append("| # | 项目 / 一句话 | 已筹 | Backers | $/Watcher | 完成率 | 结束 |")
        out.append("| ---: | --- | ---: | ---: | ---: | ---: | --- |")
        for i, p in enumerate(successful[:10], start=1):
            cpw = conversion_per_watcher(p)
            cpw_cell = fmt_usd(cpw) if cpw else "—"
            out.append(
                f"| {i:02d} | {project_link(p)} | {fmt_usd(p.get('pledged_usd'))} | "
                f"{fmt_int(p.get('backers'))} | {cpw_cell} | "
                f"{fmt_pct(p.get('percent_funded'))} | "
                f"{timeline_text(p)} |"
            )
        out.append("")

    # ── Section F · Sleepers (algorithmic editor's picks) ────────────
    from .sleepers import select_sleepers
    front_page_paths = set()
    front_page_paths.update(p.get("pathname") for p in prelaunch[:10] if p.get("pathname"))
    front_page_paths.update(p.get("pathname") for p in live[:10] if p.get("pathname"))
    front_page_paths.update(p.get("pathname") for p in successful[:10] if p.get("pathname"))
    sleepers = select_sleepers(projects, front_page_paths, n=5)
    if sleepers:
        out.append("✦ &nbsp; ✦ &nbsp; ✦")
        out.append("")
        out.append(f"## Section F · 🌙 Sleeper Picks · {len(sleepers)} 个值得多看一眼")
        out.append("")
        out.append("_排在 Top 10 之外但被算法挑出来 — 每个都注明被选中的原因。_")
        out.append("")
        for i, p in enumerate(sleepers, start=1):
            star = PWL if p.get("project_we_love") else " "
            brand = p.get("matched_brand_zh") or p.get("matched_brand") or p.get("creator_name") or ""
            country = p.get("country", "?")
            status = p.get("status", "?")
            reason = p.get("_sleeper_reason", "")
            blurb_zh = p.get("blurb_zh") or ""
            url = p.get("url") or ""
            title = (p.get("title") or "").replace("|", "\\|")
            out.append(f"### {i}. {star} {title}")
            out.append("")
            if p.get("image_url"):
                out.append(f'<img src="{p["image_url"]}" alt="" width="280" />')
                out.append("")
            line_parts = [
                f"`{status}`",
                f"**{brand}**" if brand else "",
                country,
            ]
            if status == "live":
                line_parts.append(f"已筹 **{fmt_usd(p.get('pledged_usd'))}**")
                line_parts.append(f"完成率 **{fmt_pct(p.get('percent_funded'))}**")
            elif status == "prelaunch":
                line_parts.append(f"**{fmt_int(p.get('followers'))}** watchers")
            elif status == "successful":
                line_parts.append(f"已筹 **{fmt_usd(p.get('pledged_usd'))}**")
            out.append(" · ".join(s for s in line_parts if s))
            out.append("")
            out.append(f"**▸ 选中原因：{reason}**")
            out.append("")
            if blurb_zh:
                out.append(f"*{blurb_zh}*")
                out.append("")
            out.append(f"→ [在 Kickstarter 看完整页面]({url})")
            out.append("")
            out.append("---")
            out.append("")

    out.append("✦ &nbsp; ✦ &nbsp; ✦")
    out.append("")
    out.append("---")
    out.append("")
    out.append(f"*All the news that's fit to print, every morning at 08:00 Beijing.*")
    out.append("")
    out.append(f"<sub>Vol. 1 · No. {edition} · Auto-generated by `scraper/report.py` · 中文一句话见 [`data/blurbs_zh.json`](../data/blurbs_zh.json)（欢迎 PR）· 架构见 [ARCHITECTURE.md](../ARCHITECTURE.md)</sub>")
    return "\n".join(out)


def write_today() -> Path:
    if not PROJECTS.exists():
        raise SystemExit("data/projects.json not found — run scraper first")
    curr = json.loads(PROJECTS.read_text(encoding="utf-8"))
    prev = find_prev_snapshot()
    md = make_report(curr, prev)
    REPORTS.mkdir(parents=True, exist_ok=True)
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    out_path = REPORTS / f"{today}.md"
    out_path.write_text(md, encoding="utf-8")
    # Also write a stable-URL copy so a bookmark always points at today.
    (REPORTS / "latest.md").write_text(md, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    p = write_today()
    print(f"wrote {p.relative_to(REPO_ROOT)}")
