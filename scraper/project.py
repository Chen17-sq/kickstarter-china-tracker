"""Fetch supplementary project data via the KS GraphQL endpoint.

The Discover JSON endpoint gives us 90% of what we need (name, creator,
location, country, pledged, backers, staff_pick, deadline …). The one
missing piece — the prelaunch follower count — is *not* in the SSR HTML
either; KS injects it client-side after page mount.

But KS exposes a public GraphQL endpoint at /graph that accepts anonymous
queries with just a CSRF token from the meta tag of any page. The field
is `watchesCount` on the Project type — that's the prelaunch follower
count visible on the "Notify me on launch" UI.

We batch all slugs into a single aliased GraphQL query (chunked at 50)
so 138 projects → ~3 round trips instead of 138.
"""
from __future__ import annotations
import json
import random
import re
import time
from typing import Optional

from curl_cffi import requests as cc_requests
from .http import DEFAULT_COOKIES, IMPERSONATE_ROTATION

GRAPH_URL = "https://www.kickstarter.com/graph"
SEED_URL = "https://www.kickstarter.com/discover/advanced?state=upcoming"
RE_CSRF = re.compile(r'<meta[^>]*name="csrf-token"[^>]*content="([^"]+)"')

CHUNK_SIZE = 50
SEED_MAX_ATTEMPTS = 4


def fetch_watches_counts(slugs: list[str], *, verbose: bool = True) -> dict[str, Optional[int]]:
    """Batch-fetch `watchesCount` for project slugs via KS GraphQL.

    Returns {slug: count_or_None}. Slugs that error out individually still
    appear in the dict mapped to None — callers can fall back gracefully.

    A slug is the *last* segment of the KS pathname:
        /projects/creator/foo-bar  →  "foo-bar"
    """
    out: dict[str, Optional[int]] = {s: None for s in slugs}
    if not slugs:
        return out

    # Step 1: seed a session with retry + TLS impersonation rotation, since
    # Cloudflare gates probabilistically. We need this single Session to
    # persist for the POST too (cookies must match the CSRF token).
    client: cc_requests.Session | None = None
    csrf: str | None = None
    for attempt in range(SEED_MAX_ATTEMPTS):
        impersonate = IMPERSONATE_ROTATION[attempt % len(IMPERSONATE_ROTATION)]
        client = cc_requests.Session(impersonate=impersonate, timeout=30)
        for k, v in DEFAULT_COOKIES.items():
            client.cookies.set(k, v)
        try:
            r = client.get(SEED_URL, headers={"Referer": "https://www.kickstarter.com/"})
        except Exception as e:
            if verbose:
                print(f"  watchesCount seed attempt {attempt+1} ({impersonate}): exception {e}")
            time.sleep(1.5 + attempt + random.random())
            continue
        if r.status_code == 200:
            m = RE_CSRF.search(r.text)
            if m:
                csrf = m.group(1)
                break
            elif verbose:
                print(f"  watchesCount seed attempt {attempt+1} ({impersonate}): 200 but no CSRF token")
        elif verbose:
            print(f"  watchesCount seed attempt {attempt+1} ({impersonate}): status {r.status_code}")
        time.sleep(2 + attempt + random.random() * 1.5)

    if csrf is None or client is None:
        if verbose:
            print(f"  watchesCount: failed to seed session after {SEED_MAX_ATTEMPTS} attempts; skipping")
        return out

    headers = {
        "X-CSRF-Token": csrf,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Referer": "https://www.kickstarter.com/",
    }

    # Step 2: chunked batch GraphQL query, one round trip per ~50 slugs.
    for i in range(0, len(slugs), CHUNK_SIZE):
        chunk = slugs[i : i + CHUNK_SIZE]
        # Build aliased query: p0: project(slug: $s0) { watchesCount } …
        # Use variables (not interpolated strings) — safer + cacheable.
        var_decls = ", ".join(f"$s{j}: String!" for j in range(len(chunk)))
        fields = "\n  ".join(
            f"p{j}: project(slug: $s{j}) {{ watchesCount }}"
            for j in range(len(chunk))
        )
        query = f"query Watches({var_decls}) {{\n  {fields}\n}}"
        variables = {f"s{j}": s for j, s in enumerate(chunk)}
        body = {"operationName": "Watches", "variables": variables, "query": query}

        try:
            resp = client.post(GRAPH_URL, headers=headers, data=json.dumps(body))
            if resp.status_code != 200:
                if verbose:
                    print(f"  watchesCount chunk {i//CHUNK_SIZE+1}: status {resp.status_code}")
                continue
            data = resp.json().get("data") or {}
            for j, s in enumerate(chunk):
                obj = data.get(f"p{j}")
                if isinstance(obj, dict) and "watchesCount" in obj:
                    out[s] = obj["watchesCount"]
        except Exception as e:
            if verbose:
                print(f"  watchesCount chunk {i//CHUNK_SIZE+1} failed: {e}")
            continue

    return out


def slug_from_pathname(pathname: str) -> str:
    """`/projects/creator/foo-bar` → `foo-bar`."""
    return (pathname or "").rstrip("/").split("/")[-1]


if __name__ == "__main__":
    import sys
    slugs = sys.argv[1:] or [
        "ayaneo-pocket-play-mobile-phone-and-gaming-handheld-in-one",
        "xgimi-titan-noir-series-4k-projector",
        "la-seine-espresso-machine",
    ]
    counts = fetch_watches_counts(slugs)
    for s, c in counts.items():
        print(f"  {c if c is not None else '—':>8}  {s}")
