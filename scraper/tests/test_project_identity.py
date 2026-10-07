import datetime as dt

import pytest

from scraper import identity, momentum, refresh, run
from scraper.discover import _hit_from_proj
from scraper.observations import observe

NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


def row(path, pid=None, value=100, at=None, canonical=None):
    at = at or NOW.isoformat()
    r = {'pathname': path, 'title': 'Same title', 'status': 'live', 'raw_state': 'live'}
    observe(r, 'pledged_usd', value, at=at, source='ks_graphql', basis='native_usd')
    identity.observe_identity(r, pid, 'https://www.kickstarter.com' + (canonical or path), at=at, source='ks_graphql')
    return r


@pytest.mark.parametrize('pid', [None, True, 0, -1, '123'])
def test_unverified_ids_and_same_titles_are_never_merged(pid):
    rows = [row('/projects/name/same', pid), row('/projects/123/same', pid)]
    unique, aliases = identity.deduplicate_projects(rows)
    assert len(unique) == 2 and aliases == []


def test_official_identity_deduplicates_alias_and_preserves_fresh_fields_and_history():
    canonical = '/projects/name/same'
    old = row(canonical, 10, value=90, at=(NOW-dt.timedelta(days=1)).isoformat())
    fresh = row('/projects/123/same', 10, canonical=canonical)
    unique, aliases = identity.deduplicate_projects([fresh, old])
    assert len(unique) == 1 and unique[0]['pathname'] == canonical
    assert unique[0]['pledged_usd'] == 100
    assert unique[0]['aliases'] == ['/projects/123/same']
    assert aliases[0]['project_id'] == 10
    assert old['pledged_usd'] == 90 and 'aliases' not in old
    repeated, repeated_aliases = identity.deduplicate_projects(unique)
    assert repeated == unique and repeated_aliases == aliases


def test_different_official_ids_same_title_or_slug_stay_separate():
    rows, aliases = identity.deduplicate_projects([row('/projects/name/same', 10), row('/projects/123/same', 11)])
    assert len(rows) == 2 and aliases == []


def test_catalog_and_discover_record_official_numeric_project_id(monkeypatch):
    monkeypatch.setattr('scraper.backoff.chunk_pause', lambda *a: None)
    class Source:
        def post_graphql(self, body):
            assert 'pid' in body['query'] and 'url' in body['query']
            return 200, {'data': {'p0': {'pid': 17, 'url': 'https://www.kickstarter.com/projects/name/example', 'state': 'LIVE'}}}
    fresh = refresh.fetch_fat_graphql(['example'], transport=Source(), verbose=False)
    rows, _ = refresh.apply_refresh([{'pathname': '/projects/123/example'}], fresh, verbose=False)
    assert identity.verified_id(rows[0]) == 17
    hit = _hit_from_proj({'id': 17, 'urls': {'web': {'project': 'https://www.kickstarter.com/projects/name/example'}}})
    discovered = run.build_row(hit, followers=None, confidence='高', reason='fixture', matched_brand=None, matched_brand_zh=None, blurb_zh=None)
    assert identity.verified_id(discovered) == 17


def test_delta_uses_verified_alias_baseline_and_rejects_different_id(tmp_path, monkeypatch):
    monkeypatch.setattr(momentum, 'HISTORY', tmp_path)
    baseline = row('/projects/123/same', 10, 90, (NOW-dt.timedelta(days=1)).isoformat())
    current = row('/projects/name/same', 10, 100)
    current['aliases'] = [baseline['pathname']]
    momentum._compute([current], {'projects': [baseline]}, NOW-dt.timedelta(days=1), 1, NOW)
    assert current['delta_pledged_usd'] == 10
    baseline['project_id'] = baseline['identity_observation']['project_id'] = 11
    momentum._compute([current], {'projects': [baseline]}, NOW-dt.timedelta(days=1), 1, NOW)
    assert current['delta_pledged_usd'] is None


def test_empty_or_untrusted_identity_evidence_does_not_merge():
    a,b = row('/projects/name/same', 10), row('/projects/123/same', 10)
    b['identity_observation']['source'] = 'legacy_guess'
    unique, _ = identity.deduplicate_projects([a,b])
    assert len(unique) == 2


def test_alias_transition_is_not_new_ended_or_vanished_and_does_not_rewrite_history(monkeypatch):
    import copy

    from scraper import anomalies, diff
    canonical, alias = '/projects/name/same', '/projects/123/same'
    old = row(alias, None, 90, (NOW-dt.timedelta(days=1)).isoformat())
    previous = {'projects': [old]}
    current = row(canonical, 10, 100)
    current['aliases'] = [alias]
    reference = {'projects': [current]}
    before = copy.deepcopy(previous)
    aligned = identity.align_snapshot(previous, reference)
    assert aligned['projects'][0]['pathname'] == canonical
    assert aligned['projects'][0]['observations'] == old['observations']
    assert previous == before
    assert not any(c.kind in {'new','ended'} for c in diff.diff_snapshots(previous, reference))
    monkeypatch.setattr(anomalies, '_load_history_snapshot', lambda *a: None)
    assert anomalies.detect(reference, previous)['vanished'] == []
    conflicting = row(alias, 11)
    assert identity.align_snapshot({'projects':[conflicting]}, reference)['projects'][0]['pathname'] == alias
