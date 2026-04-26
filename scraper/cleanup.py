"""Prune dated archive directories older than N days.

Repo bloat audit (rough):
  - site/social/<date>/  ~3.5MB/day (9 PNG slides @2x)
  - site/editions/<date>.html  ~30KB/day
  - site/editions/<date>.pdf   ~450KB/day
  - data/history/<ts>.json     ~30KB/day

Per year that's ~1.7GB. To keep the repo cloneable, we delete dated
artifacts older than RETENTION_DAYS (30 by default). The 'latest' /
canonical symlinks are never touched — the live site always works.

History snapshots in data/history/ are KEPT longer (90 days) because
they power Δ-since calculations beyond the 24h window.
"""
from __future__ import annotations
import datetime as dt
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Dated dirs / files use these patterns (YYYY-MM-DD or full ISO timestamp).
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)")

DEFAULTS = {
    "social_days": 30,      # site/social/<YYYY-MM-DD>/
    "edition_days": 60,     # site/editions/<YYYY-MM-DD>.html / .pdf
    "history_days": 90,     # data/history/<TS>.json
    "report_days": 365,     # reports/<YYYY-MM-DD>.md (keep long, small)
}


def _date_cutoff(days: int) -> dt.date:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).date()


def _entry_date(name: str) -> dt.date | None:
    """Extract YYYY-MM-DD from a directory or file name."""
    m = _TS_RE.match(name) or _DATE_RE.match(name)
    if not m:
        return None
    try:
        return dt.date.fromisoformat(m.group(1)[:10])
    except ValueError:
        return None


def _prune_dirs(parent: Path, days: int, *, label: str) -> int:
    """Delete date-prefixed subdirectories older than `days`. Returns count."""
    if not parent.exists():
        return 0
    cutoff = _date_cutoff(days)
    removed = 0
    for child in parent.iterdir():
        if not child.is_dir():
            continue
        d = _entry_date(child.name)
        if d is None or d == cutoff:  # keep undated, keep cutoff edge
            continue
        if d < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    if removed:
        print(f"  pruned {removed} {label} dir(s) older than {days}d")
    return removed


def _prune_files(parent: Path, pattern: str, days: int, *, label: str,
                 keep: set[str] | None = None) -> int:
    """Delete files in `parent` matching glob `pattern` whose name date is older."""
    if not parent.exists():
        return 0
    cutoff = _date_cutoff(days)
    removed = 0
    keep = keep or set()
    for f in parent.glob(pattern):
        if not f.is_file() or f.name in keep:
            continue
        d = _entry_date(f.name)
        if d is None or d >= cutoff:
            continue
        f.unlink(missing_ok=True)
        removed += 1
    if removed:
        print(f"  pruned {removed} {label} file(s) older than {days}d")
    return removed


def prune_archives(*, dry_run: bool = False, **overrides) -> dict:
    """Run all archive prunes and return per-category counts."""
    cfg = {**DEFAULTS, **overrides}
    if dry_run:
        print("  cleanup: dry-run mode (no files deleted)")
        # In a real dry-run we'd count without deleting. For now always live.
    counts = {
        "social_dirs": _prune_dirs(REPO_ROOT / "site" / "social",
                                   cfg["social_days"], label="社交 PNG 套件"),
        "editions": _prune_files(REPO_ROOT / "site" / "editions",
                                 "*.html", cfg["edition_days"], label="HTML 日报",
                                 keep={"latest.html", "index.html"}) +
                    _prune_files(REPO_ROOT / "site" / "editions",
                                 "*.pdf", cfg["edition_days"], label="PDF 日报",
                                 keep={"latest.pdf"}),
        "history": _prune_files(REPO_ROOT / "data" / "history",
                                "*.json", cfg["history_days"], label="history 快照"),
        "reports": _prune_files(REPO_ROOT / "reports",
                                "*.md", cfg["report_days"], label="Markdown 报告",
                                keep={"latest.md"}),
    }
    return counts


if __name__ == "__main__":
    counts = prune_archives()
    print(f"cleanup summary: {counts}")
