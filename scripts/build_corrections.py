#!/usr/bin/env python3
"""Publish an additive correction index. Never rewrite dated reports/snapshots."""
import csv
import datetime as dt
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = '2026-10-07'


def build(root=ROOT):
    audits = {}
    with (root / 'docs/refresh-investigation/historical-refresh-audit.csv').open() as f:
        for row in csv.DictReader(f):
            audits.setdefault(row['date'], []).append(row)
    dates = sorted(p.stem for p in (root / 'reports').glob('????-??-??.md') if p.stem <= CUTOFF)
    entries = []
    for date in dates:
        evidence = audits.get(date, [])
        logged = [r for r in evidence if r.get('catalog_refresh')]
        entry = {'date': date, 'status': 'collection_incomplete' if logged else 'observation_evidence_missing',
                 'daily_and_weekly_growth': 'unverifiable',
                 'explanation': '采集日志确认目录刷新不完整；原刊零变化不能作为零增长证据。' if logged else '缺少字段级原始观测时间，无法可靠重算日／周增长。',
                 'watches': [r['watches_fetched'] for r in logged],
                 'catalog': [r['catalog_refresh'] for r in logged],
                 'original_report': f'reports/{date}.md'}
        if (root / 'site/editions' / (date + '.html')).exists():
            entry['original_edition'] = f'editions/{date}.html'
        entries.append(entry)
    payload = {'generated_at': dt.datetime.now(dt.UTC).isoformat(), 'cutoff': CUTOFF,
               'policy': 'originals_preserved_no_historical_growth_imputed', 'entries': entries}
    target = root / 'site/api/corrections.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    rows = []
    for entry in reversed(entries):
        link = entry.get('original_edition', entry['original_report'])
        coverage = ('目录 ' + ', '.join(entry['catalog']) + '；关注 ' + ', '.join(entry['watches'])) if entry['catalog'] else '原始观测证据不足'
        rows.append(f'<article id="{entry["date"]}"><h2>{entry["date"]} · 增量无法核实</h2><p>{html.escape(entry["explanation"])}</p><p>{html.escape(coverage)}</p><a href="./{html.escape(link)}">查看原刊（仅供留档核对）</a></article>')
    (root / 'site/corrections.html').write_text('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>历史日报勘误 · KS Tracker</title>
<style>body{max-width:900px;margin:24px auto;padding:0 20px;background:#f9f9f7;color:#111;font:16px/1.7 system-ui}h1{font-size:30px}h2{font-size:20px}article{padding:18px 0;border-top:1px solid #777;overflow-wrap:anywhere}a{color:#a00}.notice{border:2px solid #a00;padding:16px}</style>
<h1>历史日报勘误与可靠性说明</h1><p><a href="./">最新看板</a> · <a href="./editions/">原刊与修订版</a></p>
<div class="notice">2026年10月7日上线前的日报缺少可信字段观测时间。已核实的9月1日至10月7日运行还存在目录刷新不完整。原刊中的日／周增长、零变化榜单和项目状态可能受影响；邮件送达成功不代表数据刷新成功。</div>
<p>原刊和历史快照均保留。没有用今天的值倒推过去，也没有把缺失增量补零。以下逐日标注已知证据；无日志的日期标为无法核实，不推定当天所有来源都失败。10月7日上线后的修订预览以版本中的字段观测信息为准。</p>
''' + '\n'.join(rows) + '</html>')
    return payload


if __name__ == '__main__':
    result = build()
    print(f"correction entries: {len(result['entries'])}; originals unchanged")
