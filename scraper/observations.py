"""Field-level evidence. A snapshot timestamp is never an observation timestamp."""
from __future__ import annotations

import copy
import datetime as dt
import math

METRICS = ("followers", "backers", "pledged_usd", "min_pledge_usd", "goal_usd",
           "percent_funded", "pledged_native")
DELTA_METRICS = ("followers", "backers", "pledged_usd")


def timestamp() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value):
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo else None
    except (TypeError, ValueError, AttributeError):
        return None


def number(value):
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (ValueError, TypeError):
        return None


def clear_deltas(row, prefix=None):
    for key in list(row):
        if (prefix and key.startswith(prefix)) or (
            prefix is None and key.startswith(("delta_", "weekly_delta_", "delta_meta"))
        ):
            row.pop(key, None)


def observe(row, key, value, *, at, source, basis=None, unit=None):
    value = number(value)
    if value is None or (key in ("followers", "backers") and not value.is_integer()):
        return False
    row[key] = int(value) if key in ("followers", "backers") else value
    row.setdefault("observations", {})[key] = {
        "status": "fresh", "attempt_status": "success", "observed_at": at,
        "attempted_at": at, "source": source,
        "unit": unit or ("USD" if key.endswith("_usd") else "count"),
        "basis": basis or key,
    }
    return True


def carry(row, previous, key, *, at, reason="fetch_failed"):
    """Retain the last value and *original* timestamp; legacy time stays unknown."""
    old = copy.deepcopy((previous.get("observations") or {}).get(key) or {})
    value = number(previous.get(key))
    if value is not None and key in ("followers", "backers"):
        value = int(value) if value.is_integer() else None
    row[key] = value
    missing = reason in {"source_missing", "no_rewards", "currency_conversion_unavailable"}
    old.update(status="stale" if value is not None else (
        "missing" if missing else "failed"),
        attempt_status="missing" if missing else "failed",
        attempted_at=at, reason=reason)
    old.setdefault("observed_at", None)
    old.setdefault("source", "legacy_unknown")
    old.setdefault("unit", "USD" if key.endswith("_usd") else "count")
    old.setdefault("basis", None)
    row.setdefault("observations", {})[key] = old


def carry_row(previous, *, at, reason="fetch_failed"):
    row = copy.deepcopy(previous)
    clear_deltas(row)
    for key in METRICS:
        carry(row, previous, key, at=at, reason=reason)
    row["status_observation"] = {
        **previous.get("status_observation", {}), "status": "stale",
        "observed_at": previous.get("status_observation", {}).get("observed_at"),
    }
    return row


def is_fresh(row, key, now=None):
    meta = (row.get("observations") or {}).get(key) or {}
    at = parse_time(meta.get("observed_at"))
    now = now or dt.datetime.now(dt.UTC)
    return (meta.get("status") == "fresh" and at is not None
            and 0 <= (now - at).total_seconds() <= 30 * 3600
            and number(row.get(key)) is not None)


def comparable_delta(current, baseline, key, *, days=1, now=None):
    """Return (value, evidence). Missing/legacy/incomparable evidence yields None."""
    cm = (current.get("observations") or {}).get(key) or {}
    conversion = cm.get("conversion") or {}
    if key == "pledged_usd" and is_fresh(current, key, now) and conversion and conversion.get("currency") != "USD":
        native_meta = current.get("observations", {}).get("pledged_native", {})
        rate = number(conversion.get("rate"))
        if (conversion.get("source") == "ks_project_usd_exchange_rate" and rate and
                conversion.get("observed_at") == cm.get("observed_at") == native_meta.get("observed_at") and
                conversion.get("currency") == native_meta.get("unit") and
                number(conversion.get("native_amount")) == number(current.get("pledged_native"))):
            value, evidence = comparable_delta(current, baseline, "pledged_native", days=days, now=now)
            evidence.update(method="constant_currency", currency=conversion["currency"],
                            usd_rate=rate, rate_observed_at=conversion["observed_at"])
            return (None if value is None else value * rate), evidence

    bm = (baseline.get("observations") or {}).get(key) or {}
    evidence = {"status": "unavailable", "reason": None,
                "from": bm.get("observed_at"), "to": cm.get("observed_at")}
    a, b = number(current.get(key)), number(baseline.get(key))
    ct, bt = parse_time(evidence["to"]), parse_time(evidence["from"])
    reason = None
    if not is_fresh(current, key, now):
        reason = "current_not_fresh"
    elif b is None or bt is None or not bm.get("basis"):
        reason = "baseline_missing_or_unverified"
    elif cm.get("unit") != bm.get("unit") or cm.get("basis") != bm.get("basis"):
        reason = "incompatible_basis_or_currency"
    else:
        seconds = (ct - bt).total_seconds()
        tolerance = 6 * 3600 if days == 1 else 12 * 3600
        if abs(seconds - days * 86400) > tolerance:
            reason = "incompatible_window"
        else:
            evidence.update(status="valid", seconds=seconds)
            value = a - b
            return (int(value) if key in ("followers", "backers") else value), evidence
    evidence["reason"] = reason
    return None, evidence


def metric_text(row, key):
    from ._common import fmt_int, fmt_pct, fmt_usd
    if key == "min_pledge_usd" and row.get("observations", {}).get(key, {}).get("reason") == "no_rewards":
        return "暂无档位"
    if not is_fresh(row, key):
        return "未更新"
    if key == "min_pledge_usd":
        return f"${row[key]:,.2f}"
    if key == "percent_funded":
        return fmt_pct(row[key])
    return (fmt_usd if key.endswith("_usd") else fmt_int)(row.get(key))


def delta_text(row, key, *, weekly=False):
    from ._common import fmt_int, fmt_usd
    name = ("weekly_delta_" if weekly else "delta_") + key
    meta = (row.get("delta_meta") or {}).get(name) or {}
    value = row.get(name)
    if meta.get("status") != "valid" or value is None or not is_fresh(row, key):
        return "无法计算"
    formatted = (fmt_usd if key.endswith("_usd") else fmt_int)(abs(value))
    return ("+" if value > 0 else "−" if value < 0 else "") + formatted


class FetchResults(dict):
    """Values stay compatible with old callers; evidence distinguishes null from failed."""
    def __init__(self, slugs):
        super().__init__((s, None) for s in slugs)
        self.errors = dict.fromkeys(slugs, "fetch_failed")
        self.observed_at = {}
        self.money = {}
