#!/usr/bin/env python3
"""Refresh known catalog through the canonical pipeline; never sends email.

Use a separate checkout/output directory for diagnostics. No historical deletion.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    from scraper import run
    # Same merge, observation timestamps, deltas, health, website and archives.
    # No discovery network request is necessary for catalog-only recovery.
    run.crawl_discover = lambda: {}
    return run.run()


if __name__ == "__main__":
    sys.exit(main())
