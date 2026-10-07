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
from pathlib import Path

from . import anomalies as _anomalies
from . import brand_candidates as _brand_candidates
from . import health
from . import refresh as _refresh
from .api import write_api
from .atomic import write_json_atomic, write_text_atomic, write_versioned_text
from .banner import write_banner
from .classify import classify
from .diff import changes_to_markdown, diff_snapshots
from .discover import DiscoverHit, crawl_discover
from .email_notify import build_html as build_email_html
from .email_notify import write_archive as write_email_archive
from .feed import write_feed
from .momentum import compute_deltas, compute_weekly_deltas
from .money import observe_money
from .observations import METRICS, FetchResults, carry, carry_row, is_fresh, observe
from .pdf import render_today as render_pdf_today
from .project import (
    fetch_pledge_minimums,
    fetch_watches_counts,
    open_transport,
    slug_from_pathname,
)
from .quality import assess
from .report import REPORTS, make_report
from .sitemap import write_sitemap
from .social import generate_carousel
from .translate import fill_missing as translate_fill_missing

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
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    row = {
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

    at = hit.observed_at or now_iso()
    row["native_currency"] = hit.raw.get("currency")
    row["static_usd_rate"] = hit.raw.get("static_usd_rate")
    for key in METRICS:
        carry(row, {}, key, at=at, reason="source_missing")
    for key, value in (("backers", hit.backers_count), ("goal_usd", hit.goal_usd),
                       ("percent_funded", hit.percent_funded)):
        observe(row, key, value, at=at, source="ks_discover")
    currency = row["native_currency"]
    rate = row["static_usd_rate"]
    basis = "native_usd" if currency == "USD" else (
        f"static_usd:{currency}:{rate}" if currency and rate else "ks_reported_usd")
    if hit.raw.get("usd_pledged") is None and hit.raw.get("converted_pledged_amount") is not None:
        basis = f"ks_converted_usd:{currency or 'unknown'}"
    observe(row, "pledged_usd", hit.pledged_usd, at=at, source="ks_discover", basis=basis)
    observe(row, "pledged_native", hit.raw.get("pledged"), at=at, source="ks_discover",
            basis=f"native_pledged:{currency}", unit=currency or "unknown")
    observe(row, "followers", followers, at=now_iso(), source="ks_graphql")
    observe(row, "min_pledge_usd", min_pledge_usd, at=now_iso(), source="ks_graphql")
    row["status_observation"] = {"status": "fresh" if hit.state else "missing",
                                  "observed_at": at if hit.state else None, "source": "ks_discover"}
    return row


def run() -> int:
    health.reset()  # fresh counter state for this run
    started = now_iso()
    print(f"[{started}] crawl discover ...")
    try:
        hits = crawl_discover()
    except Exception as exc:
        health.fetch_error("discover", type(exc).__name__, 0)
        print(f"  discover failed: {type(exc).__name__}; attempting known catalog")
        hits = {}
    print(f"  → {len(hits)} candidate projects")

    # Discover catastrophe guard. Threshold lowered to 25 (was 50) now
    # that refresh.refresh_from_history() supplements yesterday's known
    # projects via fat GraphQL — even a near-total discover failure can
    # still produce a usable snapshot. Only abort when discover is so
    # broken that we have no useful new-project signal at all.
    DISCOVER_FLOOR = 25
    if len(hits) < DISCOVER_FLOOR and not _refresh.latest_history_snapshot():
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
    unknown_for_review: list[dict] = []  # for brand_candidates auto-discovery
    for path, hit in hits.items():
        cls = classify(creator_slug=hit.creator_slug, location=hit.location, title=hit.title)
        if cls.confidence in ("高", "中"):
            classified_paths.append((path, hit, cls))
        elif cls.confidence == "未知":
            # Track unknowns with their hit data — brand_candidates.detect()
            # will further filter by signal strength (followers / pledged /
            # staff_pick). Without this list, unknowns get dropped on the
            # classifier step and we never see them again.
            unknown_for_review.append({
                "pathname": path,
                "title": hit.title,
                "location": hit.location,
                "country": hit.country,
                "creator_slug": hit.creator_slug,
                "status": hit.state,
                "followers": None,  # watchesCount fetch is below; can't fill yet
                "pledged_usd": hit.pledged_usd,
                "project_we_love": hit.staff_pick,
                "url": hit.url,
                "china_confidence": "未知",
            })

    prior = _refresh.latest_history_snapshot() or {}
    prior_by_path = {p.get("pathname"): p for p in prior.get("projects", [])}
    slugs = list(dict.fromkeys(
        [slug_from_pathname(path) for path, _, _ in classified_paths] +
        [slug_from_pathname(p["pathname"]) for p in prior.get("projects", [])
         if p.get("pathname") and p.get("status") in {"prelaunch", "live"}]
    ))
    health.classified(len(classified_paths))
    try:
        ks_transport = open_transport(label="ks_graphql")
    except Exception as exc:
        health.fetch_error("graphql_seed", type(exc).__name__, len(slugs))
        ks_transport = None
    refresh_result = None
    watches, pledge_mins = FetchResults(slugs), FetchResults(slugs)
    try:
        # Core known-catalog fields have priority over optional reward expansion.
        try:
            refresh_result = _refresh.refresh_from_history(transport=ks_transport, verbose=True)
        except Exception as exc:
            health.fetch_error("catalog_refresh", type(exc).__name__, len(prior_by_path))
        refreshed_rows = refresh_result[0] if refresh_result else [carry_row(p, at=now_iso()) for p in prior_by_path.values()]
        for p in refreshed_rows:
            slug = slug_from_pathname(p["pathname"])
            if slug in watches and is_fresh(p, "followers"):
                watches[slug] = p["followers"]
                watches.errors[slug] = None
                watches.observed_at[slug] = p["observations"]["followers"]["observed_at"]
        missing = [slug for slug in slugs if watches[slug] is None]
        try:
            additional = fetch_watches_counts(missing, transport=ks_transport)
            for slug in missing:
                watches[slug] = additional.get(slug)
                watches.errors[slug] = getattr(additional, "errors", {}).get(slug)
                if watches[slug] is not None:
                    watches.observed_at[slug] = getattr(additional, "observed_at", {}).get(slug) or now_iso()
        except Exception as exc:
            health.fetch_error("watches", type(exc).__name__, len(missing))
        n_with = sum(value is not None for value in watches.values())
        health.watches_done(getattr(ks_transport, "mode", "failed"), n_with, len(slugs))
        print(f"  got watchesCount for {n_with}/{len(slugs)} (known active + discovered)")
        try:
            pledge_mins = fetch_pledge_minimums(slugs, transport=ks_transport)
        except Exception as exc:
            health.fetch_error("minimum_pledge", type(exc).__name__, len(slugs))
            health.pledge_done("failed", 0, len(slugs))
        print(f"  got pledge minimum for {sum(v is not None for v in pledge_mins.values())}/{len(slugs)}")
        # Apply supplemental successes to known projects even when Discover
        # did not return them; original times remain on any failed fields.
        for p in refreshed_rows:
            slug = slug_from_pathname(p["pathname"])
            for key, values in (("followers", watches), ("min_pledge_usd", pledge_mins)):
                if values.get(slug) is not None:
                    at = getattr(values, "observed_at", {}).get(slug) or now_iso()
                    money = getattr(values, "money", {}).get(slug)
                    if money:
                        observe_money(p, key, money, at=at, source="ks_graphql")
                    else:
                        observe(p, key, values[slug], at=at, source="ks_graphql")
                else:
                    carry(p, p, key, at=now_iso(), reason=getattr(values, "errors", {}).get(slug) or "fetch_failed")
    finally:
        if ks_transport is not None:
            ks_transport.close()

    rows: list[dict] = []
    for path, hit, cls in classified_paths:
        slug = slug_from_pathname(path)
        row = build_row(
            hit,
            followers=watches.get(slug),
            confidence=cls.confidence,
            reason=cls.reason,
            matched_brand=cls.matched_brand,
            matched_brand_zh=cls.matched_brand_zh,
            blurb_zh=blurbs_zh.get(path),
            min_pledge_usd=pledge_mins.get(slug),
        )
        for key, result in (("followers", watches), ("min_pledge_usd", pledge_mins)):
            if result.get(slug) is not None:
                at = getattr(result, "observed_at", {}).get(slug) or now_iso()
                money = getattr(result, "money", {}).get(slug)
                if money:
                    observe_money(row, key, money, at=at, source="ks_graphql")
                else:
                    row["observations"][key]["observed_at"] = at
            else:
                row["observations"][key]["reason"] = getattr(result, "errors", {}).get(slug) or "fetch_failed"
        rows.append(row)
    matched = sum(1 for r in rows if r.get("blurb_zh"))
    print(f"  classified {len(rows)} as China-background ({matched} with curated zh blurb)")

    # Merge per field: a fresh discovered amount must survive a failed GraphQL
    # refresh, and a successful GraphQL watcher must survive a discover hit.
    refreshed = {p.get("pathname"): p for p in refreshed_rows}
    restored = 0
    for row in rows:
        path = row["pathname"]
        old = prior_by_path.get(path, {})
        update = refreshed.pop(path, {})
        for key in METRICS:
            current_meta = row.get("observations", {}).get(key, {})
            update_meta = update.get("observations", {}).get(key, {})
            if update_meta.get("status") == "fresh" and (
                current_meta.get("status") != "fresh" or
                update_meta.get("observed_at", "") > current_meta.get("observed_at", "")
            ):
                row[key] = update[key]
                row["observations"][key] = update_meta
            elif current_meta.get("status") != "fresh":
                carry(row, old, key, at=now_iso(), reason=current_meta.get("reason", "source_missing"))
                restored += key == "followers" and row[key] is not None
        if update.get("status_observation", {}).get("status") == "fresh":
            row["status"] = update["status"]
            row["status_observation"] = update["status_observation"]
    existing = {p["pathname"] for p in rows}
    for path, old in prior_by_path.items():
        if path and path not in existing:
            rows.append(refreshed.get(path) or carry_row(old, at=now_iso()))
    health.watches_restored_from_prev(restored)
    print(f"  retained {restored} historical watcher values with original observation times")

    # Auto-translate any rows still missing blurb_zh (no-op if no API key).
    # Mutates rows in-place to add blurb_zh; updates data/blurbs_zh.json.
    translate_fill_missing(rows)

    # Compute Δ since previous snapshot (mutates rows in-place; no-op on
    # first run when no history exists yet).
    momentum_summary = compute_deltas(rows)
    if momentum_summary.get("delta_seconds"):
        hrs = momentum_summary["delta_seconds"] / 3600
        n_with_delta = sum(1 for r in rows if r.get("delta_pledged_usd") is not None)
        print(f"  computed Δ vs snapshot {hrs:.1f}h ago for {n_with_delta} projects")

    # Compute weekly Δ (7-day rolling window). Surfaces sustained growth
    # vs daily noise. No-op until history is at least 5 days old.
    weekly_summary = compute_weekly_deltas(rows)
    if weekly_summary.get("age_days"):
        n_weekly = sum(1 for r in rows if r.get("weekly_delta_pledged_usd") is not None)
        print(
            f"  computed weekly Δ vs snapshot {weekly_summary['age_days']}d ago "
            f"for {n_weekly} projects"
        )

    finished = now_iso()
    out = {
        "schema_version": 2,
        "delivery_policy": os.environ.get("KS_EMAIL_DELIVERY", "unknown"),
        "generated_at": finished,
        "started_at": started,
        "total_candidates": len(hits),
        "kept": len(rows),
        "projects": rows,
    }

    out["data_quality"] = assess(out)
    health.set_quality(out["data_quality"])
    if out["data_quality"]["status"] != "healthy":
        print("DATA REFRESH DEGRADED: " + "; ".join(out["data_quality"]["issues"]))

    DATA.mkdir(parents=True, exist_ok=True)
    HISTORY.mkdir(parents=True, exist_ok=True)

    # Always write the history snapshot — useful for debugging even when the
    # main file is locked behind the safety guard.
    snap_path = HISTORY / f"{finished.replace(':', '-')}.json"
    attempt = 1
    while snap_path.exists():
        snap_path = HISTORY / f"{finished.replace(':', '-')}_attempt{attempt:03d}.json"
        attempt += 1
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
                write_text_atomic(REPO_ROOT / "CHANGELOG.md", changes_to_markdown([]))
                print("  no comparable changes since last run")
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
        archive_path = write_email_archive(archive_html)
        print(f"  archived {archive_path.name} (+ latest.html)")
    except Exception as e:
        print(f"  archive skipped: {e}")

    # Refresh sitemap.xml so newly-archived editions get crawled
    try:
        sm = write_sitemap()
        print(f"  refreshed {sm.relative_to(REPO_ROOT)}")
    except Exception as e:
        print(f"  sitemap skipped: {e}")

    # Refresh Atom feed (site/feed.xml) — subscription alternative to email,
    # consumed by any RSS reader. See scraper/feed.py.
    try:
        fp = write_feed()
        if fp:
            print(f"  refreshed {fp.relative_to(REPO_ROOT)}")
    except Exception as e:
        print(f"  feed skipped: {e}")

    # Refresh public JSON API (site/api/today.json + <date>.json + index.json).
    # Slim schema for outside consumers (Slack bots, dashboards, mirrors).
    try:
        api_paths = write_api(out)
        print(f"  refreshed {len(api_paths)} API file(s) (site/api/)")
    except Exception as e:
        print(f"  api skipped: {e}")

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

    # Retention is deliberately separate from collection/recovery. A retry
    # must never remove the evidence needed to diagnose an earlier attempt.

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
        today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
        report_path = write_versioned_text(REPORTS / f"{today}.md", md)
        # Stable URL — bookmark this once
        write_text_atomic(REPORTS / "latest.md", md)
        print(f"  wrote reports/{report_path.name} (and reports/latest.md)")
    except Exception as e:
        print(f"  report skipped: {e}")

    # Persist scrape health for the OPS digest. Failure is non-fatal —
    # we'd rather have a working email today than crash on observability.
    try:
        health.save()
    except Exception as e:
        print(f"  health.save() skipped: {e}")

    # Brand-candidates auto-discovery — surface high-signal unknown creators
    # for owner to evaluate adding to brands/china_brands.yaml. FYI-only.
    try:
        bc_result = _brand_candidates.detect(unknown_for_review)
        _brand_candidates.save(bc_result)
        n_cands = len(bc_result.get("candidates", []))
        if n_cands:
            print(f"  brand candidates: {n_cands} unknown high-signal creator(s) for review")
    except Exception as e:
        print(f"  brand_candidates skipped: {e}")

    # Per-project anomaly detection: vanished / reverted / stuck. FYI-only;
    # surfaced in the OPS digest but doesn't block the broadcast.
    try:
        prev_for_anomalies = None
        if len(snaps) >= 2:
            try:
                prev_for_anomalies = json.loads(snaps[-2].read_text(encoding="utf-8"))
            except Exception:
                prev_for_anomalies = None
        anomalies_result = _anomalies.detect(out, prev_for_anomalies)
        _anomalies.save(anomalies_result)
        v = len(anomalies_result.get("vanished", []))
        r = len(anomalies_result.get("reverted", []))
        s = len(anomalies_result.get("stuck", []))
        if v + r + s > 0:
            print(f"  anomalies: vanished={v} reverted={r} stuck={s}")
    except Exception as e:
        print(f"  anomalies skipped: {e}")

    print(f"done. kept {len(rows)}/{len(hits)}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
