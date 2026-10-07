"""Bounded GraphQL batches with per-field errors and shared access-denial state."""
from __future__ import annotations

import re

from . import backoff, health
from .observations import timestamp

# Full catalog queries expand substantially more fields than watcher queries.
CATALOG_BATCH_SIZE = 20
_LIMIT = re.compile(r"complexity|too complex|query.{0,20}cost|maximum.{0,20}(?:aliases|complexity)|too many (?:fields|aliases)", re.I)


def invalid_field(errors, alias, field):
    """A sibling field error must not discard successful data on this project."""
    return any(not e.get("path") or (e["path"][0] == alias and (
        len(e["path"]) == 1 or e["path"][1] == field)) for e in errors)


def fetch_projects(slugs, *, transport, fields, operation, batch_size, source):
    slugs = list(dict.fromkeys(slugs))
    result = {slug: {"data": {}, "error": "fetch_failed", "invalid_fields": set()} for slug in slugs}
    if transport is None:
        return result
    budget = 4 * ((len(slugs) + batch_size - 1) // batch_size) + 4
    requests = 0

    def fetch(chunk):
        nonlocal requests
        blocked = getattr(transport, "_ks_blocked_status", None)
        if blocked is not None:
            for slug in chunk:
                result[slug]["error"] = f"http_{blocked}"
            health.graphql_batch(source, len(chunk), 0, f"circuit_open_{blocked}")
            return
        if requests >= budget:
            for slug in chunk:
                result[slug]["error"] = "request_budget_exhausted"
            health.graphql_batch(source, len(chunk), 0, "request_budget_exhausted")
            return
        if requests:
            backoff.chunk_pause(1, 3)
        requests += 1
        declarations = ", ".join(f"$s{i}: String!" for i in range(len(chunk)))
        selection = "\n".join(f"p{i}: project(slug: $s{i}) {{ {fields} }}" for i in range(len(chunk)))
        body = {"operationName": operation, "query": f"query {operation}({declarations}) {{ {selection} }}",
                "variables": {f"s{i}": slug for i, slug in enumerate(chunk)}}
        try:
            status, response = transport.post_graphql(body)
        except Exception:
            status, response = -1, None
        error = f"http_{status}"
        if status in (401, 403, 429):
            # Stop this shared session. A smaller query does not cure access
            # denial or rate limiting; do not switch identity or retry here.
            transport._ks_blocked_status = status
        if status == 200 and isinstance(response, dict):
            errors = response.get("errors") or []
            if not isinstance(errors, list) or any(not isinstance(e, dict) for e in errors):
                errors = [{"message": "invalid errors shape"}]
            # Keep only valid structured paths; malformed paths are global errors.
            errors = [{**e, "path": e.get("path") if isinstance(e.get("path"), list) else None} for e in errors]
            data = response.get("data")
            if errors and any(_LIMIT.search(str(e.get("message", ""))) for e in errors) and not data and len(chunk) > 1:
                health.graphql_batch(source, len(chunk), 0, "query_complexity_limit")
                midpoint = len(chunk) // 2
                fetch(chunk[:midpoint])
                fetch(chunk[midpoint:])
                return
            if isinstance(data, dict):
                count = 0
                for i, slug in enumerate(chunk):
                    alias = f"p{i}"
                    obj = data.get(alias)
                    obj = obj if isinstance(obj, dict) else {}
                    invalid = {key for key in obj if invalid_field(errors, alias, key)}
                    clean = {key: value for key, value in obj.items() if key not in invalid}
                    relevant_error = any(not e.get("path") or e["path"][0] == alias for e in errors)
                    count += bool(clean)
                    result[slug] = {"data": clean, "error": "graphql_error" if relevant_error else "source_missing",
                                    "invalid_fields": invalid, "observed_at": timestamp()}
                health.graphql_batch(source, len(chunk), count, "graphql_partial_error" if errors else "response")
                return
            error = "graphql_error" if errors else "invalid_response"
        elif status == 200:
            error = "invalid_response"
        health.fetch_error(source, error, len(chunk))
        health.graphql_batch(source, len(chunk), 0, error)
        for slug in chunk:
            result[slug]["error"] = error

    for offset in range(0, len(slugs), batch_size):
        fetch(slugs[offset:offset + batch_size])
    return result
