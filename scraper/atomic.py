"""Atomic-write helper.

If the scraper crashes or the GH Actions runner gets killed mid-write,
we don't want a half-written `data/projects.json` that breaks downstream
readers (the live site, email_notify, sanity gate). Solution: write to
a sibling temp file and `os.replace()` over the target — POSIX guarantees
that operation is atomic on the same filesystem. Reader either sees the
old file or the new file, never half of one.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_text_atomic(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write `content` to `path` atomically.

    Implementation: write to <path>.tmp.<pid>, fsync, rename → target.
    Same directory so rename is intra-fs (atomic on Linux/macOS).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # NamedTemporaryFile in the same dir keeps the rename atomic (cross-fs
    # rename is not atomic). delete=False so we can rename it ourselves.
    fd = tempfile.NamedTemporaryFile(
        mode="w",
        encoding=encoding,
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        fd.write(content)
        fd.flush()
        os.fsync(fd.fileno())
        fd.close()
        os.replace(fd.name, str(path))
    except Exception:
        # Best-effort cleanup of stranded temp file
        try:
            os.unlink(fd.name)
        except OSError:
            pass
        raise


def write_json_atomic(path: Path, obj: Any, *, indent: int = 2) -> None:
    """JSON-encode `obj` and write atomically. Defaults to indent=2."""
    write_text_atomic(
        path,
        json.dumps(obj, ensure_ascii=False, indent=indent) + "\n",
    )


def versioned_text_path(path: Path, content: str) -> Path:
    """Keep the first dated edition; identical reruns reuse their revision."""
    if not path.exists() or path.read_text(encoding="utf-8") == content:
        return path
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    return path.with_name(f"{path.stem}-revision-{digest}{path.suffix}")


def write_versioned_text(path: Path, content: str) -> Path:
    target = versioned_text_path(path, content)
    if target.exists():
        if target.read_text(encoding="utf-8") != content:
            raise ValueError("edition revision collision; refusing to overwrite")
    else:
        write_text_atomic(target, content)
    return target
