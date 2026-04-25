# Architecture

## Why this shape

Kickstarter has no public API. Anyone tracking the site has to either:
1. Scrape (this project)
2. Pay for closed services like Kicktraq

Scraping at hobby scale is fine if you're polite. We aim for "1 cron every 4 hours, ~250 page fetches per run, ~5 minutes total" — well below noise floor.

The whole stack runs on free GitHub Actions + GitHub Pages, so total cost is **$0/month**. The repo doubles as the database (commits = time series).

## Pipeline

### 1. Discover (`scraper/discover.py`)
Walks 8 Discover seed URLs:
- China geo (`woe_id=23424781`) × {newest, most_funded live, upcoming popularity, most_backed live}
- Global Tech (`category_id=16`) × {upcoming popularity, live most_funded}
- Global Design (`category_id=7`) × {upcoming popularity, live most_funded}

The two global category seeds matter because **many Chinese brands register their KS account from a US address** (XGIMI in CA, Snapmaker in DE, Anker in DE, Unihertz in CA…). They wouldn't show up in the China geo filter.

We grab the first 4 pages of each seed → ~200-300 unique pathnames.

### 2. Project page parse (`scraper/project.py`)
For each pathname, do a single GET (USD currency forced via cookie), parse with `selectolax`. Fields extracted:

| Field | Where |
|---|---|
| `title` | `<h1>` |
| `status` | `"Launching soon"` text → prelaunch; "days to go" → live; "Funding successful" → successful |
| `project_we_love` | "Project We Love" string presence |
| `followers` | regex `(\d+) followers` (prelaunch only) |
| `backers` | regex `(\d+) backers` |
| `pledged / goal` | regex `S?$ X pledged of S?$ Y goal` |
| `funded_pct` | regex `(\d+)% funded` |
| `days_to_go` | regex `(\d+) days to go` |
| `deadline` | regex `by Sun, June 21 2026 1:02 AM AWST` |
| `location, category` | text positional heuristic |

These regexes target the **visible text**, not React state, so they survive markup changes well.

### 3. China classification (`scraper/classify.py`)
Three-tier rules, in order:

1. **Brand whitelist hit** (`brands/china_brands.yaml::high_confidence`) → `confidence: 高`
   - Matches by KS creator slug or brand name in title
   - This is the most important rule — it covers the brands listed under US addresses
2. **KS location field** contains a Chinese city/region token → `confidence: 高`
3. **Medium-confidence whitelist** (eg. teams that look Chinese but unverified) → `confidence: 中`
4. **Blacklist** for explicit non-Chinese collisions (eg. Peak Design)
5. Default: `未知` — filtered out before saving

### 4. Snapshot output (`scraper/run.py`)
- `data/projects.json` — full latest snapshot (web frontend reads this)
- `data/prelaunch.json` / `data/live.json` — pre-sliced for quick consumption
- `data/history/<UTC-iso>.json` — full snapshot at this run; never overwritten
- `CHANGELOG.md` — diff vs previous snapshot, used by `notify.py`

### 5. Diff (`scraper/diff.py`)
Compare current and previous snapshot. Emit Change events for:
- **new** — pathname appeared
- **status_change** — eg. prelaunch → live, live → successful
- **followers_delta** — increase ≥ 50 in one run
- **backers_delta** — increase ≥ 100 in one run
- **ended** — pathname disappeared from discovery

These thresholds are tuned for "interesting enough to ping me about" — adjust in `diff.py`.

### 6. Notify (`scraper/notify.py`)
If `SLACK_WEBHOOK` or `DISCORD_WEBHOOK` env var is set, posts the latest `CHANGELOG.md` to those webhooks (truncated to 3.5KB).

## Storage choices

**Why JSON commits, not a real DB?**
- Free
- History is git-native (`git log data/history/2026-04-25*.json` is enough to time-travel)
- JSON files are CDN-able via GitHub Pages
- Anyone can `curl` your data without auth
- No service to maintain

**Tradeoffs:**
- Repo grows ~70KB / cron, ~25MB / year. Use shallow clones in CI (`fetch-depth: 1`).
- Don't try to embed binary blobs (videos, large images). Just keep the structured fields.

## Future extensions (good first PRs)

- **Follower-time charts**: `site/trends.html` reading `data/history/`
- **RSS feed**: `data/feed.xml` with new + status_change events
- **Alerts on momentum**: 7-day rolling delta > 20% / day
- **Brand auto-discovery**: when an unknown creator slug shows up in Discover with 5K+ followers, propose adding to the YAML via PR comment
- **Multi-region support**: parameterize `woe_id` to track other regions (eg. `2475687` Taiwan-only)
