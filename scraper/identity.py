"""Deduplicate only identities explicitly supplied by Kickstarter, never titles."""
from __future__ import annotations

import copy
from urllib.parse import urlparse

from .observations import METRICS, is_fresh, parse_time


def observe_identity(row, project_id, url, *, at, source):
    if isinstance(project_id, bool) or not isinstance(project_id, int) or project_id <= 0:
        return
    parsed = urlparse(url or '')
    canonical = (parsed.path.rstrip('/') if parsed.hostname in {'www.kickstarter.com', 'kickstarter.com'}
                 and parsed.path.startswith('/projects/') and len(parsed.path.rstrip('/').split('/')) == 4 else None)
    row['project_id'] = project_id
    row['identity_observation'] = {'project_id': project_id, 'source': source,
                                   'observed_at': at, 'canonical_pathname': canonical}


def verified_id(row):
    evidence = row.get('identity_observation', {})
    pid = row.get('project_id')
    return pid if (isinstance(pid, int) and not isinstance(pid, bool) and pid > 0
                   and evidence.get('project_id') == pid and parse_time(evidence.get('observed_at'))
                   and evidence.get('source') in {'ks_graphql', 'ks_discover'}) else None


def deduplicate_projects(rows):
    groups = {}
    for i, row in enumerate(rows):
        pid = verified_id(row)
        groups.setdefault(('id', pid) if pid else ('unverified', i), []).append(row)
    unique, aliases = [], []
    for group in groups.values():
        # Prefer the official current URL when already present, then a stable
        # path. Successful fields are selected separately below.
        group.sort(key=lambda r: (r.get('pathname') != r.get('identity_observation', {}).get('canonical_pathname'),
                                  r.get('pathname', '')))
        winner = copy.deepcopy(group[0])
        paths = set()
        for row in group:
            paths.add(row['pathname'])
            paths.update(row.get('aliases', []))
            for key in METRICS:
                old = winner.get('observations', {}).get(key, {})
                new = row.get('observations', {}).get(key, {})
                if is_fresh(row, key) and (not is_fresh(winner, key) or new.get('observed_at', '') > old.get('observed_at', '')):
                    winner[key] = row[key]
                    winner.setdefault('observations', {})[key] = copy.deepcopy(new)
                    if key == 'pledged_native':
                        winner['native_currency'] = row.get('native_currency')
            state = row.get('status_observation', {})
            old_state = winner.get('status_observation', {})
            if state.get('status') == 'fresh' and (old_state.get('status') != 'fresh' or state.get('observed_at', '') > old_state.get('observed_at', '')):
                for key in ('status', 'raw_state', 'status_observation'):
                    winner[key] = copy.deepcopy(row.get(key))
            if not winner.get('blurb_zh') and row.get('blurb_zh'):
                winner['blurb_zh'] = row['blurb_zh']
        winner['aliases'] = sorted(paths - {winner['pathname']})
        for path in winner['aliases']:
            aliases.append({'pathname': path, 'canonical_pathname': winner['pathname'],
                            'project_id': verified_id(winner),
                            'identity_observation': winner.get('identity_observation')})
        unique.append(winner)
    return unique, aliases


def align_snapshot(snapshot, reference):
    """Read-only identity alignment for comparisons; never rewrite observations."""
    by_id, by_path = {}, {}
    for row in reference.get('projects', []):
        pid = verified_id(row)
        if pid:
            target = (row['pathname'], pid)
            by_id[pid] = target
            for path in [row['pathname'], *row.get('aliases', [])]:
                by_path[path] = target
    grouped = {}
    for row in snapshot.get('projects', []):
        original = row.get('pathname')
        pid = verified_id(row)
        target = by_id.get(pid) or by_path.get(original)
        path = target[0] if target and (not pid or pid == target[1]) else original
        # Prefer an existing canonical record; values/timestamps stay from one
        # actual historical record, never from the current snapshot.
        if path not in grouped or original == path:
            grouped[path] = {**row, 'pathname': path}
    return {**snapshot, 'projects': list(grouped.values())}
