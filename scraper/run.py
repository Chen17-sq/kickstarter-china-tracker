"""End-to-end scrape pipeline — invoked by GitHub Actions cron.

Architecture:
  1. Crawl Discover seeds via the JSON API → DiscoverHit per project, with
     name/creator/location/country/state/pledged/backers/staff_pick/...
  2. Classify each hit; keep those scored 高 or 中 for China background.
  3. For prelaunch projects (state in {submitted, started}), fetch the project
     page to extract `followers` — the key prelaunch metric, missing from the
     Discover JSON.
  4. Write snapshots: data/projects.json (everything), data/prelaunch.json,
     data/live.json, data/history/<ts>.json.
  5. Diff vs the previous history snapshot → CHANGELOG.md (consumed by notify).

Safety: if Discover returns 0 candidates or all China-matches are < a hard
floor (likely Cloudflare blocking the runner), refuse to overwrite the live
projects.json. We still write a history snapshot for forensics.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from .http import RateLimiter
from .discover import crawl_discover, DiscoverHit
from .classify import classify
from .diff import diff_snapshots, changes_to_markdown
from .translate import fill_missing as translate_fill_missing
from .report import make_report, REPORTS
from .project import fetch_watches_counts, fetch_pledge_minimums, slug_from_pathname
from .banner import write_banner
from .atomic import write_text_atomic, write_json_atomic
from .momentum import compute_deltas
from .email_notify import build_html as build_email_html, write_archive as write_email_archive
from .sitemap import write_sitemap
from .pdf import render_today as render_pdf_today
from .social import generate_carousel
from .cleanup import prune_archives

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "data"
HISTORY = DATA / "history"
BLURBS_ZH = DATA / "blurbs_zh.json"

# If China-matched count drops below this floor, treat the run as compromised
# (likely Cloudflare blocked the runner, KS changed schema, etc.) and do NOT
# overwrite the live data files. The history snapshot is still written so we
# can diagnose afterwards. Tune via env var KS_MIN_KEPT.
MIN_KEPT_FLOOR = int(os.environ.get("KS_MIN_KEPT", "20"))

PRELAUNCH_STATES = {"submitted", "started"}
LIVE_STATES = {"live"}
ENDED_STATES = {"successful", "failed", "canceled", "suspended"}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_status(state: str | None) -> str:
    if state in PRELAUNCH_STATES:
        return "prelaunch"
    if state in LIVE_STATES:
        return "live"
    if state == "successful":
        return "successful"
    if state == "failed":
        return "failed"
    if state in {"canceled", "suspended"}:
        return state
    return "unknown"


def load_blurbs_zh() -> dict[str, str]:
    """Load curated Chinese product one-liners keyed by KS pathname.

    File format: flat dict { '/projects/x/y': '中文一句话', ... } with an
    optional '_meta' key (skipped). Future: extend to LLM-translated entries.
    """
    if not BLURBS_ZH.exists():
        return {}
    try:
        raw = json.loads(BLURBS_ZH.read_text(encoding="utf-8"))
        return {k: v for k, v in raw.items()
                if isinstance(v, str) and not k.startswith("_")}
    except Exception as e:
        print(f"  warn: blurbs_zh.json failed to load ({e}); continuing without")
        return {}


def build_row(hit: DiscoverHit, *, followers: int | None,
              confidence: str, reason: str,
              matched_brand: str | None, matched_brand_zh: str | None,
              blurb_zh: str | None,
              min_pledge_usd: float | None = None) -> dict:
    status = normalize_status(hit.state)
    return {
        "pathname": hit.pathname,
        "url": hit.url,
        "title": hit.title,
        "blurb": hit.blurb,
        "blurb_zh": blurb_zh,
        "creator": hit.creator_name,  # alias for site/app.js compatibility
        "creator_slug": hit.creator_slug,
        "creator_name": hit.creator_name,
        "location": hit.location,
        "country": hit.country,
        "category": hit.category,
        "image_url": hit.image_url,
        "status": status,
        "raw_state": hit.state,
        "project_we_love": hit.staff_pick,
        "followers": followers,
        "backers": hit.backers_count,
        "pledged_usd": hit.pledged_usd,
        "goal_usd": hit.goal_usd,
        "percent_funded": hit.percent_funded,
        "min_pledge_usd": min_pledge_usd,
        "deadline": hit.deadline,
        "launched_at": hit.launched_at,
        "created_at": hit.created_at,
        "state_changed_at": hit.state_changed_at,
        "prelaunch_activated": hit.prelaunch_activated,
        "china_confidence": confidence,
        "china_reason": reason,
        "matched_brand": matched_brand,
        "matched_brand_zh": matched_brand_zh,
    }


def run() -> int:
    started = now_iso()
    print(f"[{started}] crawl discover ...")
    hits = crawl_discover()
    print(f"  → {len(hits)} candidate projects")

    # Discover catastrophe guard: with 14 seeds × 8 pages, a healthy crawl
    # produces 600-700 candidates. If we got < 50, all-but-one seed likely
    # got 403'd — refuse to proceed (don't overwrite good projects.json).
    DISCOVER_FLOOR = 50
    if len(hits) < DISCOVER_FLOOR:
        print(
            f"FATAL: only {len(hits)} candidates (floor={DISCOVER_FLOOR}). "
            f"Most discover seeds were probably Cloudflare-blocked. "
            f"Refusing to write. data/projects.json stays at its previous value.",
            file=sys.stderr,
        )
        return 1

    blurbs_zh = load_blurbs_zh()
    print(f"  loaded {len(blurbs_zh)} curated Chinese blurbs")

    # Pre-fetch watchesCount via KS GraphQL for all classified rows.
    # For prelaunch: this is the current pre-launch follower count (the key
    # signal). For live/ended: it's the frozen pre-launch hype baseline.
    classified_paths = []
    for path, hit in hits.items():
        cls = classify(creator_slug=hit.creator_slug, location=hit.location, title=hit.title)
        if cls.confidence in ("高", "中"):
            classified_paths.append((path, hit, cls))

    slugs = [slug_from_pathname(path) for path, _, _ in classified_paths]
    print(f"  fetching watchesCount via GraphQL for {len(slugs)} projects ...")
    watches = fetch_watches_counts(slugs)
    n_with = sum(1 for v in watches.values() if v is not None)
    print(f"  got watchesCount for {n_with}/{len(slugs)}")

    # Graceful degradation: if Cloudflare 403'd the GraphQL endpoint and we
    # got <50% watchers coverage, fall back to the previous projects.json
    # snapshot's followers numbers. Avoids sending an email full of zeros
    # when the only thing wrong was a transient block. Δ deltas will read
    # as 0 (truthful — we don't know today's change).
    if len(slugs) and n_with < len(slugs) * 0.5:
        print(f"  ⚠ watchers fetch coverage {n_with}/{len(slugs)} below 50%; reusing previous followers")
        prev_path = DATA / "projects.json"
        if prev_path.exists():
            try:
                prev = json.loads(prev_path.read_text(encoding="utf-8"))
                prev_followers = {p.get("pathname"): p.get("followers")
                                  for p in (prev.get("projects") or [])
                                  if p.get("pathname") and p.get("followers") is not None}
                restored = 0
                for path, _, _ in classified_paths:
                    slug = slug_from_pathname(path)
                    if watches.get(slug) is None and prev_followers.get(path) is not None:
                        watches[slug] = prev_followers[path]
                        restored += 1
                print(f"  → restored {restored} followers from previous snapshot")
            except Exception as e:
                print(f"  ! couldn't read previous snapshot for fallback: {e}")

    # Pledge tier minimums (起步价) — separate query, smaller chunks
    print(f"  fetching minimum pledge tiers via GraphQL ...")
    pledge_mins = fetch_pledge_minimums(slugs)
    n_pledge = sum(1 for v in pledge_mins.values() if v is not None)
    print(f"  got pledge minimum for {n_pledge}/{len(slugs)}")

    rows: list[dict] = []
    for path, hit, cls in classified_paths:
        slug = slug_from_pathname(path)
        rows.append(build_row(
            hit,
            followers=watches.get(slug),
            confidence=cls.confidence,
            reason=cls.reason,
            matched_brand=cls.matched_brand,
            matched_brand_zh=cls.matched_brand_zh,
            blurb_zh=blurbs_zh.get(path),
            min_pledge_usd=pledge_mins.get(slug),
        ))
    matched = sum(1 for r in rows if r.get("blurb_zh"))
    print(f"  classified {len(rows)} as China-background ({matched} with curated zh blurb)")

    # Auto-translate any rows still missing blurb_zh (no-op if no API key).
    # Mutates rows in-place to add blurb_zh; updates data/blurbs_zh.json.
    translate_fill_missing(rows)

    # Compute Δ since previous snapshot (mutates rows in-place; no-op on
    # first run when no history exists yet).
    momentum_summary = compute_deltas(rows)
    if momentum_summary.get("delta_seconds"):
        hrs = momentum_summary["delta_seconds"] / 3600
        n_with_delta = sum(1 for r in rows if "delta_pledged_usd" in r)
        print(f"  computed Δ vs snapshot {hrs:.1f}h ago for {n_with_delta} projects")

    finished = now_iso()
    out = {
        "generated_at": finished,
        "started_at": started,
        "total_candidates": len(hits),
        "kept": len(rows),
        "projects": rows,
    }

    DATA.mkdir(parents=True, exist_ok=True)
    HISTORY.mkdir(parents=True, exist_ok=True)

    # Always write the history snapshot — useful for debugging even when the
    # main file is locked behind the safety guard.
    snap_path = HISTORY / f"{finished.replace(':', '-')}.json"
    write_json_atomic(snap_path, out)

    if len(rows) < MIN_KEPT_FLOOR:
        print(f"WARN: kept {len(rows)} < floor {MIN_KEPT_FLOOR}. "
              f"Refusing to overwrite data/projects.json. "
              f"History snapshot still written to {snap_path.name}.",
              file=sys.stderr)
        return 2

    write_json_atomic(DATA / "projects.json", out)
    for slice_status in ("prelaunch", "live"):
        sub = {**out, "projects": [r for r in rows if r["status"] == slice_status]}
        write_json_atomic(DATA / f"{slice_status}.json", sub)

    # Diff vs the second-newest snapshot in history
    snaps = sorted(HISTORY.glob("*.json"))
    if len(snaps) >= 2:
        try:
            prev = json.loads(snaps[-2].read_text(encoding="utf-8"))
            diffs = diff_snapshots(prev, out)
            if diffs:
                write_text_atomic(REPO_ROOT / "CHANGELOG.md",
                                  changes_to_markdown(diffs))
                print(f"  wrote CHANGELOG.md with {len(diffs)} changes")
            else:
                print("  no changes since last run")
        except Exception as e:
            print(f"  diff skipped: {e}")

    # Refresh the editorial banner SVG with current KPIs (rendered at top of README)
    try:
        banner_path = write_banner()
        print(f"  refreshed {banner_path.relative_to(REPO_ROOT)}")
    except Exception as e:
        print(f"  banner skipped: {e}")

    # Archive today's email-formatted HTML edition under site/editions/.
    # Pages serves it permanently at /editions/<date>.html.
    try:
        _, archive_html = build_email_html(out)
        write_email_archive(archive_html)
        today_date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        print(f"  archived site/editions/{today_date}.html (+ latest.html)")
    except Exception as e:
        print(f"  archive skipped: {e}")

    # Refresh sitemap.xml so newly-archived editions get crawled
    try:
        sm = write_sitemap()
        print(f"  refreshed {sm.relative_to(REPO_ROOT)}")
    except Exception as e:
        print(f"  sitemap skipped: {e}")

    # Render today's edition to PDF (for 小红书 / 微信 sharing)
    try:
        pdf = render_pdf_today()
        if pdf:
            print(f"  rendered {pdf.relative_to(REPO_ROOT)} (+ latest.pdf)")
    except Exception as e:
        print(f"  pdf skipped: {e}")

    # Generate 9 portrait PNGs for 小红书 carousel
    try:
        slides = generate_carousel()
        if slides:
            print(f"  generated {len(slides)} carousel slides → site/social/latest/")
    except Exception as e:
        print(f"  carousel skipped: {e}")

    # Prune dated archives older than retention thresholds (keeps repo
    # cloneable as the daily PNG/PDF/history archives accumulate).
    try:
        counts = prune_archives()
        n = sum(counts.values())
        if n > 0:
            print(f"  cleanup: pruned {n} stale dated artifact(s)")
    except Exception as e:
        print(f"  cleanup skipped: {e}")

    # Generate today's Markdown report (compares against snaps[-2])
    try:
        REPORTS.mkdir(parents=True, exist_ok=True)
        prev_for_report = None
        if len(snaps) >= 2:
            try:
                prev_for_report = json.loads(snaps[-2].read_text(encoding="utf-8"))
            except Exception:
                prev_for_report = None
        md = make_report(out, prev_for_report)
        today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        report_path = REPORTS / f"{today}.md"
        write_text_atomic(report_path, md)
        # Stable URL — bookmark this once
        write_text_atomic(REPORTS / "latest.md", md)
        print(f"  wrote reports/{today}.md (and reports/latest.md)")
    except Exception as e:
        print(f"  report skipped: {e}")

    print(f"done. kept {len(rows)}/{len(hits)}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
