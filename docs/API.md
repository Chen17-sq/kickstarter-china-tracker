# Public JSON API

A free, no-auth, CORS-friendly read-only API of every China-background
consumer-hardware project we're tracking. Refreshed daily at 08:00 Beijing
(00:00 UTC) by the scrape cron.

Use it for Slack bots, dashboards, mirror sites, partner scrapers,
academic research. No registration, no key, no rate limit you'd hit.

---

## Endpoints

| URL | Returns |
|---|---|
| `https://ks.aldrich.fyi/api/today.json` | Today's full snapshot (all tracked projects) |
| `https://ks.aldrich.fyi/api/<YYYY-MM-DD>.json` | A specific past day |
| `https://ks.aldrich.fyi/api/sleepers.json` | **Just** today's 5 algorithmic editor's picks (sleeper bucket) |
| `https://ks.aldrich.fyi/api/index.json` | Available dates + endpoints list + schema version |

The GitHub Pages mirror also works:
- `https://chen17-sq.github.io/kickstarter-china-tracker/api/today.json`

Both serve the same content.

---

## Schema

Top-level:

```json
{
  "schema_version": 1,
  "generated_at": "2026-05-16T02:06:14Z",
  "edition": 22,
  "counts": {
    "prelaunch": 86,
    "live": 76,
    "successful": 72,
    "failed": 0,
    "total": 234,
    "pwl": 59
  },
  "total_live_usd": 33246672.98,
  "projects": [ ... ]
}
```

Each project (only `pathname`, `title`, `status` are guaranteed present;
other fields may be absent):

```json
{
  "pathname": "/projects/ayaneo-offical/ayaneo-pocket-play-mobile-phone-and-gaming-handheld-in-one",
  "title": "AYANEO Pocket Play: Mobile Phone and Gaming Handheld in One",
  "blurb_zh": "安卓掌机 + 手机二合一（侧滑实体按键）",
  "status": "prelaunch",
  "url": "https://www.kickstarter.com/projects/ayaneo-offical/...",
  "country": "CN",
  "creator": "AYANEO",
  "followers": 7638,
  "backers": 0,
  "pledged_usd": 0.0,
  "goal_usd": 0.0,
  "percent_funded": 0,
  "deadline": null,
  "launched_at": null,
  "project_we_love": true,
  "china_confidence": "高",
  "delta_followers": 12,
  "delta_backers": 0,
  "delta_pledged_usd": 0.0,
  "_sleeper_reason": "AI 硬件 · 早期 traction",
  "_sleeper_score": 170
}
```

Sleeper annotations (`_sleeper_reason`, `_sleeper_score`) are only
present on the 5 sleeper picks per day, not on every project. Filter
on `_sleeper_reason` being non-null to get just the day's picks.

---

## Stability promise

`schema_version` will only increase on breaking changes. Adding a field
is non-breaking. Removing a field or changing a type is breaking and
bumps schema_version.

You can rely on these fields existing in every record:
- `pathname` · `title` · `status`

These usually exist but may be absent for projects mid-fetch:
- `url` · `followers` · `country` · `creator` · `pledged_usd`
- `goal_usd` · `percent_funded` · `deadline` · `launched_at`
- `project_we_love` · `china_confidence`

These exist only when the previous-snapshot comparison succeeded:
- `delta_followers` · `delta_backers` · `delta_pledged_usd`

These exist only on sleeper-pick projects:
- `_sleeper_reason` · `_sleeper_score`

---

## Examples

### Top 10 live projects by USD raised today

```python
import requests
data = requests.get("https://ks.aldrich.fyi/api/today.json").json()
live = [p for p in data["projects"] if p.get("status") == "live"]
live.sort(key=lambda p: -(p.get("pledged_usd") or 0))
for p in live[:10]:
    print(f"  ${p['pledged_usd']:>12,.0f}  {p['title']}")
```

### Sleeper picks of the day (use dedicated endpoint)

```bash
# Slim — only the 5 sleeper picks, sorted by score desc:
curl -s https://ks.aldrich.fyi/api/sleepers.json | jq '.projects[] | {title, reason: ._sleeper_reason, score: ._sleeper_score}'

# Or filter from the full snapshot:
curl -s https://ks.aldrich.fyi/api/today.json \
  | jq '.projects[] | select(._sleeper_reason != null) | {title, reason: ._sleeper_reason, score: ._sleeper_score}'
```

### List available archive dates

```bash
curl -s https://ks.aldrich.fyi/api/index.json | jq '.dates'
```

### Slack bot — alert on new prelaunch with >1000 followers

```python
import requests, json
data = requests.get("https://ks.aldrich.fyi/api/today.json").json()
hot = [p for p in data["projects"]
       if p.get("status") == "prelaunch"
       and (p.get("followers") or 0) > 1000
       and (p.get("delta_followers") or 0) >= 100]
for p in hot:
    requests.post(SLACK_WEBHOOK, json={
        "text": f":fire: *{p['title']}* — {p['followers']:,} followers (+{p['delta_followers']} today). <{p['url']}|link>"
    })
```

---

## What's NOT in the public API

- `photo` URLs (large, frequently stale)
- English `blurb` (often redundant with `blurb_zh`)
- Internal classifier hints (`matched_brand`, `matched_brand_zh`)
- Any field starting with underscore *except* the documented sleeper ones

If you need any of these, read `data/projects.json` directly from the
GitHub repo (raw URL). That schema is NOT stable — it changes whenever
we refactor — so depend on it only for ad-hoc analysis, never for
production tooling.

---

## CORS / rate limit

All API files are static JSON served from GitHub Pages + Cloudflare
edge. CORS is wide open (no `Access-Control-Allow-Origin` headers
needed; the files are public). No rate limit beyond Pages' own. You
won't hit it from any reasonable consumer.

---

## Source

The schema is generated by [`scraper/api.py`](../scraper/api.py).
Field whitelist is `PUBLIC_PROJECT_FIELDS`. Tests pin behavior in
[`scraper/tests/test_api.py`](../scraper/tests/test_api.py).
