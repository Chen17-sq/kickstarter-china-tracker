"""Read-only live fundraising totals. Never promote carried values to observations."""
from __future__ import annotations

import datetime as dt
import math
import re

from ._common import fmt_usd
from .observations import parse_time


def usd_number(value):
    """Only JSON numbers qualify; booleans and numeric strings are not money."""
    if type(value) not in (int, float):
        return None
    try:
        return float(value) if math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None


def live_pledged_totals(projects, *, now=None):
    """Full total is unknown unless every live project has fresh USD evidence.

    Coverage includes missing/stale projects. Empty coverage is unknown, not zero.
    Freshness uses observation time against the evaluation clock, never generated_at.
    """
    now = now or dt.datetime.now(dt.UTC)
    live = [p for p in projects if p.get("status") == "live"]
    values = []
    for p in live:
        observations = p.get("observations")
        meta = observations.get("pledged_usd") if isinstance(observations, dict) else None
        if not isinstance(meta, dict):
            continue
        value = usd_number(p.get("pledged_usd"))
        raw_time = meta.get("observed_at")
        at = parse_time(raw_time) if isinstance(raw_time, str) and re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d"
            r"(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", raw_time
        ) else None
        if (value is not None and meta.get("status") == "fresh" and meta.get("unit") == "USD"
                and at is not None and 0 <= (now - at).total_seconds() <= 30 * 3600):
            values.append(value)
    try:
        subtotal = math.fsum(values) if values else None
    except OverflowError:
        subtotal = None
    return {
        "total_live_usd": subtotal if values and len(values) == len(live) else None,
        "verified_live_usd_subtotal": subtotal,
        "live_usd_coverage": {"verified": len(values), "total": len(live)},
    }


def live_pledged_text(totals, *, lang="zh"):
    coverage = totals["live_usd_coverage"]
    count = f"{coverage['verified']}/{coverage['total']}"
    full = totals["total_live_usd"]
    subtotal = totals["verified_live_usd_subtotal"]
    if lang == "en":
        if full is not None:
            return f"Full total {fmt_usd(full)} · {count} projects"
        amount = fmt_usd(subtotal) if subtotal is not None else "not updated"
        return f"Verified subtotal {amount} · {count} projects; full total not updated"
    if full is not None:
        return f"全量合计 {fmt_usd(full)}，{count} 项"
    amount = fmt_usd(subtotal) if subtotal is not None else "未更新"
    return f"已验证小计 {amount}，{count} 项；全量合计未更新"
