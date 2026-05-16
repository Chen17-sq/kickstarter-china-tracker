# Changelog · Feature history

Auto-generated from `git log` (excluding daily cron snapshots).
Run `python scripts/gen_changelog.py` to refresh.

## 2026-05

- **2026-05-16** ([`a472ac7`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/a472ac7)) — per-edition og:image · sleeper tag in API · ARCHITECTURE.md refresh
- **2026-05-16** ([`418fadd`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/418fadd)) — api.py tests (17) + auto-deploy Worker workflow
- **2026-05-16** ([`829508b`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/829508b)) — dependabot · CITATION.cff · subscribers tests · README API surface
- **2026-05-16** ([`a748da0`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/a748da0)) — worker XSS fix + 17 JS tests + AI-bot robots.txt + CI badges
- **2026-05-16** ([`470ea4d`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/470ea4d)) — public JSON API · Worker /health · subscribe RSS · per-edition canonical
- **2026-05-16** ([`e09d2f6`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/e09d2f6)) — plaintext email · NewsArticle JSON-LD · 404 page · PWA manifest · README docs index
- **2026-05-16** ([`c45aa22`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/c45aa22)) — anomalies + streaks + 50 new tests + ruff pass + RUNBOOK
- **2026-05-16** ([`6121c57`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/6121c57)) — feed + welcome email + rate limit + preheader + stale-time fixes
- **2026-05-16** ([`bc98592`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/bc98592)) — scraper: optional proxy pool via KS_PROXY env var
- **2026-05-16** ([`9ff679c`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/9ff679c)) — tests: pytest coverage for sleepers, sanity, classify
- **2026-05-16** ([`f8f34b5`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/f8f34b5)) — worker: add Resend bounce/complaint webhook auto-cleanup
- **2026-05-16** ([`460f180`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/460f180)) — sanity: include scrape-health digest in BLOCKED alert email
- **2026-05-16** ([`a58ccd7`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/a58ccd7)) — observability: scrape health log in OPS digest
- **2026-05-16** ([`23eba94`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/23eba94)) — sleeper: novelty scoring; scraper: warm session + discover Playwright fallback
- **2026-05-13** ([`a0c61fe`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/a0c61fe)) — fix(project): route GraphQL POSTs through real browser on Playwright fallback
- **2026-05-13** ([`68caa98`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/68caa98)) — fix(email_notify): owner digest NameError on d / counts
- **2026-05-01** ([`91777f1`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/91777f1)) — audit: fix critical + high-severity findings from full code review

## 2026-04

- **2026-04-28** ([`834b7bf`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/834b7bf)) — feat: Sleeper picks + creator-type subscribers
- **2026-04-28** ([`07e4bd6`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/07e4bd6)) — gitignore: wrangler local build cache
- **2026-04-28** ([`b9bf9a7`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/b9bf9a7)) — subscribe-worker: pin KV namespace ID in wrangler.toml
- **2026-04-28** ([`1a8d86e`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/1a8d86e)) — privacy: move subscribers from public GitHub → private CF KV
- **2026-04-28** ([`100a38a`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/100a38a)) — scraper safety v2: 7 more layers + comprehensive failure analysis
- **2026-04-28** ([`090022d`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/090022d)) — scraper safety: 4-layer defense against bad-data emails
- **2026-04-28** ([`aee41c7`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/aee41c7)) — feat(scraper): Playwright fallback for GraphQL session seeding
- **2026-04-28** ([`3d52fd6`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/3d52fd6)) — fix(scraper): graceful degradation when watchers fetch is blocked
- **2026-04-27** ([`4f44740`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/4f44740)) — subscribe-worker: support multi-origin CORS whitelist
- **2026-04-27** ([`de839f6`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/de839f6)) — feat: custom domain ks.aldrich.fyi
- **2026-04-27** ([`745f8ed`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/745f8ed)) — site/copy: 09:00 → 08:00 across all surfaces
- **2026-04-27** ([`44226b0`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/44226b0)) — site(time): show Updated in Beijing time, not UTC
- **2026-04-27** ([`44131ff`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/44131ff)) — ci(cron): move scrape from 09:00 → 08:00 Beijing
- **2026-04-27** ([`89f2ff9`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/89f2ff9)) — ci(deploy): cascade after scrape via workflow_run
- **2026-04-27** ([`a6acb4a`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/a6acb4a)) — feat(report): drop gainers / Top 5 → Top 10 / Top 3 stays image+text
- **2026-04-26** ([`e7aa8dd`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/e7aa8dd)) — feat(discover): expand to 14 seeds × 8 pages — coverage 143 → 255 China-bg projects
- **2026-04-26** ([`cba15be`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/cba15be)) — feat: 起步价 / archive cleanup / shared constants / +12 highlights / dead code purge
- **2026-04-26** ([`a1ff722`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/a1ff722)) — feat(design): top-3 detail blocks in email + Markdown report; permanent DESIGN_RULES.md
- **2026-04-26** ([`846576a`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/846576a)) — fix(social): preserve original product image colors (drop grayscale filter)
- **2026-04-26** ([`8da8462`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/8da8462)) — feat(social): top-3 detail slides — product image + 4 long-form Chinese highlights
- **2026-04-26** ([`5890974`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/5890974)) — feat(social): top prelaunch + top live detail slides — product image + highlights
- **2026-04-26** ([`5555cdd`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/5555cdd)) — feat(social): 9-slide 1080x1350 portrait carousel for 小红书
- **2026-04-26** ([`2a63873`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/2a63873)) — feat(pdf): on-demand 'Download PDF' button on every Pages page
- **2026-04-26** ([`5e28496`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/5e28496)) — feat(pdf): daily edition PDF export for 小红书 / 微信 sharing
- **2026-04-26** ([`c73cf09`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/c73cf09)) — feat(seo): full meta tags + sitemap + robots + JSON-LD; ship assets+reports to Pages
- **2026-04-26** ([`5ecb750`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/5ecb750)) — fix: regenerate SVG / data / reports — strip stray git merge conflict markers
- **2026-04-26** ([`5866177`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/5866177)) — feat(subscribe): wire CF Worker URL + clean up probe entry
- **2026-04-26** ([`b574c44`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/b574c44)) — feat(subscribe): Cloudflare Worker → direct-to-GitHub subscription + masked subscribers stats
- **2026-04-26** ([`89a616d`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/89a616d)) — feat(archive): permanent web-readable archive of every daily edition
- **2026-04-26** ([`103b478`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/103b478)) — fix(svg): snapshot section labels above rows + subscribe form mailto fallback
- **2026-04-26** ([`4d76ee0`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/4d76ee0)) — feat: subscription system v1 + 今日头版 hero + stats page + cleaner README
- **2026-04-26** ([`e3ad7e6`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/e3ad7e6)) — feat(cde): conversion ratio, momentum deltas, projected total
- **2026-04-26** ([`90f19c8`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/90f19c8)) — feat(design): full Newsprint redesign across all surfaces
- **2026-04-26** ([`018c36d`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/018c36d)) — feat(branding): editorial polish across every configurable GitHub surface
- **2026-04-26** ([`12c2550`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/12c2550)) — feat(branding): editorial SVG banner at top of README, live-refreshed each cron
- **2026-04-26** ([`26b54a2`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/26b54a2)) — fix(email): default sender when NOTIFY_EMAIL_FROM secret is empty string
- **2026-04-26** ([`bc71cf1`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/bc71cf1)) — feat(email): daily HTML email summary via Resend API
- **2026-04-26** ([`f58b4f8`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/f58b4f8)) — feat(notify): rich daily Slack/Discord summary (replaces raw CHANGELOG dump)
- **2026-04-26** ([`eb1d9e8`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/eb1d9e8)) — feat: launch / pre-launch / live time metrics
- **2026-04-26** ([`2fdd812`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/2fdd812)) — feat(followers): fetch prelaunch follower counts via KS GraphQL /graph
- **2026-04-25** ([`f3ed3a8`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/f3ed3a8)) — feat: daily Markdown reports + LLM auto-translate + editorial README
- **2026-04-25** ([`63999d7`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/63999d7)) — feat(blurbs): curated Chinese product one-liners for top 100 projects
- **2026-04-25** ([`6ffa842`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/6ffa842)) — feat(site): add ZH/EN language toggle + Chinese brand names
- **2026-04-25** ([`b969dd2`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/b969dd2)) — feat(site): redesign frontend in Editorial / Swiss style
- **2026-04-25** ([`c5218cd`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/c5218cd)) — fix(scraper): replace httpx with curl_cffi to bypass Cloudflare; switch to Discover JSON API
- **2026-04-25** ([`3655ae4`](https://github.com/Chen17-sq/kickstarter-china-tracker/commit/3655ae4)) — fix(scrape): only stage CHANGELOG.md when it exists
