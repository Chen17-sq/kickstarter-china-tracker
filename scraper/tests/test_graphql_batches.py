"""Multi-batch failures seen in production must not hide behind single-batch fixtures."""
import datetime as dt

import pytest

from scraper import health, project, refresh
from scraper.graphql import fetch_projects
from scraper.observations import observe


@pytest.fixture(autouse=True)
def no_delays_or_writes(monkeypatch):
    monkeypatch.setattr('scraper.backoff.chunk_pause', lambda *args: None)
    monkeypatch.setattr('scraper.tier_metrics.record', lambda *args: None)
    health.reset()


class LimitedServer:
    mode = 'fixture'

    def __init__(self, limit=44):
        self.limit = limit
        self.calls = []

    def post_graphql(self, body):
        self.calls.append(body)
        if len(body['variables']) > self.limit:
            return 200, {'data': None, 'errors': [{'message': 'Query complexity exceeds maximum'}]}
        return 200, {'data': {'p' + alias[1:]: {'watchesCount': int(slug), 'backersCount': 0,
                            'pledged': {'amount': int(slug), 'currency': 'USD'}}
                            for alias, slug in body['variables'].items()}}


def test_catalog_all_chunks_survive_including_exact_multiple():
    for total in (40, 101, 943):
        server = LimitedServer()
        data = refresh.fetch_fat_graphql([str(i) for i in range(total)], transport=server, verbose=False)
        assert len(data) == total
        assert all(data[str(i)]['watchesCount'] == i for i in range(total))
        assert max(len(c['variables']) for c in server.calls) == 20


def test_explicit_complexity_error_splits_within_budget():
    server = LimitedServer(limit=10)
    data = refresh.fetch_fat_graphql([str(i) for i in range(41)], transport=server, verbose=False)
    assert sum(d.get('pledged_amt') is not None for d in data.values()) == 41
    assert len(server.calls) == 7
    assert any(e['result'] == 'query_complexity_limit' for e in health._state['graphql_batches'])


@pytest.mark.parametrize('status', [401, 403, 429])
def test_denial_stops_shared_session_across_metrics(status):
    class Denied:
        mode = 'fixture'
        calls = 0
        def post_graphql(self, body):
            self.calls += 1
            return status, None
    server = Denied()
    watches = project.fetch_watches_counts([str(i) for i in range(101)], transport=server, verbose=False)
    refresh.fetch_fat_graphql(['1', '2'], transport=server, verbose=False)
    project.fetch_pledge_minimums(['1'], transport=server, verbose=False)
    assert server.calls == 1
    assert set(watches.values()) == {None}
    assert set(watches.errors.values()) == {f'http_{status}'}


@pytest.mark.parametrize('path', [None, ['p0'], ['p0', 'pledged', 'amount']])
def test_graphql_errored_fields_cannot_become_success(path):
    class Partial:
        mode = 'fixture'
        def post_graphql(self, body):
            return 200, {'data': {'p0': {'watchesCount': 8, 'pledged': {'amount': 999, 'currency': 'USD'}}},
                         'errors': [{'path': path, 'message': 'resolver failed'}]}
    data = refresh.fetch_fat_graphql(['1'], transport=Partial(), verbose=False)
    assert data['1']['pledged_amt'] is None
    assert data['1']['watchesCount'] == (8 if path and len(path) > 1 else None)


def test_healthy_sibling_survives_other_project_failure():
    class Partial:
        mode = 'fixture'
        def post_graphql(self, body):
            return 200, {'data': {'p0': None, 'p1': {'watchesCount': 0}},
                         'errors': [{'path': ['p0'], 'message': 'unavailable'}]}
    values = project.fetch_watches_counts(['1', '2'], transport=Partial(), verbose=False)
    assert values['1'] is None and values['2'] == 0


def test_invalid_shapes_do_not_crash_or_reinvent_values():
    class Bad:
        def post_graphql(self, body):
            return 200, {'errors': 'invalid', 'data': ['not a map']}
    result = fetch_projects(['a'], transport=Bad(), fields='watchesCount', operation='Watches', batch_size=20, source='test')
    assert result['a']['data'] == {}
    assert result['a']['error'] == 'graphql_error'


def test_nodriver_deserializes_explicit_json_string():
    import asyncio
    import json

    from scraper.nodriver_transport import NodriverTransport
    class Page:
        async def evaluate(self, expression, **kwargs):
            assert 'JSON.stringify' in expression
            return json.dumps({'status': 200, 'text': '{"data":{"p0":{"watchesCount":0}}}'})
    class Browser:
        def stop(self):
            pass
    transport = NodriverTransport(Browser(), Page(), 'fixture', loop=asyncio.new_event_loop())
    try:
        assert transport.post_graphql({}) == (200, {'data': {'p0': {'watchesCount': 0}}})
    finally:
        transport.close()
