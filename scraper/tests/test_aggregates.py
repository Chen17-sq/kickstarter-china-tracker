"""Fundraising coverage contract shared by API, reports and both browser pages."""
import copy
import datetime as dt
import json
import subprocess
from pathlib import Path

import pytest

from scraper.aggregates import live_pledged_text, live_pledged_totals
from scraper.api import build_payload
from scraper.email_notify import build_html, build_plaintext
from scraper.notify import build_summary, get_summary_data
from scraper.report import make_report

NOW = dt.datetime(2026, 10, 10, 4, tzinfo=dt.UTC)
ROOT = Path(__file__).resolve().parents[2]


def project(value=10, **meta):
    return {"pathname": "/projects/test/item", "title": "Item", "status": "live",
            "pledged_usd": value, "observations": {"pledged_usd": {
                "status": "fresh", "unit": "USD", "observed_at": NOW.isoformat(), **meta}}}


CASES = [
    ([project(10), project(20)], 30, 30, 2, 2),
    ([project(10), project(999, status="stale")], None, 10, 1, 2),
    ([project(0), project(0)], 0, 0, 2, 2),
    ([project(0), project(999, observed_at=None)], None, 0, 1, 2),
    ([project(None)], None, None, 0, 1),
    ([project(999, status="stale")], None, None, 0, 1),
    ([], None, None, 0, 0),
    ([{**project(999), "status": "successful"}, project(2)], 2, 2, 1, 1),
]
for bad in [True, False, "20", "", "garbage", -1, [], {}, None]:
    CASES.append(([project(5), project(bad)], None, 5, 1, 2))
for meta in [
    {"unit": "HKD"}, {"unit": None}, {"status": "missing"},
    {"observed_at": None}, {"observed_at": []}, {"observed_at": "invalid"},
    {"observed_at": "2026-10-10T04:00:00"},  # naive time
    {"observed_at": "2026-10-10T04:00:01Z"},  # future
    {"observed_at": "2026-10-08T21:59:59Z"},  # expired
    {"observed_at": "2026-02-30T04:00:00Z"},
    {"observed_at": "2026-10-09T24:00:00Z"},
    {"observed_at": "2026-10-10T04:00:00+00:99"},
]:
    CASES.append(([project(5), project(99, **meta)], None, 5, 1, 2))
for at in ["2026-10-08T22:00:00Z", "2026-10-10T12:00:00+08:00"]:
    CASES.append(([project(0, observed_at=at)], 0, 0, 1, 1))
for observations in [None, [], "bad", {"pledged_usd": []}, {"pledged_usd": "bad"}, {}]:
    CASES.append(([{**project(99), "observations": observations}], None, None, 0, 1))


@pytest.mark.parametrize("rows,full,subtotal,verified,total", CASES)
def test_aggregate_contract(rows, full, subtotal, verified, total):
    before = copy.deepcopy(rows)
    result = live_pledged_totals(rows, now=NOW)
    assert result == {"total_live_usd": full, "verified_live_usd_subtotal": subtotal,
                      "live_usd_coverage": {"verified": verified, "total": total}}
    assert rows == before


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), 10**400])
def test_nonfinite_numbers(bad):
    result = live_pledged_totals([project(bad)], now=NOW)
    assert result["verified_live_usd_subtotal"] is None
    assert result["live_usd_coverage"] == {"verified": 0, "total": 1}


def test_overflow_does_not_serialize_infinity():
    result = live_pledged_totals([project(1e308), project(1e308)], now=NOW)
    assert result["total_live_usd"] is None
    assert result["verified_live_usd_subtotal"] is None
    json.dumps(result, allow_nan=False)


def test_browser_uses_same_cases_and_language_contract():
    # Execute the real shared browser helper, not a test-side reimplementation.
    cases = [{"rows": rows, "expected": {"total_live_usd": full,
              "verified_live_usd_subtotal": subtotal,
              "live_usd_coverage": {"verified": verified, "total": total}}}
             for rows, full, subtotal, verified, total in CASES]
    script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {livePledgedTotals, livePledgedText} = require('./site/funds.js');
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
for (const item of cases) {
  const result = livePledgedTotals(item.rows, Date.parse('2026-10-10T04:00:00Z'));
  assert.deepEqual(result, item.expected);
  for (const lang of ['zh', 'en']) {
    const text = livePledgedText(result, lang);
    assert.ok(text.includes(`${result.live_usd_coverage.verified}/${result.live_usd_coverage.total}`));
    if (result.total_live_usd === null) assert.ok(text.includes(lang === 'en' ? 'full total not updated' : '全量合计未更新'));
    if (result.verified_live_usd_subtotal === null) assert.ok(!text.includes('$0'));
    if (lang === 'en') assert.ok(!/[\u4e00-\u9fff]/.test(text));
  }
}
for (const bad of [NaN, Infinity, -Infinity]) {
  const row = {...cases[0].rows[0], pledged_usd: bad};
  assert.equal(livePledgedTotals([row], Date.parse('2026-10-10T04:00:00Z')).verified_live_usd_subtotal, null);
}
'''
    subprocess.run(["node", "-e", script], input=json.dumps(cases), text=True,
                   cwd=ROOT, check=True, capture_output=True)


@pytest.mark.parametrize("amount,stale,expected", [(10, True, 10), (0, True, 0), (0, False, 0), (None, True, None), ("garbage", True, None), ({}, True, None)])
def test_api_report_email_share_contract(amount, stale, expected, monkeypatch, tmp_path):
    # Pure renderers only, isolated cwd and no outbound network permitted.
    import socket
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("Unexpected network"))
    at = dt.datetime.now(dt.UTC).isoformat()
    rows = [project(amount, observed_at=at), project(99 if stale else 0, observed_at=at,
                                                        status="stale" if stale else "fresh")]
    curr = {"schema_version": 2, "generated_at": at, "projects": rows, "delivery_policy": "paused"}
    before = copy.deepcopy(curr)
    payload, summary = build_payload(curr), get_summary_data(curr)
    assert payload["verified_live_usd_subtotal"] == expected
    for key in ("total_live_usd", "verified_live_usd_subtotal", "live_usd_coverage"):
        assert payload[key] == summary[key]
    zh, en = live_pledged_text(summary), live_pledged_text(summary, lang="en")
    assert zh in make_report(curr, None)
    assert zh in build_summary(curr)
    assert zh in build_html(curr)[1]
    assert en in build_plaintext(curr)
    assert curr == before
    assert list(tmp_path.iterdir()) == []


def test_recovery_and_rerun_preserve_original_observation():
    rows = [project(10), project(99, status="stale", observed_at=None)]
    assert live_pledged_totals(rows, now=NOW)["total_live_usd"] is None
    rows[1] = project(20)
    first = live_pledged_totals(rows, now=NOW)
    assert first["total_live_usd"] == 30
    assert live_pledged_totals(rows, now=NOW + dt.timedelta(hours=1)) == first
    assert rows[1]["observations"]["pledged_usd"]["observed_at"] == NOW.isoformat()
    assert live_pledged_totals(rows, now=NOW + dt.timedelta(hours=31))["verified_live_usd_subtotal"] is None


def test_browser_and_report_amount_precision():
    from scraper._common import fmt_usd
    amounts = [0, 2.5, 3.5, 1000, 10500, 11500, 1e6, 1.2e6, 17017406.82772803, 1e9]
    script = "const f=require('./site/funds.js'); console.log(JSON.stringify(" + json.dumps(amounts) + ".map(f.fmtUSD)))"
    result = subprocess.run(["node", "-e", script], cwd=ROOT, check=True, text=True, capture_output=True)
    assert json.loads(result.stdout) == [fmt_usd(amount) for amount in amounts]
