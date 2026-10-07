import datetime as dt
import hashlib
import importlib.util
from pathlib import Path

import pytest

from scraper import health, project, refresh
from scraper.money import observe_money, to_usd
from scraper.observations import comparable_delta, metric_text, observe

NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    health.reset()
    monkeypatch.setattr('scraper.backoff.chunk_pause', lambda *args: None)
    monkeypatch.setattr('scraper.tier_metrics.record', lambda *args: None)


@pytest.mark.parametrize('amount,currency,project_currency,rate,expected', [
    (100,'HKD','HKD',.128,12.8),(100,'GBP','GBP',1.25,125),
    (0,'HKD','HKD',.128,0),(100,'USD','USD',None,100),
    (100,'HKD','USD',.128,None),(100,'HKD','HKD',None,None),
    (100,'HKD','HKD',0,None),(100,'HKD','HKD',float('nan'),None)])
def test_explicit_project_currency_conversion(amount,currency,project_currency,rate,expected):
    result=to_usd(amount,currency,project_currency,rate)
    assert (result['amount'] if result else None) == expected


def test_catalog_refresh_uses_current_rate_and_updates_goal_without_legacy_guess():
    before={'pathname':'/projects/a/example','native_currency':'HKD','static_usd_rate':.5,'pledged_usd':999}
    rows,_=refresh.apply_refresh([before], {'example':{'currency':'HKD','usd_exchange_rate':.128,
        'pledged_currency':'HKD','pledged_amt':1000,'goal_currency':'HKD','goal_amt':2000}},verbose=False)
    assert rows[0]['pledged_usd']==128
    assert rows[0]['goal_usd']==256
    assert rows[0]['observations']['pledged_usd']['conversion']['rate']==.128
    assert rows[0]['native_currency']=='HKD'


@pytest.mark.parametrize('native,expected',[(100,0),(110,1.3),(90,-1.3)])
def test_currency_delta_excludes_fx_changes_and_can_use_verified_native_baseline(native,expected):
    baseline,current={},{}
    observe(baseline,'pledged_native',100,at=(NOW-dt.timedelta(days=1)).isoformat(),source='ks_graphql',unit='HKD',basis='native_pledged:HKD')
    observe(current,'pledged_native',native,at=NOW.isoformat(),source='ks_graphql',unit='HKD',basis='native_pledged:HKD')
    observe_money(current,'pledged_usd',to_usd(native,'HKD','HKD',.13),at=NOW.isoformat(),source='ks_graphql')
    value,meta=comparable_delta(current,baseline,'pledged_usd',now=NOW)
    assert value==pytest.approx(expected)
    assert meta['method']=='constant_currency' and meta['usd_rate']==.13
    baseline['observations']['pledged_native']['unit']='GBP'
    assert comparable_delta(current,baseline,'pledged_usd',now=NOW)[0] is None


def rewards(nodes,next_page=False,cursor=None):
    return {'nodes':[{'amount':{'amount':n,'currency':'HKD'}} for n in nodes],
            'pageInfo':{'hasNextPage':next_page,'endCursor':cursor}}


class Paged:
    mode='fixture'
    def __init__(self,second=None):
        self.calls=[]
        self.second=second or rewards([8])
    def post_graphql(self,body):
        self.calls.append(body)
        r=rewards([10,20],True,'next') if len(self.calls)==1 else self.second
        return 200,{'data':{'p0':{'currency':'HKD','usdExchangeRate':.128,'rewards':r}}}


def test_minimum_fetches_remaining_pages_before_selecting():
    server=Paged()
    values=project.fetch_pledge_minimums(['example'],transport=server,verbose=False)
    assert values['example']==pytest.approx(8*.128)
    assert values.money['example']['currency']=='HKD'
    assert len(server.calls)==2 and 'after: "next"' in server.calls[1]['query']


def test_incomplete_or_looping_rewards_never_publish_partial_minimum():
    server=Paged(rewards([8],True,'next'))
    values=project.fetch_pledge_minimums(['example'],transport=server,verbose=False)
    assert values['example'] is None
    assert values.errors['example']=='reward_pagination_incomplete'
    assert len(server.calls)==2


def test_empty_rewards_are_distinct_from_network_failure():
    class Empty:
        mode='fixture'
        def post_graphql(self,body):
            return 200,{'data':{'p0':{'rewards':rewards([])}}}
    result=project.fetch_pledge_minimums(['example'],transport=Empty(),verbose=False)
    assert result['example'] is None and result.errors['example']=='no_rewards'
    assert metric_text({'observations':{'min_pledge_usd':{'reason':'no_rewards'}}},'min_pledge_usd')=='暂无档位'


def test_correction_index_is_additive_and_labels_no_log_dates(tmp_path):
    script=Path(__file__).resolve().parents[2]/'scripts/build_corrections.py'
    spec=importlib.util.spec_from_file_location('corrections',script)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path/'reports').mkdir()
    (tmp_path/'site/editions').mkdir(parents=True)
    audit=tmp_path/'docs/refresh-investigation'
    audit.mkdir(parents=True)
    (audit/'historical-refresh-audit.csv').write_text('date,catalog_refresh,watches_fetched\n2026-10-07,0/980,0/248\n')
    original=tmp_path/'reports/2026-10-07.md'
    original.write_text('published original')
    (tmp_path/'reports/2026-09-01.md').write_text('unverified original')
    digest=hashlib.sha256(original.read_bytes()).hexdigest()
    result=module.build(tmp_path)
    assert len(result['entries'])==2
    assert result['entries'][0]['status']=='observation_evidence_missing'
    assert result['entries'][1]['status']=='collection_incomplete'
    assert hashlib.sha256(original.read_bytes()).hexdigest()==digest
