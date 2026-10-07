"""Proposed pre-send gates; observe by default until the owner approves enforcement."""
from __future__ import annotations

import datetime as dt

from .observations import is_fresh, parse_time

POLICY = {"core_coverage": 0.90, "delta_coverage": 0.80,
          "zero_ratio": 0.95, "zero_min_sample": 20, "max_age_hours": 30}


def assess(snapshot, *, now=None):
    now = now or dt.datetime.now(dt.UTC)
    rows = snapshot.get("projects") or []
    metrics, issues = {}, []
    for key in ("followers", "backers", "pledged_usd", "min_pledge_usd"):
        eligible = [p for p in rows if (p.get("status") == "prelaunch" if key == "followers"
                    else p.get("status") == "live")]
        fresh = sum(is_fresh(p, key, now) for p in eligible)
        comparable = [p for p in eligible if (p.get("delta_meta", {}).get("delta_" + key) or {}).get("status") == "valid"]
        zeros = sum(p.get("delta_" + key) == 0 for p in comparable)
        ages = [(now - parse_time(m["observed_at"])).total_seconds() / 3600
                for p in eligible if (m := p.get("observations", {}).get(key, {}))
                and parse_time(m.get("observed_at"))]
        statuses = {s: sum(p.get("observations", {}).get(key, {}).get("status", "missing") == s
                          for p in eligible) for s in ("fresh", "stale", "missing", "failed")}
        n = len(eligible)
        metrics[key] = {"eligible": n, "fresh": fresh, "coverage": fresh / n if n else None,
                        "comparable": len(comparable), "zero_changes": zeros,
                        "oldest_observation_hours": round(max(ages), 2) if ages else None,
                        "unknown_observation_time": sum(not parse_time(p.get("observations", {}).get(key, {}).get("observed_at")) for p in eligible),
                        "statuses": statuses}
        if n and key != "min_pledge_usd":
            if fresh / n < POLICY["core_coverage"]:
                issues.append(f"{key}: fresh {fresh}/{n} below 90%")
            if len(comparable) / n < POLICY["delta_coverage"]:
                issues.append(f"{key}: comparable daily baseline {len(comparable)}/{n} below 80%")
            if len(comparable) >= POLICY["zero_min_sample"] and zeros / len(comparable) >= POLICY["zero_ratio"]:
                issues.append(f"{key}: suspicious zero changes {zeros}/{len(comparable)}; review required")
    if not rows:
        issues.append("empty_snapshot")
    return {"status": "degraded" if issues else "healthy", "metrics": metrics,
            "issues": issues, "proposed_send_allowed": not issues,
            "policy_mode": "observe", "thresholds": POLICY, "evaluated_at": now.isoformat()}


def quality_lines(snapshot):
    q = snapshot.get("data_quality") or assess(snapshot)
    lines = ["数据刷新：" + ("正常" if q["status"] == "healthy" else "部分未更新／增量无法计算")]
    labels = {"followers": "预热关注", "backers": "在筹支持人数", "pledged_usd": "在筹筹款", "min_pledge_usd": "最低支持档位"}
    for key, m in q["metrics"].items():
        lines.append(f"{labels[key]}：本次有效刷新 {m['fresh']}/{m['eligible']}；可比日增量 {m['comparable']}/{m['eligible']}")
    lines.append("未更新值仅为历史参考；生成时间不代表观测时间。邮件送达另行统计。")
    return lines
