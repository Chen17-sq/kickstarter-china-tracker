#!/usr/bin/env python3
"""Generate CHANGELOG.md from git history — non-snapshot commits only.

The repo's `CHANGELOG.md` at root is OVERWRITTEN every cron with the
diff-vs-previous-snapshot (scraper/diff.py). This script generates a
SEPARATE human-readable changelog of code/feature commits — skipping
the "snapshot YYYY-MM-DDTHH-MM-SSZ" commits the cron emits.

Output: docs/CHANGELOG_features.md

Run manually before tagging a release:
    python scripts/gen_changelog.py

Or wire to a release-tag workflow. Until then it's manual / on-demand.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "docs" / "CHANGELOG_features.md"

# Skip commits matching these patterns — they're either auto-generated
# (snapshot ...) or low-signal (merge, typo).
SKIP_RE = re.compile(
    r"^(snapshot \d{4}-\d{2}-\d{2}|Merge |merge |Initial commit)",
    re.IGNORECASE,
)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(REPO_ROOT),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def parse_log() -> list[dict]:
    """Read git log, return list of {hash, date, subject, body}."""
    # %H short hash · %as ISO date (committer) · %s subject · %b body
    # Use \x1f (unit separator) between fields, \x1e between commits
    raw = git(
        "log",
        "--pretty=format:%h%x1f%as%x1f%s%x1f%b%x1e",
        "--no-merges",
    )
    out = []
    for entry in raw.split("\x1e"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("\x1f")
        if len(parts) < 3:
            continue
        h, date, subject = parts[0], parts[1], parts[2]
        body = parts[3] if len(parts) > 3 else ""
        if SKIP_RE.search(subject):
            continue
        out.append({"hash": h, "date": date, "subject": subject, "body": body.strip()})
    return out


def main() -> int:
    commits = parse_log()
    if not commits:
        print("No commits found", file=sys.stderr)
        return 1

    # Group by month (YYYY-MM)
    by_month: dict[str, list[dict]] = {}
    for c in commits:
        month = c["date"][:7]
        by_month.setdefault(month, []).append(c)

    months_sorted = sorted(by_month.keys(), reverse=True)

    lines: list[str] = []
    lines.append("# Changelog · Feature history")
    lines.append("")
    lines.append("Auto-generated from `git log` (excluding daily cron snapshots).")
    lines.append("Run `python scripts/gen_changelog.py` to refresh.")
    lines.append("")

    for month in months_sorted:
        lines.append(f"## {month}")
        lines.append("")
        for c in by_month[month]:
            lines.append(f"- **{c['date']}** ([`{c['hash']}`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/{c['hash']})) — {c['subject']}")
        lines.append("")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)} ({len(commits)} commits across {len(months_sorted)} month(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
