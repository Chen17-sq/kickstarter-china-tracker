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

PWL = "★"


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


def fmt_pct(p) -> str:
    """KS's `percent_funded` is already a percentage where 100 = 100%."""
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


def fmt_int(n) -> str:
    if n is None or n == "":
        return "—"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


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

    out: list[str] = []
    out.append(f"# Kickstarter China Tracker — {today}")
    out.append("")
    out.append(f"_自动生成于 {curr.get('generated_at','—')} · 仓库 [Pages 站](https://chen17-sq.github.io/kickstarter-china-tracker/) · [JSON](../data/projects.json)_")
    out.append("")

    out.append("## 概览")
    out.append("")
    out.append("| 总数 | 未发布 | 在筹中 | 已成功 | KS 精选 | 在筹已筹合计 |")
    out.append("| ---: | ---: | ---: | ---: | ---: | ---: |")
    out.append(f"| **{len(projects)}** | {counts['prelaunch']} | {counts['live']} | {counts['successful']} | {PWL} {pwl_count} | {fmt_usd(total_live_usd)} |")
    out.append("")
    out.append(f"中国背景置信度高 · **{high}** / {len(projects)}")
    out.append("")

    if new_today:
        out.append(f"## 🆕 今日新增 · {len(new_today)} 项")
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
        out.append(f"## 🔄 状态变化 · {len(status_changes)} 项")
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
        out.append(f"## ⏳ Prelaunch · {len(prelaunch)} 项")
        out.append("")
        out.append("| | 项目 / 一句话 | 公司 | 国家 | Followers | 时间 |")
        out.append("| - | --- | --- | --- | ---: | --- |")
        for p in prelaunch[:30]:
            star = PWL if p.get("project_we_love") else ""
            brand = p.get("matched_brand_zh") or p.get("matched_brand") or p.get("creator_name") or ""
            out.append(
                f"| {star} | {project_link(p)} | {brand} | {p.get('country','?')} "
                f"| {fmt_int(p.get('followers'))} | {timeline_text(p)} |"
            )
        if len(prelaunch) > 30:
            out.append(f"| | _…and {len(prelaunch)-30} more in [JSON](../data/projects.json)_ | | | | |")
        out.append("")

    live = sorted(
        [p for p in projects if p.get("status") == "live"],
        key=lambda x: -float(x.get("pledged_usd") or 0),
    )
    if live:
        out.append(f"## 🔴 在筹 · 按已筹排序 Top {min(20, len(live))}")
        out.append("")
        out.append("| | 项目 / 一句话 | 已筹 | Backers | Followers | 完成率 | 时间 |")
        out.append("| - | --- | ---: | ---: | ---: | ---: | --- |")
        for p in live[:20]:
            star = PWL if p.get("project_we_love") else ""
            out.append(
                f"| {star} | {project_link(p)} | {fmt_usd(p.get('pledged_usd'))} | "
                f"{fmt_int(p.get('backers'))} | {fmt_int(p.get('followers'))} | "
                f"{fmt_pct(p.get('percent_funded'))} | {timeline_text(p)} |"
            )
        out.append("")

    successful = sorted(
        [p for p in projects if p.get("status") == "successful"],
        key=lambda x: -float(x.get("pledged_usd") or 0),
    )
    if successful:
        out.append(f"## ✅ 最近已结束 · 按已筹排序 Top {min(15, len(successful))}")
        out.append("")
        out.append("| 项目 / 一句话 | 已筹 | Backers | 完成率 | 结束 |")
        out.append("| --- | ---: | ---: | ---: | --- |")
        for p in successful[:15]:
            out.append(
                f"| {project_link(p)} | {fmt_usd(p.get('pledged_usd'))} | "
                f"{fmt_int(p.get('backers'))} | {fmt_pct(p.get('percent_funded'))} | "
                f"{timeline_text(p)} |"
            )
        out.append("")

    out.append("---")
    out.append("")
    out.append("<sub>报告由 `scraper/report.py` 每次 cron 自动生成 · 中文一句话来自 [`data/blurbs_zh.json`](../data/blurbs_zh.json)，欢迎 PR 补充 · 抓取细节见 [ARCHITECTURE.md](../ARCHITECTURE.md)</sub>")
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
