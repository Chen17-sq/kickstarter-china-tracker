"""Diff two snapshots → human-readable changelog (and JSON change events)."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Iterable
import json
from pathlib import Path


@dataclass
class Change:
    pathname: str
    title: str
    kind: str          # new | status_change | followers_delta | backers_delta | ended
    detail: str


def _by_path(snapshot: dict) -> dict[str, dict]:
    return {p["pathname"]: p for p in snapshot.get("projects", []) if p.get("pathname")}


def diff_snapshots(prev: dict, curr: dict) -> list[Change]:
    out: list[Change] = []
    a, b = _by_path(prev), _by_path(curr)

    # New
    for path in b.keys() - a.keys():
        p = b[path]
        out.append(Change(path, p.get("title", ""), "new",
                          f"Discovered ({p.get('status', '?')}, {p.get('followers') or 0} followers)"))

    # Removed = ended/archived
    for path in a.keys() - b.keys():
        p = a[path]
        out.append(Change(path, p.get("title", ""), "ended",
                          f"No longer in discovery (likely ended)"))

    # Compare overlapping
    for path in a.keys() & b.keys():
        ap, bp = a[path], b[path]

        if ap.get("status") != bp.get("status"):
            out.append(Change(path, bp.get("title", ""), "status_change",
                              f"{ap.get('status')} → {bp.get('status')}"))

        af, bf = ap.get("followers") or 0, bp.get("followers") or 0
        if isinstance(af, int) and isinstance(bf, int) and bf - af >= 50:
            out.append(Change(path, bp.get("title", ""), "followers_delta",
                              f"+{bf - af} followers ({af} → {bf})"))

        ab, bb = ap.get("backers") or 0, bp.get("backers") or 0
        if isinstance(ab, int) and isinstance(bb, int) and bb - ab >= 100:
            out.append(Change(path, bp.get("title", ""), "backers_delta",
                              f"+{bb - ab} backers ({ab} → {bb})"))

    return out


def changes_to_markdown(changes: Iterable[Change]) -> str:
    lines = ["# Kickstarter China Tracker — diff"]
    by_kind: dict[str, list[Change]] = {}
    for c in changes:
        by_kind.setdefault(c.kind, []).append(c)
    for kind, items in by_kind.items():
        lines.append(f"\n## {kind} ({len(items)})")
        for c in items[:50]:
            lines.append(f"- **{c.title}** — {c.detail}  \n  `{c.pathname}`")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    prev = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    curr = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    diffs = diff_snapshots(prev, curr)
    print(changes_to_markdown(diffs))
