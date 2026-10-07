#!/usr/bin/env python3
"""One public, read-only GraphQL currency contract query; no scraper writes/mail."""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def probe():
    from scraper import project, session_state
    # No proxy discovery, saved sessions, credential access or session writes.
    project.pick_proxy = lambda: None
    session_state.get_cookies = lambda: {}
    for method in ('update_cookies', 'set_ua', 'mark_warmed'):
        setattr(session_state, method, lambda *args, **kwargs: None)
    if shutil.which('google-chrome'):
        os.environ['KS_BROWSER_EXECUTABLE'] = shutil.which('google-chrome')
    rows = json.loads((ROOT / 'data/projects.json').read_text())['projects']
    slugs, currencies = [], set()
    for row in rows:
        currency = row.get('observations', {}).get('pledged_native', {}).get('unit')
        if row['status'] == 'live' and currency in {'HKD', 'USD', 'GBP'} and currency not in currencies:
            currencies.add(currency)
            slugs.append(row['pathname'].rsplit('/', 1)[-1])
    transport = project._open_playwright_transport('currency_contract', verbose=False)
    if transport is None:
        return {'status': 'source_access_unavailable', 'queries': 0}
    try:
        declarations = ', '.join(f'$s{i}: String!' for i in range(len(slugs)))
        fields = 'currency usdExchangeRate pledged { amount currency } goal { amount currency } rewards(first:30) { nodes { amount { amount currency } } pageInfo { hasNextPage endCursor } }'
        selections = '\n'.join(f'p{i}: project(slug: $s{i}) {{ {fields} }}' for i in range(len(slugs)))
        status, payload = transport.post_graphql({'operationName': 'CurrencyContract',
            'variables': {f's{i}': slug for i, slug in enumerate(slugs)},
            'query': f'query CurrencyContract({declarations}) {{ {selections} }}'})
        return {'status': 'sample_success' if status == 200 and isinstance(payload, dict) and payload.get('data') and not payload.get('errors') else 'sample_unavailable',
                'http_status': status, 'queries': 1, 'public_slugs': slugs,
                'data': payload.get('data') if isinstance(payload, dict) else None,
                'errors': [{'message': e.get('message'), 'path': e.get('path')} for e in (payload or {}).get('errors', [])] if isinstance(payload, dict) else []}
    finally:
        transport.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT) or output.exists():
        parser.error('--output must be a new file outside the checkout')
    try:
        result = probe()
    except Exception as exc:
        result = {'status': 'probe_error', 'exception_type': type(exc).__name__}
    result['emails_sent'] = 0
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
