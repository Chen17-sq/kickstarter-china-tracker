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

### 7. Email broadcast + observability (`scraper/email_notify.py`)
The main user-facing output. Builds a newsprint-styled HTML edition + plaintext alternative (multipart), preheader text for inbox preview, NewsArticle JSON-LD for SEO, per-edition canonical URL. Sends via Resend. Owner gets a separate `[OPS]` digest each day with KPIs, sanity warnings, scrape-health, and anomaly counts.

### 8. Sleeper picks (`scraper/sleepers.py`)
Algorithmic editor's-picks beyond the Top 10. Scores every non-Top-10 project across 6 buckets (hidden_hot, acceleration, early_traction, watcher_surge, just_crossed, cold_pick), composes a single Chinese reason line, applies diversity caps (≤3 per status, ≤3 per novelty label), plus a streak bonus (+30/day, capped at 3 days) for projects that hit the criteria multiple days in a row. Streak state at `data/.sleeper_streaks.json` (gitignored).

### 9. Sanity gate (`scraper/sanity.py`)
LAST check before broadcast. Blocks if: 0 projects, project count dropped >70%, followers coverage <30%, pledged_usd outliers >$100M, negative pledged values, duplicate pathnames, history timestamps out of order. On block, owner gets `[ALERT]` instead of subscribers getting bad data. See `docs/FAILURE_MODES.md`.

### 10. Anomaly detection (`scraper/anomalies.py`)
FYI signals — vanished (project gone from discovery, not ended/failed), reverted (followers dropped >50%), stuck (live project with $0 movement in 7 days). Surfaced in OPS digest, never blocks broadcast. State at `data/.anomalies.json`.

### 11. Public outputs

| Surface | Module | URL |
|---|---|---|
| Static homepage + sortable table | `site/index.html` | `/` |
| Newsprint edition (per day) | `email_notify.write_archive` | `/editions/<date>.html` |
| Atom 1.0 feed | `scraper/feed.py` | `/feed.xml` |
| Sitemap | `scraper/sitemap.py` | `/sitemap.xml` |
| Public JSON API (slim) | `scraper/api.py` | `/api/today.json`, `/api/<date>.json`, `/api/index.json` |
| Carousel slides (Xiaohongshu) | `scraper/social.py` | `/social/<date>/slide-NN.png` |
| PDF edition | `scraper/pdf.py` | `/editions/<date>.pdf` |
| 404 page | `site/404.html` | served on misses |
| PWA manifest | `site/manifest.json` | installable to home screen |

### 12. Subscribe Worker (`subscribe-worker/worker.js`)
Cloudflare Worker that stores subscribers in KV (private, never on public repo). Endpoints: POST / (subscribe + rate limit + welcome email), GET /count, GET /list (owner-only), GET /health, POST /unsubscribe (owner-only), POST /webhook/resend (Svix-verified bounce auto-cleanup). See `docs/RUNBOOK.md` for ops.

### 13. Anti-bot defense (`scraper/http.py` + `scraper/project.py` + `scraper/discover.py`)
Four-layer stack: (1) curl_cffi TLS impersonation rotation across 8 profiles; (2) warm session pre-visits KS homepage for CF clearance; (3) Playwright headless Chromium end-to-end fallback — POSTs go via `page.evaluate("fetch(...)")` so requests inherit the real browser TLS fingerprint + sec-ch-ua headers; (4) optional `KS_PROXY` env (single URL or comma-pool). See `docs/PROXY.md` + `docs/FAILURE_MODES.md`.

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
