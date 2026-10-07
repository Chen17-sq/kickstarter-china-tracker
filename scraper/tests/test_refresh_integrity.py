"""Regression coverage for data failures independently of delivery outcomes."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from scraper import health, momentum, project, refresh
from scraper.discover import _hit_from_proj
from scraper.observations import carry_row, comparable_delta, delta_text, observe
from scraper.quality import assess
from scraper.sanity import validate_for_send


@pytest.fixture(autouse=True)
def isolated_metrics(monkeypatch):
    monkeypatch.setattr("scraper.tier_metrics.record", lambda *args, **kwargs: None)


NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


def row(at=NOW, **values):
    result = {"pathname": "/projects/example/test", "title": "Test", "status": "live", "native_currency": "USD"}
    for key, value in {"followers": 100, "backers": 10, "pledged_usd": 1000, **values}.items():
        observe(result, key, value, at=at.isoformat(), source="fixture", basis="native_usd" if key == "pledged_usd" else key)
    return result


@pytest.mark.parametrize("value,expected", [(1000, 0), (1250, 250), (900, -100)])
def test_true_zero_nonzero_and_negative(value, expected):
    before = row(NOW - dt.timedelta(days=1))
    current = row(pledged_usd=value)
    delta, evidence = comparable_delta(current, before, "pledged_usd", now=NOW)
    assert delta == expected
    assert evidence["status"] == "valid"


@pytest.mark.parametrize("value", [None, "garbage", float("nan"), float("inf"), True])
def test_missing_or_invalid_never_becomes_zero(value):
    current, before = row(), row(NOW - dt.timedelta(days=1))
    before["pledged_usd"] = value
    assert comparable_delta(current, before, "pledged_usd", now=NOW)[0] is None


def test_legacy_baseline_cannot_borrow_snapshot_timestamp():
    assert comparable_delta(row(), {"pledged_usd": 900, "generated_at": (NOW - dt.timedelta(days=1)).isoformat()}, "pledged_usd", now=NOW)[0] is None


def test_all_failed_carries_original_time_and_removes_old_deltas():
    before = row(NOW - dt.timedelta(days=1))
    before.update(delta_pledged_usd=999, weekly_delta_followers=20)
    current, summary = refresh.apply_refresh([before], {}, verbose=False)
    current = current[0]
    assert summary["refreshed"] == 0
    assert current["pledged_usd"] == 1000
    assert current["observations"]["pledged_usd"]["observed_at"] == before["observations"]["pledged_usd"]["observed_at"]
    assert current["observations"]["pledged_usd"]["status"] == "stale"
    assert "delta_pledged_usd" not in current
    assert "weekly_delta_followers" not in current
    assert comparable_delta(current, before, "pledged_usd", now=NOW)[0] is None


def test_partial_refresh_is_per_field():
    before = row(NOW - dt.timedelta(days=1))
    current, _ = refresh.apply_refresh([before], {"test": {"watchesCount": 0}}, verbose=False)
    assert current[0]["followers"] == 0
    assert current[0]["observations"]["followers"]["status"] == "fresh"
    assert current[0]["observations"]["pledged_usd"]["status"] == "stale"


def test_non_usd_amount_is_not_labelled_usd():
    current, _ = refresh.apply_refresh([row()], {"test": {"pledged_amt": 50000, "pledged_currency": "HKD"}}, verbose=False)
    assert current[0]["pledged_usd"] == 1000
    assert current[0]["observations"]["pledged_usd"]["status"] == "stale"
    assert current[0]["pledged_native"] == 50000
    assert current[0]["observations"]["pledged_native"]["unit"] == "HKD"


def test_currency_basis_and_window_must_match():
    before = row(NOW - dt.timedelta(days=1))
    before["observations"]["pledged_usd"]["basis"] = "native_hkd"
    assert comparable_delta(row(), before, "pledged_usd", now=NOW)[1]["reason"] == "incompatible_basis_or_currency"
    assert comparable_delta(row(), row(NOW - dt.timedelta(days=3)), "pledged_usd", now=NOW)[1]["reason"] == "incompatible_window"


def test_repeated_carry_does_not_advance_time():
    original = row(NOW - dt.timedelta(days=2))
    carried = carry_row(carry_row(original, at=NOW.isoformat()), at=(NOW + dt.timedelta(days=1)).isoformat())
    assert carried["observations"]["pledged_usd"]["observed_at"] == original["observations"]["pledged_usd"]["observed_at"]


def test_recovery_rerun_uses_yesterday_not_failed_today(tmp_path, monkeypatch):
    monkeypatch.setattr(momentum, "HISTORY", tmp_path)
    before = row(NOW - dt.timedelta(days=1))
    for at, item in [(NOW - dt.timedelta(days=1), before), (NOW - dt.timedelta(minutes=10), carry_row(before, at=NOW.isoformat()))]:
        (tmp_path / (at.strftime("%Y-%m-%dT%H-%M-%SZ") + ".json")).write_text(json.dumps({"generated_at": at.isoformat(), "projects": [item]}))
    current = row(pledged_usd=1200)
    momentum.compute_deltas([current], now=NOW)
    assert current["delta_pledged_usd"] == 200
    assert current["delta_meta"]["delta_pledged_usd"]["seconds"] == 86400
    momentum.compute_deltas([current], now=NOW)
    assert current["delta_pledged_usd"] == 200  # idempotent


def test_quality_freshness_and_zero_anomaly_are_distinct(monkeypatch):
    current = row()
    current["delta_meta"] = {"delta_pledged_usd": {"status": "valid"}, "delta_backers": {"status": "valid"}}
    current.update(delta_pledged_usd=0, delta_backers=0)
    q = assess({"projects": [current] * 25}, now=NOW)
    assert q["metrics"]["pledged_usd"]["fresh"] == 25
    assert any("suspicious zero" in i for i in q["issues"])
    snapshot = {"schema_version": 2, "projects": [carry_row(row(), at=NOW.isoformat())]}
    monkeypatch.delenv("KS_QUALITY_POLICY", raising=False)
    assert validate_for_send(snapshot)[0]  # policy remains observe pending owner decision
    monkeypatch.setenv("KS_QUALITY_POLICY", "enforce")
    assert not validate_for_send(snapshot)[0]


def test_discover_zero_is_not_replaced_by_fallback_and_currency_checked():
    assert _hit_from_proj({"usd_pledged": 0, "converted_pledged_amount": 900}).pledged_usd == 0
    assert _hit_from_proj({"converted_pledged_amount": 900, "current_currency": "HKD"}).pledged_usd is None
    assert _hit_from_proj({"converted_pledged_amount": 900, "current_currency": "USD"}).pledged_usd == 900


class FakeTransport:
    mode = "fixture"
    def __init__(self, response):
        self.response = response
    def post_graphql(self, body):
        return self.response


def test_http_200_null_or_errors_never_synthesize_zero():
    for body in [{"data": {"p0": None}}, {"errors": [{"message": "error"}]}, {"data": {"p0": {"pledged": {"currency": "USD", "amount": None}}}}]:
        out = refresh.fetch_fat_graphql(["test"], transport=FakeTransport((200, body)), verbose=False)
        updated, _ = refresh.apply_refresh([row()], out, verbose=False)
        assert updated[0]["pledged_usd"] == 1000
        assert updated[0]["observations"]["pledged_usd"]["status"] == "stale"


def test_watch_missing_vs_failed_vs_zero():
    failed = project.fetch_watches_counts(["test"], transport=FakeTransport((403, None)), verbose=False)
    missing = project.fetch_watches_counts(["test"], transport=FakeTransport((200, {"data": {"p0": {"watchesCount": None}}})), verbose=False)
    zero = project.fetch_watches_counts(["test"], transport=FakeTransport((200, {"data": {"p0": {"watchesCount": 0}}})), verbose=False)
    assert failed.errors["test"] == "http_403"
    assert missing.errors["test"] == "source_missing"
    assert zero["test"] == 0


def test_failed_shared_transport_does_not_open_three_more(monkeypatch):
    monkeypatch.setattr(project, "_open_transport", lambda **kw: pytest.fail("unexpected reopen"))
    monkeypatch.setattr(refresh, "_open_transport", lambda **kw: pytest.fail("unexpected reopen"))
    assert project.fetch_watches_counts(["test"], transport=None)["test"] is None
    assert project.fetch_pledge_minimums(["test"], transport=None)["test"] is None
    assert refresh.fetch_fat_graphql(["test"], transport=None)["test"] == {}


def test_reward_currency_is_explicit():
    body = {"data": {"p0": {"rewards": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [{"amount": {"amount": 10, "currency": "HKD"}}]}}}}
    assert project.fetch_pledge_minimums(["test"], transport=FakeTransport((200, body)))["test"] is None


def test_zero_and_unavailable_display_differ():
    current = row()
    current["delta_pledged_usd"] = 0
    current["delta_meta"] = {"delta_pledged_usd": {"status": "valid"}}
    assert delta_text(current, "pledged_usd") == "$0"
    current["delta_pledged_usd"] = None
    assert delta_text(current, "pledged_usd") == "无法计算"


def test_nodriver_reuses_one_loop_and_closes_background_tasks():
    import asyncio

    from scraper.nodriver_transport import NodriverTransport

    loop = asyncio.new_event_loop()
    calls = []
    class Browser:
        def stop(self):
            calls.append("stopped")
    class Page:
        async def evaluate(self, expr, **kwargs):
            assert asyncio.get_running_loop() is loop
            calls.append("query")
            return {"status": 200, "text": '{"data":{}}'}
    async def boot():
        background = asyncio.create_task(asyncio.sleep(100))
        assert not background.done()
        return NodriverTransport(Browser(), Page(), "fixture-csrf", loop=loop)
    transport = loop.run_until_complete(boot())
    assert transport.post_graphql({}) == (200, {"data": {}})
    assert transport.post_graphql({}) == (200, {"data": {}})
    transport.close()
    transport.close()
    assert loop.is_closed()
    assert calls == ["query", "query", "stopped"]


def test_schema_v2_keeps_structural_sanity_guards(monkeypatch):
    monkeypatch.setenv("KS_QUALITY_POLICY", "observe")
    duplicate = {"schema_version": 2, "projects": [row(), row()]}
    assert not validate_for_send(duplicate)[0]
    invalid = row()
    invalid["pledged_usd"] = float("nan")
    assert not validate_for_send({"schema_version": 2, "projects": [invalid]})[0]


def test_legacy_history_does_not_make_changelog_growth():
    from scraper.diff import diff_snapshots
    before = {"projects": [{"pathname": "/a", "followers": 10}]}
    after = {"projects": [{"pathname": "/a", "followers": 1000}]}
    assert not any(c.kind == "followers_delta" for c in diff_snapshots(before, after))


@pytest.mark.parametrize("scenario,valid,attempts", [("all-failed", 0, 3), ("partial", 24, 3), ("healthy", 29, 3), ("recovery", 29, 4), ("currency", 29, 3), ("aliases", 29, 3)])
def test_isolated_pipeline_never_sends_or_changes_source(tmp_path, scenario, valid, attempts):
    import hashlib
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    source = root / "data" / "projects.json"
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / scenario
    result = subprocess.run([sys.executable, str(root / "scripts" / "dry_run.py"), "--scenario", scenario, "--output", str(output)], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads((output / "dry-run-result.json").read_text())
    assert summary["daily_delta_valid"] == valid
    assert summary["history_attempts"] == attempts
    assert summary["network_calls"] == summary["emails_sent"] == 0
    html = (output / "site" / "integrity_preview.html").read_text()
    assert "无法计算" in html
    assert "'OBSERVED_AT':" not in html
    assert "'observed_at':" not in html
    assert before == hashlib.sha256(source.read_bytes()).hexdigest()


def test_anomaly_window_uses_days_not_number_of_files(tmp_path, monkeypatch):
    from scraper import anomalies
    monkeypatch.setattr(anomalies, "HISTORY", tmp_path)
    for days in (0, 1, 2, 3, 4, 5, 6, 7):
        at = (NOW - dt.timedelta(days=days)).isoformat()
        (tmp_path / f"{days}.json").write_text(json.dumps({"generated_at": at, "days": days}))
    assert anomalies._load_history_snapshot(7)["days"] == 7


def test_export_cards_do_not_present_carried_values_as_current():
    from scraper.banner import build_og_svg, build_snapshot_svg, build_svg
    from scraper.social import _detail_row, _list_row
    stale = carry_row(row(NOW - dt.timedelta(days=1)), at=NOW.isoformat())
    snapshot = {"schema_version": 2, "projects": [stale]}
    assert "PLEDGED · 未更新" in build_svg(snapshot)
    assert "DATA DEGRADED" in build_og_svg(snapshot)
    assert "排名仅供历史参考" in build_snapshot_svg(snapshot)
    for html in (_detail_row(1, stale, kind="live", hl_map={}), _list_row(1, stale, kind="live")):
        assert "未更新" in html
        assert "$1.0K" not in html
    assert "$1.0K" in _list_row(1, row(), kind="live")


def test_baseline_uses_successful_rerun_when_nearest_attempt_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(momentum, "HISTORY", tmp_path)
    failed_at = NOW - dt.timedelta(days=1)
    success_at = failed_at + dt.timedelta(hours=2)
    for label, at, project_row in [
        ('failed', failed_at, {"pathname": row()["pathname"], "pledged_usd": 123}),
        ('recovered', success_at, row(success_at, pledged_usd=900)),
    ]:
        (tmp_path / f'{label}.json').write_text(json.dumps({'generated_at': at.isoformat(), 'projects': [project_row]}))
    current = row()
    momentum.compute_deltas([current], now=NOW)
    assert current['delta_pledged_usd'] == 100
    assert current['delta_meta']['delta_pledged_usd']['from'] == success_at.isoformat()


def test_expired_valid_delta_does_not_count_as_comparable():
    p = row(NOW - dt.timedelta(days=2))
    p['delta_pledged_usd'] = 0
    p['delta_meta'] = {'delta_pledged_usd': {'status': 'valid'}}
    q = assess({'projects': [p]}, now=NOW)
    assert q['metrics']['pledged_usd']['fresh'] == 0
    assert q['metrics']['pledged_usd']['comparable'] == 0
    assert momentum.conversion_per_backer(p) is None


def test_auxiliary_notifications_and_ai_context_reject_stale_metrics(tmp_path, monkeypatch):
    from scraper import notify
    from scripts import draft_editor_note
    stale = carry_row(row(NOW - dt.timedelta(days=1)), at=NOW.isoformat())
    snapshot = {'schema_version': 2, 'projects': [stale]}
    path = tmp_path / 'projects.json'
    path.write_text(json.dumps(snapshot))
    monkeypatch.setattr(draft_editor_note, 'PROJECTS_FILE', path)
    monkeypatch.setattr(draft_editor_note, 'HIGHLIGHTS_FILE', tmp_path / 'absent')
    text = draft_editor_note.build_context()
    assert 'raised: 未更新' in text
    assert 'raised: $1,000' not in text
    for dialect in ('slack', 'discord'):
        summary = notify.build_summary(snapshot, dialect=dialect)
        assert '未更新' in summary
        assert '$1.0K' not in summary


def test_old_editor_draft_cannot_leak_into_new_edition(tmp_path, monkeypatch):
    from scraper import email_notify
    monkeypatch.setattr(email_notify, 'REPO_ROOT', tmp_path)
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/.editor_drafts.json').write_text(json.dumps({'snapshot_at': 'old', 'drafts': [{'text': 'old growth'}]}))
    assert email_notify._load_editor_drafts({'generated_at': 'new', 'projects': [row()]}) is None


def test_enforcement_cannot_be_bypassed_by_legacy_schema(monkeypatch):
    monkeypatch.setenv('KS_QUALITY_POLICY', 'enforce')
    legacy = {'projects': [{'pathname': '/a', 'status': 'live', 'followers': 100, 'backers': 10, 'pledged_usd': 1000}]}
    allowed, issues = validate_for_send(legacy)
    assert not allowed
    assert any('fresh 0/' in issue for issue in issues)


def test_delivery_pause_applies_before_any_reads_or_writes(tmp_path, monkeypatch):
    from scraper import email_notify
    monkeypatch.setenv('KS_EMAIL_DELIVERY', 'paused')
    monkeypatch.setattr(email_notify, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(email_notify, 'PROJECTS', tmp_path / 'missing.json')
    assert email_notify.main([]) == 0
    assert list(tmp_path.iterdir()) == []


def test_health_reports_actual_enforcement_mode(monkeypatch):
    monkeypatch.setenv('KS_QUALITY_POLICY', 'enforce')
    quality = assess({'projects': [row()]})
    assert quality['policy_mode'] == 'enforce'
    assert any('(enforce mode)' in line for line in health.format_digest_lines({'data_quality': quality}))
