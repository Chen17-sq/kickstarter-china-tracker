# Runbook · Kickstarter China Tracker

Common ops you'll do, with the actual command and where it lives. Living
doc — if you find yourself googling the same git incantation twice,
add it here.

Repo root: `/Users/chensiqi/CC/kickstarter-china-tracker`

---

## Daily operations

### Force a re-run of today's cron

The cron has an idempotency guard (skips if `data/history/<today>T*.json`
exists). To re-trigger after the gate blocked the broadcast, or after a
hand fix:

```bash
# 1. Delete today's history snapshot so the guard re-fires
rm data/history/$(date -u +%Y-%m-%d)T*.json
git add -u data/history && git commit -m "force re-run for $(date -u +%F)" && git push

# 2. Manually trigger
gh workflow run scrape.yml --repo Chen17-sq/kickstarter-china-tracker

# 3. Watch it
gh run watch
```

### Run the scrape locally (no email send)

```bash
python -m scraper.run
```

Writes to `data/projects.json` + `data/history/<ts>.json` + everything else.
Doesn't touch email — that's a separate `python -m scraper.email_notify`.

### Preview tomorrow's email locally

```bash
python -m scraper.email_notify --dry-run
# Then open the preview URL it prints
```

No emails go out. The HTML is written to `data/.tmp/email_preview.html`.

---

## Subscriber management

All subscriber state lives in Cloudflare KV via the `ks-tracker-subscribe`
Worker. Local CLI helpers live in `scraper/subscribers.py`.

### List current subscribers

```bash
OWNER_TOKEN=<token> python -m scraper.subscribers list
```

### Add a subscriber manually

```bash
OWNER_TOKEN=<token> python -m scraper.subscribers add user@example.com "Display Name"
```

### Remove a subscriber

```bash
OWNER_TOKEN=<token> python -m scraper.subscribers remove user@example.com
```

### Count subscribers (no token needed)

```bash
curl https://ks-tracker-subscribe.schen-aldrich.workers.dev/count
```

### Migrate legacy file → KV (one-shot)

If you ever resurrect `data/subscribers.json` for any reason:

```bash
OWNER_TOKEN=<token> python -m scraper.subscribers migrate
```

---

## Worker (Cloudflare) ops

### Deploy a new Worker version

```bash
cd subscribe-worker
CLOUDFLARE_API_TOKEN=<token> npx wrangler deploy
```

Token comes from Cloudflare dashboard → My Profile → API Tokens → Create
Token → "Edit Cloudflare Workers" template.

### Set a Worker secret

```bash
cd subscribe-worker
echo "<value>" | CLOUDFLARE_API_TOKEN=<token> npx wrangler secret put OWNER_TOKEN
```

Secrets we use:
- `OWNER_TOKEN` — auth for `/list` and `/unsubscribe`
- `RESEND_API_KEY` — for welcome emails (optional; without it, welcomes skip)
- `NOTIFY_EMAIL_FROM` — paired with above, e.g. `"KS Tracker <hi@aldrich.fyi>"`
- `RESEND_WEBHOOK_SECRET` — Svix signing secret for `/webhook/resend`

### View Worker logs (live tail)

```bash
cd subscribe-worker
CLOUDFLARE_API_TOKEN=<token> npx wrangler tail
```

Useful for debugging welcome email failures, rate limit firing, etc.

### List KV keys (debug)

```bash
cd subscribe-worker
CLOUDFLARE_API_TOKEN=<token> npx wrangler kv key list --binding=SUBSCRIBERS_KV
```

---

## Brand list maintenance

`brands/china_brands.yaml` is the classifier's source of truth. After
editing, no rebuild step is needed — `classify.py` reads it fresh on
each run.

### Add a high-confidence brand

Append to the `high_confidence:` block:
```yaml
high_confidence:
  - brand: NewBrand
    brand_zh: 新品牌
    creator_slugs: [newbrand-official, newbrand-hk]
```

`brand_zh` is optional (falls back to `brand`). Test before pushing:
```bash
python -m scraper.classify newbrand-official "New York"
```

### Blacklist a project that's miscategorized

```yaml
not_china:
  - brand: SomeBrand
    creator_slugs: [their-slug]
```

Test that it now classifies `否`:
```bash
python -m scraper.classify their-slug "Shenzhen, China"
# Should print confidence='否' because not_china hits before location.
```

Wait, that order isn't right — check the `classify()` priority order
in `scraper/classify.py` before adding to `not_china`. Currently:
brand whitelist > location > medium > blacklist > unknown.

---

## Emergency: restore last-known-good data

If today's `data/projects.json` got corrupted (sanity-gate-blocked is
the usual case; data is also corrupted on disk):

```bash
# Find the most recent healthy history snapshot
ls data/history/ | tail -5

# Restore it as the live snapshot
cp data/history/<last-good-ts>.json data/projects.json
python -m scraper.email_notify --dry-run  # verify it renders
git add data/projects.json && git commit -m "restore: $(date)" && git push
```

---

## Translation / blurbs

Auto-translation uses Anthropic API when `ANTHROPIC_API_KEY` is set in
CI (it's NOT today — see scraper logs).

Curated translations live in `data/blurbs_zh.json` (manually edited) and
`data/highlights_zh.json` (the 4-line product highlights for Top 3 detail
cards). Adding to these is the most reliable path right now.

Format:
```json
{
  "ayaneo-pocket-play-mobile-phone-and-gaming-handheld-in-one": "ARM 设备专用 AI 应用基础设施开发板"
}
```

Key is the slug (last segment of `pathname`), not the full pathname.

---

## Anti-bot / scraper hardening

Current defense stack documented in `docs/FAILURE_MODES.md` (A11, A12).

### Diagnose a scraper failure

```bash
# Look at today's GH Actions log
gh run list --workflow=scrape.yml --limit 3
gh run view <run-id> --log | grep -E "(seed|watchesCount|sanity|Email|fallback)"
```

Look for:
- `! seed page failed` — curl_cffi 403'd that page. Did Playwright fallback recover?
- `watchesCount chunk N: status 403` — GraphQL chunk got blocked
- `⚠ sanity issues:` — gate flagged something
- `Email broadcast: sent=N` — actual delivery count

### Add proxy support (when IP-blocked)

See `docs/PROXY.md`. Short version:
```bash
gh secret set KS_PROXY --body "http://your.proxy:8080"
# Then trigger the workflow
```

---

## Adding tests

```bash
pip install pytest  # once
# Add new tests/file in scraper/tests/
python -m pytest scraper/tests/ -v
```

CI runs them on every push via `.github/workflows/test.yml`. Failing
tests block the merge.

---

## Things NOT to do

- **Never `git push --force` to main** — daily commits accumulate from
  cron; force-push destroys them.
- **Never commit `.env`** — it has API keys. `.gitignore` covers it.
- **Never commit `data/subscribers.json`** — gitignored; subscriber
  data is private and lives in KV.
- **Don't disable the sanity gate** — even temporarily. Better to
  delay one day's email than spam subscribers with zeros.
- **Don't lower the `DISCOVER_FLOOR`** in `scraper/run.py` (currently 50)
  — that's the catastrophic-failure guard.
