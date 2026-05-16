"""Brand auto-discovery — surface high-signal unknown creators for review.

The classifier (scraper/classify.py) has 4 buckets: 高 / 中 / 否 / 未知.
"未知" means we don't have a rule for that creator. The point of this
module is to find the SUBSET of 未知 projects that look interesting
enough to be worth manually reviewing for `china_brands.yaml`.

Signal heuristics (any one qualifies):
  - followers >= FOLLOWERS_THRESHOLD (default 200)
  - pledged_usd >= PLEDGED_USD_THRESHOLD (default 5_000)
  - project_we_love (KS curator endorsement is itself signal)

We further restrict to projects whose KS-reported `country` is one of
CHINA_COUNTRIES — projects from other countries are noise unless we
explicitly want to expand scope.

Output: data/.brand_candidates.json — gitignored, refreshed each run.
OPS digest in email_notify reads it to show owner "5 unknown candidates
worth reviewing" with creator slugs they can paste into the YAML.

Why this matters:
  Today, classifier coverage is ~36 projects via brand whitelist + ~200
  via KS location. New Chinese brands that incorporate in the US
  ("AYANEO LLC, Wilmington DE") fall through location-based detection
  and need manual addition. This module finds them automatically so
  the YAML grows organically with the catalog.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = REPO_ROOT / "data" / ".brand_candidates.json"

# Thresholds — keep deliberately low so we err on surfacing too many
# rather than missing real candidates. Owner can downgrade by ignoring.
FOLLOWERS_THRESHOLD = 200
PLEDGED_USD_THRESHOLD = 5_000

# KS reports country codes ("CN", "HK", "TW", etc.). We include the
# Greater China set; if a US-registered Chinese brand reports "US",
# it'll fall through to NOT-china-territory and we won't surface it
# (manually reviewed projects are tagged via creator_slugs path).
CHINA_COUNTRIES = {"CN", "HK", "TW", "MO"}


def _num(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def detect(projects: list[dict]) -> dict:
    """Return {'candidates': [...], '_meta': {...}}.

    A candidate dict has:
      creator_slug, title, location, country, status, followers,
      pledged_usd, project_we_love, url, china_confidence (will be '未知'),
      reasons: list[str] explaining why it qualified.
    """
    cands: list[dict] = []
    seen_slugs: set[str] = set()

    for p in projects or []:
        if (p.get("china_confidence") or "") != "未知":
            continue
        country = (p.get("country") or "").upper()
        if country and country not in CHINA_COUNTRIES:
            # Reported non-CN/HK/TW/MO — skip to avoid noise. If it's
            # actually a Chinese brand using a US shell, it'll only
            # surface via the matched-brand path (manual entry).
            continue

        followers = int(_num(p.get("followers")))
        pledged_usd = _num(p.get("pledged_usd"))
        pwl = bool(p.get("project_we_love"))

        reasons: list[str] = []
        if followers >= FOLLOWERS_THRESHOLD:
            reasons.append(f"followers >= {FOLLOWERS_THRESHOLD}")
        if pledged_usd >= PLEDGED_USD_THRESHOLD:
            reasons.append(f"pledged >= ${PLEDGED_USD_THRESHOLD:,.0f}")
        if pwl:
            reasons.append("KS staff pick")
        if not reasons:
            continue

        # Pull creator_slug from pathname (cheap, no separate fetch)
        path = p.get("pathname") or ""
        parts = [s for s in path.split("/") if s]
        creator_slug = parts[1] if len(parts) >= 3 and parts[0] == "projects" else ""
        if not creator_slug or creator_slug in seen_slugs:
            # One row per creator — don't flood the digest with multiple
            # campaigns from the same creator on the same day.
            continue
        seen_slugs.add(creator_slug)

        cands.append({
            "creator_slug": creator_slug,
            "title": p.get("title") or "?",
            "location": p.get("location") or "",
            "country": country,
            "status": p.get("status") or "?",
            "followers": followers,
            "pledged_usd": pledged_usd,
            "project_we_love": pwl,
            "url": p.get("url") or "",
            "china_confidence": p.get("china_confidence") or "未知",
            "reasons": reasons,
        })

    # Sort by descending "interestingness" — staff pick first, then by
    # the strongest signal value
    cands.sort(key=lambda c: (
        -int(c["project_we_love"]),
        -max(c["followers"], int(c["pledged_usd"] / 100)),
    ))

    return {
        "candidates": cands,
        "_meta": {
            "generated_at": dt.datetime.now(dt.UTC).isoformat(),
            "thresholds": {
                "followers": FOLLOWERS_THRESHOLD,
                "pledged_usd": PLEDGED_USD_THRESHOLD,
            },
        },
    }


def save(result: dict) -> Path:
    CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATES_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return CANDIDATES_PATH


def load() -> dict | None:
    if not CANDIDATES_PATH.exists():
        return None
    try:
        return json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def format_digest_lines(result: dict | None) -> list[str]:
    """Plaintext lines for the OPS digest. Empty list if no candidates."""
    if not result:
        return []
    cands = result.get("candidates") or []
    if not cands:
        return []
    out = [f"Brand candidates (高 follower / pledged / staff-pick · {len(cands)} 项 unknown):"]
    for c in cands[:8]:
        star = "★ " if c.get("project_we_love") else "  "
        title = (c.get("title") or "?")[:50]
        followers = c.get("followers") or 0
        pledged = c.get("pledged_usd") or 0
        out.append(
            f"  {star}{title:50}  followers={followers}  pledged=${pledged:,.0f}"
        )
        out.append(f"    creator_slug: {c.get('creator_slug')}  ({c.get('location') or '?'})")
    if len(cands) > 8:
        out.append(f"  …and {len(cands)-8} more in data/.brand_candidates.json")
    out.append("")
    out.append("  → 评估后，把好的 creator_slug 加进 brands/china_brands.yaml")
    return out


if __name__ == "__main__":
    curr = json.loads((REPO_ROOT / "data" / "projects.json").read_text(encoding="utf-8"))
    result = detect(curr.get("projects") or [])
    save(result)
    cands = result["candidates"]
    print(f"  brand candidates: {len(cands)}")
    for c in cands[:10]:
        print(f"    {c['creator_slug']:25}  {c['title'][:45]:45}  {c['followers']:>5}  ${c['pledged_usd']:>8,.0f}")
