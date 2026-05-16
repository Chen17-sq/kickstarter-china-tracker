#!/usr/bin/env python3
"""Draft editor's note candidates for the daily KS Tracker email.

LOCAL-ONLY TOOL — never invoked by cron, never sends mail, never commits
anything. You run it manually to see what an LLM-drafted editor's note
*would* look like if attached to today's edition.

Usage
-----
    # Set the API key once per shell (or write to .deepseek_key in repo root)
    export DEEPSEEK_API_KEY=sk-xxxxx

    # Draft 3 candidates for today
    python scripts/draft_editor_note.py

    # Override temperature spread
    python scripts/draft_editor_note.py --temps 0.7,0.85,0.95

    # Use the cheap+fast model instead of pro (worse quality, ~50× cheaper)
    python scripts/draft_editor_note.py --model deepseek-v4-flash

    # Save the drafts as markdown (default also prints to stdout)
    python scripts/draft_editor_note.py --out data/.tmp/editor_drafts.md

Workflow we're testing
----------------------
1. Cron runs daily at 08:00 Beijing.
2. Sometime mornings you (the owner) run THIS script.
3. It prints 2-3 candidates. You pick one (or none).
4. We don't yet wire it into the email pipeline — first validate that you
   actually like the output enough to use it.

If after a week you find yourself picking a candidate most days, we'll
integrate it into the cron flow (with a manual approval gate).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECTS_FILE = REPO_ROOT / "data" / "projects.json"
HIGHLIGHTS_FILE = REPO_ROOT / "data" / "highlights_zh.json"
LOCAL_KEY_FILE = REPO_ROOT / ".deepseek_key"  # gitignored

API_URL = "https://api.deepseek.com/v1/chat/completions"

# ── The prompt that worked (v3: macro + specific product, less 老登) ──

SYSTEM_PROMPT = """你是一份硬件日报的总编。每天写 150-220 字的编辑按语。

读者：硬件投资人 + 喜欢看新奇硬件的人。他们看过 Top 10 表了——他们要你：(a) 给一个不显而易见的大判断 (b) 圈出 1-2 个具体产品的"结构性怪点"。

## 必须做的两层（缺一不可）

### 第一层：宏观切片（30% 篇幅）
- 一个非显而易见的横向观察。算个比率 / 分布 / 集中度。
- 例：「Top 2 在筹吃掉 49% 的资金」、「Top 5 prelaunch 全是 prosumer 工坊设备」

### 第二层：产品挑选（70% 篇幅）⭐ 重头
- 挑 **1-2 个特定产品**，讲它**结构性的怪点 / 工程奇招 / 反常识设计**
- 不要写"它做了 X 件事"——写"它居然是 Y 形态"或者"它把传统的 A 换成了 B"
- 用一个具体物理细节让读者想点开 KS 页

举例什么叫"结构性怪点"：
- GORDIX 是"系绳爬行式 CNC"——传统 CNC 靠龙门梁的刚性，它不要龙门，主轴系一根承力绳在工件上爬，能切金属。这种结构在工业里**没人敢做**因为精度全靠龙门。
- Pongbot Aura 把整个 ball launcher + AI 教练压成 7kg——市面上的 Tennibot 之类都是 30-50kg 推车级别。
- Lumos Ultra 把 UV 激光（玻璃/塑料）和 MOPA 激光（金属）**塞同一台**——业界为了热膨胀和聚焦问题一直分两台机器卖。

## ✅ Genuinely sharp 范例（这是目标）

> Top 5 在筹有 4 个是 prosumer 工坊机器：XGIMI 激光投影、Lumos UV+MOPA 双激光、xTool 3D 热压、Makera 桌面 CNC——全是单笔 $500+、卖给一类人：在家把车库改成迷你工厂的人。
>
> 这一类里今天最让人停下来看的不是花钱最多的 XGIMI，是 prelaunch 榜 4314 watchers 的 GORDIX——一台"系绳爬行式" CNC。它**不要龙门**，主轴吊一根承力绳在工件上爬，整机塞进背包，号称能切金属。传统工业 CNC 没人敢这么做，精度全靠龙门梁的刚性。如果它正式上线后 backer 数能跑过 1000，说明 prosumer 这帮人愿意为"形态创新"赌精度——这不是 KS 上典型的"性价比党"逻辑。

注意上例做对了什么：
1. 第一句给出"4/5 都是 prosumer 工坊机器"的横切分布
2. 然后立刻转到 GORDIX 的具体奇怪点："系绳爬行式"、"不要龙门"、"承力绳吊主轴"
3. 解释为什么这怪："传统工业 CNC 没人敢这么做，精度全靠龙门刚性"
4. 钩子是一个具体数（backer > 1000），但更重要的是给出一个心理学判断（"为形态创新赌精度"）

## ❌ Shallow 反例（千万别写）

> "AYANEO Pocket Play 收了 7647 watchers，赌的是不满足触屏的硬核玩家。"
（数据翻译成一句话。）

> "今天 Top 10 都很厉害。"
（废话。）

> "XGIMI 把众筹当 pre-order，这是新趋势。"
（2024 年的老话题。）

## 事实纪律（hardline）

- 每个数字 / 品牌 / 规格 / 地名必须能在 context 找到原文；做算术 OK 但要算对
- 历史品类对照可以引用名字（Pebble / Xperia Play / Tennibot / Anker / Steam Deck / Shapeoko / Carbide 3D 等），不能编它们的数字
- 不许把 $12,991,053 写成 $13M（写 $12.99M 或 1299 万）

## 绝对不要的句式

- "不是 A，而是 B" / "并非 A，而是 B" / "不仅是 A，也是 B"
- "更深层"、"本质上"、"其实"、"归根结底"
- "值得我们思考"、"意义深远"、"未来可期"
- "随着 XX 的发展" / "在这个 XX 的时代"

## 腔调

- **不要老登**：避免"赛道"、"打法"、"破局"、"赋能"、"价值闭环"这种 PPT 词
- **可以 nerd**：技术细节是好的（系绳爬行、双虹膜、UV+MOPA、Anti-RBE 都可以聊）
- **可以略略八卦**：比如点名一个 creator 反复在 KS 上做生意
- 句子可以短

直接写正文，不带标题。
"""


# ── Lint: catch AI tics + banned PPT-speak ─────────────────────────

BANNED_AI_TICS = [
    "更深层", "本质上", "归根结底", "换句话说",
    "值得我们思考", "意义深远", "未来可期",
    "随着 ", "随着AI", "在这个时代",
]
BANNED_PPT_SPEAK = [
    "赛道", "打法", "破局", "赋能", "价值闭环",
    "护城河被", "强强联合", "形成闭环",
]


def lint(note: str) -> list[str]:
    """Return list of warnings for an editor's note draft.

    Empty list = clean. Each warning is human-readable Chinese.
    """
    warns: list[str] = []

    # Paired-pattern AI tics — these are the strongest "AI smell" signals
    if re.search(r"不是[^。！？\n]{0,25}而是", note):
        warns.append('用了 "不是 A 而是 B" 配对句式')
    if re.search(r"并非[^。！？\n]{0,25}而是", note):
        warns.append('用了 "并非 A 而是 B" 配对句式')
    if re.search(r"不仅[^。！？\n]{0,25}也是", note):
        warns.append('用了 "不仅 A 也是 B" 配对句式')

    for p in BANNED_AI_TICS:
        if p in note:
            warns.append(f'含 AI 痕迹词 "{p}"')
    for p in BANNED_PPT_SPEAK:
        if p in note:
            warns.append(f'含老登 PPT 词 "{p}"')

    # Fluff adjectives (substring-match on "有意思"/"值得关注" feels too
    # aggressive — the model uses them more sparingly now and they can be
    # genuinely useful. Keep only the most cringe ones.)
    for p in ["令人瞩目", "今日追踪"]:
        if p in note:
            warns.append(f'含废话 "{p}"')

    return warns


# ── Context builder ───────────────────────────────────────────────

def _to_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _render_project(p: dict, highlights: dict, *, status_view: str) -> str:
    """Render one project block with full blurb + 中文 highlights when available."""
    lines: list[str] = []
    pwl = "★ KS PICK · " if p.get("project_we_love") else ""
    lines.append(f"  {pwl}{p.get('title') or '(untitled)'}")
    if p.get("blurb"):
        lines.append(f"    blurb (英): {p['blurb'][:220]}")
    if p.get("blurb_zh"):
        lines.append(f"    blurb (中): {p['blurb_zh']}")
    hl = highlights.get(p.get("pathname")) or []
    if hl:
        lines.append(f"    中文卖点 bullets: {' · '.join(hl[:4])}")
    country = p.get("country") or "?"
    creator = p.get("creator_name") or "?"
    if status_view == "prelaunch":
        lines.append(
            f"    watchers: {p.get('followers', 0)} · country: {country} · creator: {creator}"
        )
    else:
        lines.append(
            f"    raised: ${_to_float(p.get('pledged_usd')):,.0f}"
            f" · backers: {p.get('backers', 0)}"
            f" · % funded: {int(p.get('percent_funded', 0) or 0)}%"
            f" · country: {country}"
        )
    if p.get("_sleeper_reason"):
        lines.append(f"    sleeper reason: {p['_sleeper_reason']}")
    return "\n".join(lines)


def build_context() -> str:
    """Build the rich context blob fed to the LLM."""
    if not PROJECTS_FILE.exists():
        raise SystemExit(
            f"missing {PROJECTS_FILE.relative_to(REPO_ROOT)} — "
            "run `python -m scraper.run` first or pull latest from main."
        )
    curr = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
    highlights: dict = {}
    if HIGHLIGHTS_FILE.exists():
        try:
            highlights = json.loads(HIGHLIGHTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            highlights = {}

    projects = curr.get("projects") or []
    prelaunch = sorted(
        [p for p in projects if p.get("status") == "prelaunch"],
        key=lambda x: (
            0 if x.get("project_we_love") else 1,
            -(int(x.get("followers") or 0)),
        ),
    )
    live = sorted(
        [p for p in projects if p.get("status") == "live"],
        key=lambda x: -_to_float(x.get("pledged_usd")),
    )
    successful = sorted(
        [p for p in projects if p.get("status") == "successful"],
        key=lambda x: -_to_float(x.get("pledged_usd")),
    )

    # Sleepers — read-only mode so streaks don't double-increment
    try:
        from scraper.sleepers import select_sleepers
        front_paths = {
            p.get("pathname") for p in prelaunch[:10] + live[:10] if p.get("pathname")
        }
        sleepers = select_sleepers(
            projects, front_paths, n=5, track_streaks=False
        )
    except Exception:
        sleepers = []

    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    parts: list[str] = []
    parts.append(f"今日（{today}）KPI:")
    parts.append(
        f"  追踪 {len(projects)} 项 · "
        f"{len(prelaunch)} prelaunch · "
        f"{len(live)} live · "
        f"{len(successful)} successful"
    )
    parts.append(
        f"  在筹累计 ${sum(_to_float(p.get('pledged_usd')) for p in live):,.0f}"
    )
    parts.append(
        f"  KS Editor's Pick {sum(1 for p in projects if p.get('project_we_love'))} 项"
    )
    parts.append("")

    def _section(header: str, items: list[dict], view: str) -> None:
        parts.append(header + "\n")
        for p in items:
            parts.append(_render_project(p, highlights, status_view=view))
            parts.append("")

    _section("Top 5 prelaunch（按 watchers 排序，带 curated 中文卖点）:", prelaunch[:5], "prelaunch")
    _section("Top 5 live（按 USD raised 排序）:", live[:5], "live")
    _section("Top 5 recently successful:", successful[:5], "successful")
    _section("Sleeper picks（算法挑选 · 不在 Top 10）:", sleepers, "sleeper")

    return "\n".join(parts)


# ── DeepSeek API ──────────────────────────────────────────────────

def get_api_key() -> str:
    """Find the DeepSeek API key in env first, then .deepseek_key file."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key.strip()
    if LOCAL_KEY_FILE.exists():
        key = LOCAL_KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    raise SystemExit(
        "DEEPSEEK_API_KEY not found.\n"
        "Either:\n"
        "  export DEEPSEEK_API_KEY=sk-xxxxx\n"
        "  echo 'sk-xxxxx' > .deepseek_key   (gitignored)\n"
    )


def call_deepseek(model: str, temperature: float, ctx: str, *, max_tokens: int = 3000) -> tuple[str, int]:
    """One call to DeepSeek. Returns (content, reasoning_tokens_used)."""
    key = get_api_key()
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"今天的数据：\n\n{ctx}\n\n按上面的标准写。"},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        r = httpx.post(
            API_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
            timeout=300,
        )
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise SystemExit(f"DeepSeek API {e.response.status_code}: {e.response.text}") from e
    except httpx.HTTPError as e:
        raise SystemExit(f"DeepSeek API network error: {e}") from e
    j = r.json()
    msg = j["choices"][0]["message"]
    content = (msg.get("content") or "").strip()
    rt = j.get("usage", {}).get("completion_tokens_details", {}).get("reasoning_tokens", 0)
    return content, rt


# ── CLI ───────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--temps",
        default="0.7,0.85,0.95",
        help="Comma-separated temperatures, one candidate per temp (default: 0.7,0.85,0.95)",
    )
    ap.add_argument(
        "--model",
        default="deepseek-v4-pro",
        choices=["deepseek-v4-pro", "deepseek-v4-flash"],
        help="DeepSeek model (default: deepseek-v4-pro — slower + smarter)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Save the drafts to this markdown file (in addition to stdout)",
    )
    ap.add_argument(
        "--json",
        type=Path,
        default=None,
        dest="json_out",
        help=(
            "Save drafts as JSON for the email pipeline to consume. "
            "Typical: --json data/.editor_drafts.json (gitignored). "
            "Schema: {generated_at, model, drafts: [{index, temp, text, warnings}]}"
        ),
    )
    ap.add_argument(
        "--dump-context",
        action="store_true",
        help="Print the full context blob (useful for debugging the prompt)",
    )
    args = ap.parse_args(argv)

    temps = [float(t.strip()) for t in args.temps.split(",") if t.strip()]
    if not temps:
        raise SystemExit("--temps must contain at least one float")

    ctx = build_context()
    if args.dump_context:
        print(ctx)
        return 0

    print(f"# Editor's note drafts · {dt.datetime.now(dt.UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"# Model: {args.model}  ·  Context: {len(ctx):,} chars")
    print()

    drafts: list[tuple[float, str, int, list[str]]] = []
    for i, temp in enumerate(temps, 1):
        print(f"[{i}/{len(temps)}] {args.model} · temp={temp} ...", file=sys.stderr, flush=True)
        text, reasoning_tokens = call_deepseek(args.model, temp, ctx)
        warns = lint(text)
        drafts.append((temp, text, reasoning_tokens, warns))

    print("\n" + "═" * 72)
    print("  CANDIDATES")
    print("═" * 72)
    for i, (temp, text, rt, warns) in enumerate(drafts, 1):
        status = "✓ 干净" if not warns else f"✗ {len(warns)} 处警告"
        print(f"\n━━━ #{i} · temp={temp} · 思考 {rt} tokens · {status} ━━━\n")
        print(text)
        if warns:
            print()
            for w in warns:
                print(f"  ⚠ {w}")

    if args.out:
        # Resolve to absolute so relative_to(REPO_ROOT) works regardless of
        # which directory the user invoked the script from.
        out_path = args.out.resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            f.write(f"# Editor's note drafts · {dt.datetime.now(dt.UTC).strftime('%Y-%m-%d %H:%M UTC')}\n")
            f.write(f"\nModel: `{args.model}` · Context: {len(ctx):,} chars\n\n")
            for i, (temp, text, rt, warns) in enumerate(drafts, 1):
                status = "✓ 干净" if not warns else f"✗ {len(warns)} 处警告"
                f.write(f"\n## #{i} · temp={temp} · 思考 {rt} tokens · {status}\n\n")
                f.write(text + "\n")
                if warns:
                    f.write("\n**Lint warnings:**\n")
                    for w in warns:
                        f.write(f"- {w}\n")
        try:
            rel = out_path.relative_to(REPO_ROOT)
            print(f"\nSaved to {rel}")
        except ValueError:
            print(f"\nSaved to {out_path}")

    if args.json_out:
        # JSON output — consumed by scraper/email_notify.py to render the
        # Beta editor's-note section at the bottom of the email + archive.
        json_path = args.json_out.resolve()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "model": args.model,
            "context_chars": len(ctx),
            "drafts": [
                {
                    "index": i,
                    "temp": temp,
                    "text": text,
                    "reasoning_tokens": rt,
                    "warnings": warns,
                }
                for i, (temp, text, rt, warns) in enumerate(drafts, 1)
            ],
        }
        json_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            print(f"JSON saved to {json_path.relative_to(REPO_ROOT)}")
        except ValueError:
            print(f"JSON saved to {json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
