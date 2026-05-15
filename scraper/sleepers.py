"""Sleeper of the Day — algorithmic picks of interesting projects NOT in Top 10.

The Top 10 (by watchers / USD) is what every reader sees on the front page.
Sleepers are the alpha — projects you'd find if you actually scrolled past
the obvious picks. We score every non-Top-10 project across two axes and
emit the top N (default 5), each tagged with a single editorial "why" line.

Two scoring axes
────────────────
  (A) METRIC SIGNALS  — momentum-y stuff visible in the numbers:
        hidden_hot      funded% > 500%   AND  pledged < $100K
        acceleration    Δpledged_24h is > 20% of cumulative pledged
        early_traction  live + Δbackers ≥ 50 (24h)
        watcher_surge   prelaunch + Δfollowers ≥ 30 (24h)
        just_crossed    live + 100% ≤ funded < 200%
        cold_pick       low watchers + KS Editor's Pick (PWL)

  (B) NOVELTY SIGNALS — content-side signals from title/blurb keyword hits:
        AI 硬件        any AI / agentic / LLM / neural / smart-glasses term
        机器人         humanoid / robot arm / quadruped / robotics
        全球首款        world's first / 首款 / 业内首
        新材料         graphene / nano / aerogel / 石墨烯 / 纳米
        新声学         MEMS / tribrid / planar magnetic
        开源 / DIY      open-source / hackable / SBC
        智能家居 · 可穿戴   smart home / smartwatch / smart ring

Why both? Old (v1) sleeper used only momentum, so picks were "biggest grower"
not "most interesting". Adding content signals lets a 50-follower AI dev
board outrank a 1500-follower "5th titanium keychain knife this week".

Editorial reason line
─────────────────────
Each project gets a single "WHY" line composed of:
  <novelty label if any> · <metric headline>
e.g. "AI 硬件 · 24h +30 watchers", "全球首款 · 小盘高溢价 12× / $42K"

Reason templates are varied (3 phrasings per bucket); the picker is
deterministic per project pathname so the same project shows the same
phrasing in email / markdown / HTML / social cards.

Output: list of project dicts with two extra keys:
  _sleeper_score   — int, higher = more interesting
  _sleeper_reason  — human-readable single-line tag (zh)
"""
from __future__ import annotations
import re
from typing import Iterable

# ── Novelty keyword table ─────────────────────────────────────────────
# Each row: (score, label, pattern). Patterns are case-insensitive. A project
# gets credit for at most ONE label from each row (deduped), so a project
# saying "AI" three times doesn't compound. Score is added; label of the
# highest-scoring hit becomes the headline.
#
# Edit policy: tighten patterns rather than loosen — false positives on
# "AI" (Adobe Illustrator, etc.) are worse than missing one true positive.
# Boundary anchors (\b) keep "AI" from matching "PAID" or "RAID".
_NOVELTY = [
    # — Top tier (140): explicit AI hardware. These almost always deserve a look.
    (140, "AI 硬件",      r"\b(ai[-\s]?(powered|driven|assistant|agent|companion|enabled|native)|agentic|on[-\s]?device ai|edge ai)\b"),
    (140, "AI 硬件",      r"\b(smart\s?glasses|ai\s?glasses|ar\s?glasses|ai\s?pin|ai\s?necklace|ai\s?pendant|ai\s?wearable)\b"),
    (140, "AI 硬件",      r"\b(generative ai|neural\s?network|large\s?language\s?model|\bllm\b|\bgpt[-\s]?\d|claude|gemini\s?nano)\b"),
    # — Second tier (130): robotics + bare-bones AI claim.
    (130, "机器人",       r"\b(humanoid|robotic\s?arm|robot\s?dog|quadruped|biped|robotic\s?gripper|cobot)\b"),
    (110, "机器人",       r"\brobot(s|ic|ics|ically)?\b"),
    (110, "AI 标签",      r"\b(ai|artificial intelligence)\b"),
    # — Novelty claims (100): "first of its kind" framing.
    (100, "全球首款",     r"(world'?s\s?first|first[-\s]of[-\s]its[-\s]kind|industry[-\s]first|first[-\s]ever)"),
    (100, "全球首款",     r"(首款|首个|全球首|业内首|世界首)"),
    # — Technical novelty (80): novel materials + novel acoustics.
    (80,  "新材料",       r"\b(graphene|nano(?:wire|tube|fiber)?|carbon\s?fiber|aerogel|biotech|bioplastic)\b"),
    (80,  "新材料",       r"(石墨烯|纳米|气凝胶|生物科技|碳纤维)"),
    (80,  "新声学",       r"\b(mems\s?driver?|tribrid|planar\s?magnetic|electrostatic\s?driver|hybrid\s?driver|isobaric)\b"),
    # — Long-tail edge (50-60).
    (60,  "开源",         r"\b(open[-\s]?source|fully[-\s]?hackable)\b|开源"),
    (60,  "Maker 板",     r"\b(sbc|single\s?board\s?computer|raspberry\s?pi|esp32|esp8266|rp2040|stm32|cortex[-\s]m)\b"),
    (50,  "智能家居",     r"\b(smart\s?home|smart\s?kitchen|smart\s?garden|smart\s?aquarium|matter[-\s]over[-\s]thread)\b"),
    (50,  "可穿戴",       r"\b(smartwatch|smart\s?ring|fitness\s?band|wearable\s?device|biosensor)\b"),
    (50,  "电动出行",     r"\b(e[-\s]?bike|e[-\s]?scooter|ebike|electric\s?skateboard|escooter|electric\s?moped)\b"),
]
_NOVELTY_RE = [(score, label, re.compile(pat, re.IGNORECASE)) for score, label, pat in _NOVELTY]


# ── Reason phrasing pools — 3 variations per bucket ───────────────────
# Each phrasing is a callable taking the local vars dict and returning the
# rendered string. The picker uses hash(pathname) % len so each project
# gets a deterministic but varied phrasing across renderers.

_HIDDEN_HOT = [
    lambda v: f"小盘高溢价 · {v['funded']/100:.0f}× / ${v['pledged']/1000:.0f}K",
    lambda v: f"{v['funded']/100:.0f} 倍超募 · 总盘仅 ${v['pledged']/1000:.0f}K",
    lambda v: f"超募 {v['funded']/100:.0f}× · 小众粉丝盘 ${v['pledged']/1000:.0f}K",
]
_ACCELERATION = [
    lambda v: f"24h 加速 · 单日 +{v['pct']:.0f}% 募资",
    lambda v: f"+${v['delta_p']/1000:.1f}K（占累计 {v['pct']:.0f}%）单日新增",
    lambda v: f"今日新增 ${v['delta_p']/1000:.1f}K · {v['pct']:.0f}% 增速",
]
_EARLY_TRACTION = [
    lambda v: f"24h +{v['delta_b']} backers",
    lambda v: f"过去一天涌入 {v['delta_b']} 位 backer",
    lambda v: f"势头起来 · 单日 +{v['delta_b']} backers",
]
_WATCHER_SURGE = [
    lambda v: f"24h +{v['delta_f']} watchers",
    lambda v: f"昨日新增 {v['delta_f']} 位 watcher",
    lambda v: f"预热加速 · 单日 +{v['delta_f']} watchers",
]
_JUST_CROSSED = [
    lambda v: f"刚过目标 · {v['funded']:.0f}%",
    lambda v: f"擦线达成 · {v['funded']:.0f}%（还有上升空间）",
    lambda v: f"达成临界点 · {v['funded']:.0f}%",
]
_COLD_PICK_PRELAUNCH = [
    lambda v: f"KS 编辑挑了，但只有 {v['watchers']} watcher",
    lambda v: f"被打 KS Pick 标，关注还少（仅 {v['watchers']}）",
    lambda v: f"低关注度的 KS Pick · 仅 {v['watchers']} watcher",
]
_COLD_PICK_LIVE = [
    lambda v: f"KS Pick 但 watchers 只有 {v['watchers']}",
    lambda v: f"评分高（KS Pick）但热度未起 · {v['watchers']} watchers",
    lambda v: f"被忽略的 KS Pick · 仅 {v['watchers']} watchers",
]


def _num(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _pick_phrasing(seed: str, options: list) -> str:
    """Deterministic phrasing pick — same seed → same phrasing every render."""
    if not options:
        return ""
    # Python's built-in hash() is salted per-process; use a stable hash so
    # email / markdown / social cards rendered in different runs (or even
    # different processes of the same day) still agree.
    h = 0
    for ch in seed:
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    return options[h % len(options)](_PHRASING_CTX)


# Mutable context dict for the phrasing lambdas. Set inside _score_one
# before each lookup so lambdas can read the project's numbers without
# us passing every variable through. Single-threaded so this is fine.
_PHRASING_CTX: dict = {}


def _novelty_hits(p: dict) -> list[tuple[int, str]]:
    """Search title+blurb+blurb_zh for novelty signals. Returns sorted
    list of (score, label), highest score first, deduped by label."""
    text = " ".join(
        s for s in (
            p.get("title") or "",
            p.get("blurb") or "",
            p.get("blurb_zh") or "",
        ) if s
    )
    hits: list[tuple[int, str]] = []
    seen_labels: set[str] = set()
    for score, label, regex in _NOVELTY_RE:
        if label in seen_labels:
            continue
        if regex.search(text):
            hits.append((score, label))
            seen_labels.add(label)
    hits.sort(key=lambda x: -x[0])
    return hits


def _score_one(p: dict) -> tuple[int, str]:
    """Score a single project. Returns (score, reason_line).
    A project can hit multiple buckets — we compose the most striking
    novelty label with the most striking metric reason into one line."""
    funded = _num(p.get("percent_funded"))
    pledged = _num(p.get("pledged_usd"))
    delta_p = _num(p.get("delta_pledged_usd"))
    delta_b = int(_num(p.get("delta_backers")))
    delta_f = int(_num(p.get("delta_followers")))
    watchers = int(_num(p.get("followers")))
    status = p.get("status") or ""
    pwl = bool(p.get("project_we_love"))
    seed = p.get("pathname") or p.get("title") or ""

    score = 0
    # Bind into the module-level context so phrasing lambdas can read locals
    _PHRASING_CTX.clear()
    _PHRASING_CTX.update(
        funded=funded, pledged=pledged, delta_p=delta_p, delta_b=delta_b,
        delta_f=delta_f, watchers=watchers,
        pct=(delta_p / pledged * 100) if pledged > 0 else 0,
    )

    # ── Novelty axis (content signals)
    novelty_label = ""
    for nov_score, label in _novelty_hits(p):
        score += nov_score
        if not novelty_label:
            novelty_label = label  # headline = highest-scored hit

    # ── Metric axis. Each bucket adds score + possibly a metric phrasing.
    # We pick ONE metric phrasing — the most striking — to put after the
    # novelty label. (Order = priority; first hit wins.)
    metric_phrase = ""

    # hidden_hot — small-cap, high-funded
    if funded > 500 and 0 < pledged < 100_000:
        score += 100
        if not metric_phrase:
            metric_phrase = _pick_phrasing(seed, _HIDDEN_HOT)

    # acceleration — strong single-day pop relative to total
    if pledged > 0 and delta_p > pledged * 0.20:
        score += 80
        if not metric_phrase:
            metric_phrase = _pick_phrasing(seed, _ACCELERATION)

    # early_traction — live with strong backer day
    if status == "live" and delta_b >= 50:
        score += 60
        if not metric_phrase:
            metric_phrase = _pick_phrasing(seed, _EARLY_TRACTION)

    # watcher_surge — prelaunch with strong follower day
    if status == "prelaunch" and delta_f >= 30:
        score += 60
        if not metric_phrase:
            metric_phrase = _pick_phrasing(seed, _WATCHER_SURGE)

    # just_crossed — live past goal but not blown up yet
    if status == "live" and 100 <= funded < 200:
        score += 40
        if not metric_phrase:
            metric_phrase = _pick_phrasing(seed, _JUST_CROSSED)

    # cold_pick — KS Pick with low audience
    if pwl and watchers < 500 and status == "prelaunch":
        score += 50
        if not metric_phrase:
            metric_phrase = _pick_phrasing(seed, _COLD_PICK_PRELAUNCH)
    elif pwl and watchers < 500 and status == "live":
        score += 50
        if not metric_phrase:
            metric_phrase = _pick_phrasing(seed, _COLD_PICK_LIVE)

    # ── Compose the reason line.
    # Combinations we want:
    #   novelty + metric         → "AI 硬件 · 24h +30 watchers"
    #   novelty alone            → "AI 硬件"
    #   metric alone             → "刚过目标 · 105%"
    #   nothing                  → "" (filtered out upstream)
    if novelty_label and metric_phrase:
        reason = f"{novelty_label} · {metric_phrase}"
    elif novelty_label:
        reason = novelty_label
    elif metric_phrase:
        reason = metric_phrase
    else:
        reason = ""

    return score, reason


def select_sleepers(
    projects: Iterable[dict],
    exclude_pathnames: set[str],
    n: int = 5,
) -> list[dict]:
    """Pick N projects worth surfacing. Returns shallow-cloned dicts with
    `_sleeper_score` and `_sleeper_reason` keys added.

    `exclude_pathnames` should be the set of pathnames already shown in
    Top 10 prelaunch + Top 10 live + Top 10 successful — so sleepers are
    truly distinct from the front-page picks.

    Diversity rules (in order, both soft-capped at 3):
      1. Max 3 sleepers per status bucket (prelaunch / live / successful).
      2. Max 3 sleepers per novelty label — so we don't pick 5 AI projects
         even if AI is having a great week. Cap raised from 2 → 3 because
         on slow scrape days (<100 projects) the stricter cap left fewer
         than `n` qualified picks; 3 is the sweet spot between editorial
         variety and "fill the slate".
    """
    scored: list[tuple[int, str, dict]] = []
    for p in projects:
        if p.get("pathname") in exclude_pathnames:
            continue
        score, reason = _score_one(p)
        if score <= 0 or not reason:
            continue
        scored.append((score, reason, p))

    # Highest-scoring first
    scored.sort(key=lambda t: -t[0])

    novelty_labels = {lbl for _, lbl, _ in _NOVELTY}
    out: list[dict] = []
    by_status: dict[str, int] = {}
    by_novelty: dict[str, int] = {}
    for score, reason, p in scored:
        st = p.get("status") or "unknown"
        if by_status.get(st, 0) >= 3:
            continue
        # Extract novelty label (first segment before " · ") for diversity check
        nov_label = reason.split(" · ", 1)[0] if " · " in reason else reason
        # Only cap if the reason starts with a known novelty label
        if nov_label in novelty_labels:
            if by_novelty.get(nov_label, 0) >= 3:
                continue
            by_novelty[nov_label] = by_novelty.get(nov_label, 0) + 1
        by_status[st] = by_status.get(st, 0) + 1

        # Shallow clone + annotate
        q = dict(p)
        q["_sleeper_score"] = score
        q["_sleeper_reason"] = reason
        out.append(q)
        if len(out) >= n:
            break

    return out
