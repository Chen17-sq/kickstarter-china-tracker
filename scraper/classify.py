"""Decide whether a project counts as "China-background"."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
BRANDS_FILE = REPO_ROOT / "brands" / "china_brands.yaml"

CHINA_LOCATION_TOKENS = {
    "China", "Hong Kong", "Taiwan", "Macau", "Macao",
    "Shenzhen", "Shanghai", "Beijing", "Guangzhou", "Chengdu",
    "Hangzhou", "Suzhou", "Nanjing", "Tianjin", "Wuhan",
    "Kowloon", "Zhuhai", "Xiamen", "Dongguan",
}


@dataclass
class ClassifyResult:
    confidence: str   # 高 / 中 / 低 / 未知
    reason: str
    matched_brand: str | None = None


def _load_brands() -> dict:
    with BRANDS_FILE.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


_BRANDS_CACHE: dict | None = None
def brands() -> dict:
    global _BRANDS_CACHE
    if _BRANDS_CACHE is None:
        _BRANDS_CACHE = _load_brands()
    return _BRANDS_CACHE


def classify(*, creator_slug: str | None, location: str | None,
             title: str | None = None) -> ClassifyResult:
    """Three-tier rules — see brands/china_brands.yaml."""
    b = brands()

    # 1. Brand whitelist hit (highest priority — covers brands listed in US)
    for entry in b.get("high_confidence", []):
        slugs = entry.get("creator_slugs") or []
        if creator_slug and creator_slug in slugs:
            return ClassifyResult("高", f"brand whitelist: {entry['brand']}", entry["brand"])
        if title and entry["brand"].lower() in (title or "").lower():
            return ClassifyResult("高", f"brand name in title: {entry['brand']}", entry["brand"])

    # 2. KS-reported location is China
    if location:
        for tok in CHINA_LOCATION_TOKENS:
            if tok.lower() in location.lower():
                return ClassifyResult("高", f"KS location: {location}")

    # 3. Medium confidence whitelist
    for entry in b.get("medium_confidence", []):
        slugs = entry.get("creator_slugs") or []
        if creator_slug and creator_slug in slugs:
            return ClassifyResult("中", entry.get("reason", "medium-confidence list"), entry["brand"])

    # 4. Explicit blacklist
    for entry in b.get("not_china", []):
        slugs = entry.get("creator_slugs") or []
        if creator_slug and creator_slug in slugs:
            return ClassifyResult("否", f"blacklisted: {entry['brand']}", entry["brand"])

    return ClassifyResult("未知", "no rule matched")


if __name__ == "__main__":
    import sys
    slug = sys.argv[1] if len(sys.argv) > 1 else "xlean"
    loc = sys.argv[2] if len(sys.argv) > 2 else None
    print(classify(creator_slug=slug, location=loc))
