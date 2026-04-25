"""Auto-translate missing Chinese product blurbs via the Anthropic API.

For every China-background row whose pathname isn't already in
data/blurbs_zh.json, asks Claude Haiku 4.5 to write a one-line Chinese
product description. Manual entries (already in the cache) are NEVER
overwritten — auto-translation only fills gaps.

Each cron run typically translates 0–10 brand-new prelaunch listings,
costing pennies (Haiku + prompt-cached system prompt = ~$0.001/call).

Required env: ANTHROPIC_API_KEY (set as a GitHub Actions repo secret).
If unset, this step is a silent no-op so the rest of the pipeline keeps
working without it.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BLURBS = REPO_ROOT / "data" / "blurbs_zh.json"

# Latest Haiku — fast and cheap. The 4.6 series has no Haiku yet (as of 2026-04).
MODEL = "claude-haiku-4-5-20251001"

SYSTEM = """You translate English Kickstarter project info into a single Simplified Chinese sentence (8-28 chars) that explains *what the product is* — not its category, not marketing fluff. Lead with the product type; add 1-2 distinctive features in parentheses if helpful.

Style examples (match this register):
- 4K 三色激光投影仪（双虹膜光圈 + VRR）
- 安卓掌机 + 手机二合一（侧滑实体按键）
- 冰箱专用静音备用电源（断电自动接管）
- 桌面五轴联动 CNC 雕铣机（20000RPM）
- 全自动水洗式 AI 智能猫砂盆
- 末日废土题材角色扮演冒险游戏

Output ONLY the Chinese sentence. No prefix, no quotes, no English, no explanation, no trailing punctuation."""


def load_cache() -> dict:
    if BLURBS.exists():
        try:
            return json.loads(BLURBS.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def write_cache(cache: dict) -> None:
    """Write with _meta first, all other keys sorted alphabetically.

    Stable ordering keeps diffs small as new entries are appended over time.
    """
    out: dict = {}
    if "_meta" in cache:
        out["_meta"] = cache["_meta"]
    for k in sorted(k for k in cache if k != "_meta"):
        out[k] = cache[k]
    BLURBS.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _clean(text: str) -> str:
    """Strip quotes, fences, trailing punct that the model sometimes adds."""
    t = text.strip()
    for ch in ('"', "'", "「", "」", "『", "』", "“", "”", "‘", "’"):
        t = t.strip(ch)
    t = t.strip().rstrip("。.")
    return t.strip()


def translate_one(client, title: str, blurb: str, category: str) -> str:
    user = f"Title: {title}\nDescription: {blurb}\nCategory: {category}"
    resp = client.messages.create(
        model=MODEL,
        max_tokens=128,
        system=[
            {"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user", "content": user}],
    )
    text_parts = []
    for block in resp.content:
        if hasattr(block, "text"):
            text_parts.append(block.text)
    return _clean("".join(text_parts))


def fill_missing(rows: list[dict]) -> int:
    """For every China-bg row missing blurb_zh, fetch + cache + write back.

    Mutates `rows` in place: every row that gets a fresh translation has
    its `blurb_zh` field set so the caller can serialise the row to
    projects.json without an extra reload.

    Returns the number of new translations actually written.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  ANTHROPIC_API_KEY not set — auto-translate skipped")
        return 0
    try:
        from anthropic import Anthropic
    except ImportError:
        print("  anthropic SDK not installed — auto-translate skipped")
        return 0

    cache = load_cache()
    targets = [
        r for r in rows
        if r.get("china_confidence") in ("高", "中")
        and r.get("pathname") and r["pathname"] not in cache
        and (r.get("blurb") or r.get("title"))
    ]
    if not targets:
        print("  no missing zh blurbs to translate")
        return 0

    print(f"  auto-translating {len(targets)} blurbs via {MODEL} …")
    client = Anthropic(api_key=api_key)
    new = 0
    for r in targets:
        try:
            zh = translate_one(
                client,
                r.get("title") or "",
                r.get("blurb") or "",
                r.get("category") or "",
            )
            if zh and 4 <= len(zh) <= 80:
                cache[r["pathname"]] = zh
                r["blurb_zh"] = zh
                new += 1
                print(f"    + {r.get('title','?')[:50]} → {zh}")
            else:
                print(f"    ! {r.get('pathname')} returned unusable: {zh!r}")
        except Exception as e:
            print(f"    ! {r.get('pathname')} translate failed: {e}")

    if new > 0:
        write_cache(cache)
        print(f"  wrote {new} new zh blurbs to {BLURBS.relative_to(REPO_ROOT)}")
    return new


if __name__ == "__main__":
    # Standalone smoke test: load current projects.json, attempt translation.
    import sys
    proj_path = REPO_ROOT / "data" / "projects.json"
    if not proj_path.exists():
        print("no data/projects.json — run scraper first", file=sys.stderr)
        sys.exit(1)
    data = json.loads(proj_path.read_text(encoding="utf-8"))
    n = fill_missing(data["projects"])
    print(f"done. {n} new translations.")
