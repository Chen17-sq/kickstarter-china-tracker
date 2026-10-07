#!/usr/bin/env python3
"""Offline end-to-end replay in a NEW isolated directory. Network and email forbidden.

python scripts/dry_run.py --scenario partial --output /tmp/ks-partial
The copied scraper runs its real merge, history, delta, report, API and HTML code.
Only source responses, classification and optional remote media/translation are stubbed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def execute(scenario):
    from types import SimpleNamespace

    from scraper import email_notify, run
    from scraper.discover import _hit_from_proj
    from scraper.observations import observe

    def deny(*args, **kwargs):
        raise AssertionError("Network/email is forbidden in offline dry run")

    def audit(event, args):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            deny()
    sys.addaudithook(audit)
    email_notify.post_resend = deny
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    stamp = lambda d: d.isoformat().replace("+00:00", "Z")
    history = run.HISTORY
    history.mkdir(parents=True, exist_ok=True)
    for days in (7, 1):
        at = stamp(now - dt.timedelta(days=days))
        rows = []
        for i in range(30):
            row = {"pathname": f"/projects/fixture/fixture-{i}", "title": f"Fixture {i:02d}",
                   "url": f"https://www.kickstarter.com/projects/fixture/fixture-{i}",
                   "status": "live" if i < 15 else "prelaunch", "china_confidence": "高",
                   "native_currency": "USD", "static_usd_rate": 1.0, "blurb_zh": "离线回归样例"}
            for key, value in (("followers", 100), ("backers", 10), ("pledged_usd", 1000), ("min_pledge_usd", 10)):
                if i == 2 and key == "pledged_usd":
                    continue  # explicitly absent baseline
                observe(row, key, value, at=at, source="fixture",
                        basis="native_usd" if key == "pledged_usd" else key)
            row["delta_pledged_usd"] = 99999  # must not leak from carry-forward
            rows.append(row)
        snapshot = {"generated_at": at, "schema_version": 2, "projects": rows}
        (history / f"{at.replace(':', '-')}.json").write_text(json.dumps(snapshot))
    (run.DATA / "projects.json").write_text(json.dumps(snapshot))

    def crawl():
        if scenario == "all-failed":
            return {}
        hits = {}
        for i in range(30 if scenario in {"healthy", "recovery"} else 20):
            hit = _hit_from_proj({"urls": {"web": {"project": f"https://www.kickstarter.com/projects/fixture/fixture-{i}"}},
                                 "name": f"Fixture {i:02d}", "state": "live" if i < 15 else "submitted",
                                 "currency": "USD", "static_usd_rate": 1.0,
                                 "usd_pledged": 1000 if i == 0 else 1050 + i,
                                 "backers_count": 10 if i == 0 else 11 + i,
                                 "goal": 500, "percent_funded": 200})
            hits[hit.pathname] = hit
        return hits

    class Transport:
        mode = "fixture"

        def close(self):
            pass

        def post_graphql(self, body):
            data, errors = {}, []
            for alias, slug in body["variables"].items():
                i = int(slug.rsplit("-", 1)[-1])
                key = "p" + alias[1:]
                if scenario == "partial" and i % 2:
                    errors.append({"path": [key], "message": "fixture failure"})
                    data[key] = None
                    continue
                if body["operationName"] == "Pledges":
                    data[key] = {"rewards": {"nodes": [{"amount": {"amount": 10, "currency": "USD"}}]}}
                else:
                    data[key] = {"watchesCount": 100 if i == 0 else 110 + i,
                                 "backersCount": 10 if i == 0 else 11 + i,
                                 "state": "LIVE" if i < 15 else "SUBMITTED",
                                 "pledged": {"amount": 1000 if i == 0 else 1050 + i, "currency": "USD"},
                                 "percentFunded": 200}
            return 200, {"data": data, "errors": errors}

    run.crawl_discover = crawl
    run.open_transport = lambda **kw: None if scenario == "all-failed" else Transport()
    run.classify = lambda **kw: SimpleNamespace(confidence="高", reason="fixture", matched_brand=None, matched_brand_zh=None)
    run.translate_fill_missing = lambda rows: None
    run.render_pdf_today = lambda: None
    run.generate_carousel = lambda: []
    from scraper import backoff, tier_metrics
    backoff.chunk_pause = lambda *args, **kw: None
    tier_metrics.record = lambda *args, **kw: None
    if scenario == "recovery":
        # First failed attempt today stays in history. Recovery must choose
        # yesterday's observation, not this run's copied numbers or deltas.
        scenario = "all-failed"
        assert run.run() == 0
        scenario = "recovery"
    assert run.run() == 0
    result = json.loads((run.DATA / "projects.json").read_text())
    assert len(result["projects"]) == 30
    by_id = {p["title"]: p for p in result["projects"]}
    if scenario == "all-failed":
        assert all(p["delta_pledged_usd"] is None for p in result["projects"])
        assert all(p["observations"]["pledged_usd"]["status"] != "fresh" for p in result["projects"])
    else:
        assert by_id["Fixture 00"]["delta_pledged_usd"] == 0
        assert by_id["Fixture 01"]["delta_pledged_usd"] == 51
        assert by_id["Fixture 02"]["delta_pledged_usd"] is None
        if scenario == "partial":
            assert by_id["Fixture 21"]["delta_pledged_usd"] is None
            assert by_id["Fixture 21"]["observations"]["pledged_usd"]["observed_at"] == stamp(now - dt.timedelta(days=1))
    if scenario == "recovery":
        assert len(list(history.glob("*.json"))) == 4, "failed attempt was overwritten"
    assert email_notify.main(["--dry-run"]) == 0
    site = run.REPO_ROOT / "site"
    shutil.copytree(run.DATA, site / "data", dirs_exist_ok=True)
    (site / "data" / "subscribers.json").write_text('{"subscribers": [], "fixture": true}')
    shutil.copy(run.DATA / ".tmp" / "email_preview.html", site / "email_preview.html")
    integrity = {**result, "projects": [by_id[f"Fixture {i:02d}"] for i in (0, 1, 2, 21)]}
    _, integrity_html = email_notify.build_html(integrity)
    (site / "integrity_preview.html").write_text(integrity_html, encoding="utf-8")
    summary = {"scenario": scenario, "network_calls": 0, "emails_sent": 0,
               "project_count": len(result["projects"]), "quality": result["data_quality"],
               "daily_delta_valid": sum(p["delta_pledged_usd"] is not None for p in result["projects"]),
               "history_attempts": len(list(history.glob("*.json"))),
               "examples": [by_id[f"Fixture {i:02d}"] for i in (0, 1, 2, 21)]}
    (run.REPO_ROOT / "dry-run-result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({k: summary[k] for k in ("scenario", "network_calls", "emails_sent", "project_count", "daily_delta_valid", "history_attempts")}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=["all-failed", "partial", "healthy", "recovery"], default="partial")
    ap.add_argument("--output", type=Path)
    ap.add_argument("--execute-isolated", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.execute_isolated:
        if not Path(".offline-dry-run").exists():
            raise SystemExit("Refusing to run outside isolated copy")
        execute(args.scenario)
        return
    if not args.output:
        ap.error("--output must be a NEW directory")
    root = Path(__file__).resolve().parent.parent
    output = args.output.resolve()
    if output == root or root in output.parents:
        ap.error("output must be outside repository")
    output.mkdir(parents=True, exist_ok=False)
    for directory in ("scraper", "scripts", "site", "brands", "assets"):
        shutil.copytree(root / directory, output / directory,
                        ignore=shutil.ignore_patterns("__pycache__", "editions", "social", "api", "data"))
    (output / "data").mkdir()
    (output / ".offline-dry-run").touch()
    for name in ("blurbs_zh.json", "highlights_zh.json"):
        if (root / "data" / name).exists():
            shutil.copy(root / "data" / name, output / "data" / name)
    env = {k: v for k, v in os.environ.items() if not any(s in k for s in ("KEY", "TOKEN", "SECRET", "NOTIFY", "PROXY", "WEBHOOK"))}
    subprocess.run([sys.executable, str(output / "scripts" / "dry_run.py"), "--execute-isolated", "--scenario", args.scenario], cwd=output, env={**env, "PYTHONPATH": str(output)}, check=True)
    print(f"Preview directory: {output / 'site'}")


if __name__ == "__main__":
    main()
