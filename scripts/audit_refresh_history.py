#!/usr/bin/env python3
"""Read-only historical audit. Never rewrites or 'repairs' original snapshots."""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def audit(root, logs, output):
    result, prior = [], {}
    for path in sorted((root / "data" / "history").glob("*.json")):
        snap = json.loads(path.read_text())
        rows = snap.get("projects", [])
        by_path = {p["pathname"]: p for p in rows}
        same_followers = sum(p.get("followers") == prior[p["pathname"]].get("followers") for p in rows if p["pathname"] in prior)
        live = [p for p in rows if p.get("status") == "live"]
        date = snap["generated_at"][:10]
        logfile = logs / f"ks-{date}.log"
        log = logfile.read_text(errors="replace") if logfile.exists() else ""
        def match(pattern, log=log):
            found = re.search(pattern, log)
            return found.group(1) if found else ""
        result.append({"date": date, "snapshot": path.name, "projects": len(rows), "live": len(live),
                       "followers_same_as_previous": same_followers,
                       "daily_pledged_zero": sum(p.get("delta_pledged_usd") == 0 for p in rows),
                       "daily_pledged_nonzero": sum(isinstance(p.get("delta_pledged_usd"), (int, float)) and p["delta_pledged_usd"] != 0 for p in rows),
                       "live_weekly_zero": sum(p.get("weekly_delta_pledged_usd") == 0 for p in live),
                       "field_provenance_rows": sum(bool(p.get("observations")) for p in rows),
                       "watches_fetched": match(r"got watchesCount for (\d+/\d+)"),
                       "minimum_pledge_fetched": match(r"got pledge minimum for (\d+/\d+)"),
                       "catalog_refresh": match(r"refresh applied: (\d+/\d+) fresh"),
                       "restored_followers": match(r"restored (\d+) followers"),
                       "emails_sent": match(r"Email broadcast: sent=(\d+)"),
                       "browser_csrf_failures": log.count("CSRF token not found"),
                       "nodriver_start_failures": log.count("nodriver browser.start failed"),
                       "evidence": "run_log_and_snapshot" if log else "snapshot_only_not_proof_of_fetch_failure"})
        prior = by_path
    output.mkdir(parents=True, exist_ok=True)
    with (output / "historical-refresh-audit.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(result[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(result)
    logged = [r for r in result if r["watches_fetched"]]
    summary = {"snapshots": len(result), "range": [result[0]["date"], result[-1]["date"]],
               "logs_checked": len(logged),
               "zero_watch_days": [r["date"] for r in logged if r["watches_fetched"].startswith("0/")],
               "partial_or_full_watch_days": [{"date": r["date"], "coverage": r["watches_fetched"]} for r in logged if not r["watches_fetched"].startswith("0/")],
               "zero_catalog_refresh_days": [r["date"] for r in logged if r["catalog_refresh"].startswith("0/")],
               "nonzero_pledged_days": sum(r["daily_pledged_nonzero"] > 0 for r in result),
               "latest": result[-1]}
    (output / "historical-refresh-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    audit(Path(__file__).resolve().parent.parent, args.logs, args.output)
