"""Webrobots.io Kickstarter dataset — monthly bulk export, CF-free.

Webrobots.io publishes a complete KS project dataset on a monthly
cadence (since March 2016, current run as of 2026-05-12). The
download is a direct S3 URL — no Cloudflare, no rate limit, no
auth. ~600MB uncompressed JSON.

Use case (NOT daily scrape): once-a-month backfill that ensures we
haven't missed long-running prelaunch or already-funded projects
between the gaps in our discover crawl. Particularly useful for:

  - Backfilling historical pledged_usd / backers trajectories on
    projects that were funded BEFORE we started tracking
  - Cross-checking our brand_candidates against full-population
    counts (is "AYANEO" really not yet in brands/china_brands.yaml
    according to the dataset?)
  - Discovering Chinese-creator projects that ran categories we
    don't crawl (Comics, Games, Music — currently filtered out)

Workflow (manual, not cron):
    python -m scraper.webrobots --download   # ~600MB, slow
    python -m scraper.webrobots --enrich     # cross-ref with our data

Output: data/.webrobots/<YYYY-MM-DD>.json — gitignored. Index page
parsed on the fly to find the latest available dump URL.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import re
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / ".webrobots"

INDEX_URL = "https://webrobots.io/kickstarter-datasets/"
# Webrobots provides BOTH .json gzipped and .csv zipped. We use JSON
# because it preserves the nested project structure we care about.
RE_JSON_DUMP = re.compile(
    r'href="(https?://[^"]+Kickstarter[^"]+\.json\.gz)"',
    re.IGNORECASE,
)


def find_latest_dump_url(verbose: bool = True) -> str | None:
    """Scrape the Webrobots index page to find the latest dump URL.

    Returns the full URL to a .json.gz file or None if scraping fails.
    """
    try:
        r = httpx.get(INDEX_URL, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (compatible; ks-tracker-bot/1.0)",
        })
        r.raise_for_status()
    except Exception as e:
        if verbose:
            print(f"  webrobots index fetch failed: {e}")
        return None

    matches = RE_JSON_DUMP.findall(r.text)
    if not matches:
        if verbose:
            print("  webrobots index: no .json.gz links found "
                  "(page structure may have changed)")
        return None
    # The index lists newest-first; take the first match.
    if verbose:
        print(f"  webrobots index: {len(matches)} dumps available; using newest")
    return matches[0]


def download_dump(*, force: bool = False, verbose: bool = True) -> Path | None:
    """Download the latest dump to data/.webrobots/<date>.json (uncompressed).

    Returns the local path or None on failure. Reuses an existing file if
    one already exists from a previous run unless `force=True`.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    out_path = DATA_DIR / f"{today}.json"

    if out_path.exists() and not force:
        size_mb = out_path.stat().st_size / 1024 / 1024
        if verbose:
            print(f"  webrobots dump already on disk: {out_path.name} ({size_mb:.0f} MB)")
        return out_path

    url = find_latest_dump_url(verbose=verbose)
    if not url:
        return None

    if verbose:
        print(f"  webrobots downloading {url} → {out_path.name}")
    try:
        with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
            r.raise_for_status()
            # Webrobots dumps are gzipped. Stream-decompress.
            decompressor = gzip.decompressobj(wbits=gzip.MAX_WBITS | 16)
            with out_path.open("wb") as f:
                for chunk in r.iter_bytes(chunk_size=64 * 1024):
                    f.write(decompressor.decompress(chunk))
                f.write(decompressor.flush())
    except Exception as e:
        if verbose:
            print(f"  webrobots download failed: {e}")
        out_path.unlink(missing_ok=True)
        return None

    size_mb = out_path.stat().st_size / 1024 / 1024
    if verbose:
        print(f"  webrobots dump saved: {out_path.name} ({size_mb:.0f} MB)")
    return out_path


def iter_projects(dump_path: Path):
    """Iterate one project dict at a time from the dump.

    The Webrobots dump is JSON-lines-shaped: one project per line, each
    line a complete JSON object. Streaming-iterate to avoid loading the
    whole ~600MB into memory.
    """
    with dump_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def filter_china_candidates(dump_path: Path) -> list[dict]:
    """Iterate dump, return projects with country=='CN'|'HK'|'TW'|'MO'.

    The dump's schema includes per-project `country` (2-letter code).
    Filtering is fast and gives us a high-recall candidate set for
    cross-checking against our scraped data.
    """
    cn_countries = {"CN", "HK", "TW", "MO"}
    out: list[dict] = []
    for p in iter_projects(dump_path):
        # Webrobots dumps nest the project doc under a 'data' key
        proj = p.get("data") if "data" in p else p
        country = (proj.get("country") or "").upper()
        if country in cn_countries:
            out.append(proj)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--download",
        action="store_true",
        help="Download the latest dump (~600MB) to data/.webrobots/",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if today's dump is already on disk",
    )
    ap.add_argument(
        "--enrich",
        action="store_true",
        help="Cross-reference the most recent local dump with data/projects.json",
    )
    args = ap.parse_args(argv)

    if not (args.download or args.enrich):
        ap.print_help()
        return 1

    if args.download:
        path = download_dump(force=args.force, verbose=True)
        if path is None:
            print("✗ download failed", file=sys.stderr)
            return 1

    if args.enrich:
        # Find the most recent dump on disk
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        dumps = sorted(DATA_DIR.glob("*.json"))
        if not dumps:
            print(
                "no local dump — run with --download first",
                file=sys.stderr,
            )
            return 1
        dump_path = dumps[-1]
        print(f"  enriching from {dump_path.relative_to(REPO_ROOT)}")
        candidates = filter_china_candidates(dump_path)
        print(f"  found {len(candidates)} CN/HK/TW/MO projects in dump")

        # Cross-check against our current data
        projects_file = REPO_ROOT / "data" / "projects.json"
        if not projects_file.exists():
            print("  no data/projects.json — skipping cross-check")
            return 0
        ours = json.loads(projects_file.read_text(encoding="utf-8"))
        our_paths = {
            p.get("pathname")
            for p in ours.get("projects", [])
            if p.get("pathname")
        }
        missing = [
            c for c in candidates
            if f"/projects/{c.get('creator', {}).get('slug', '')}/{c.get('slug', '')}" not in our_paths
        ]
        print(f"  {len(missing)} projects in dump but NOT in our tracker")
        for c in missing[:10]:
            print(f"    {c.get('name','?')[:50]}  ({c.get('country','?')}) — {c.get('state','?')}")
        if len(missing) > 10:
            print(f"    ... and {len(missing) - 10} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
