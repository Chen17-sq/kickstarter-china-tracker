# Migrate subscribers from public GitHub → private Cloudflare KV

The old setup wrote subscriber emails to `data/subscribers.json` on a
**public** GitHub repo. 6 emails were exposed publicly. This migration
moves storage to a Cloudflare KV namespace (private) — emails never
leave Cloudflare's storage.

Run this **once**, then push the code changes already committed.

## 1. Create the KV namespace (1 click in CF dashboard)

1. https://dash.cloudflare.com → **Workers & Pages** → **KV**
2. **Create a namespace** → name: `SUBSCRIBERS_KV`
3. Note the **Namespace ID** (long hex string).

## 2. Bind it to the subscribe Worker (2 clicks)

1. **Workers & Pages** → click `ks-tracker-subscribe` → **Settings**
2. **Bindings** → **+ Add** → **KV Namespace**:
   - Variable name: `SUBSCRIBERS_KV` (must match this exactly)
   - KV namespace: select the one you just created
3. Save.

## 3. Generate + set the OWNER_TOKEN secret (3 clicks + 1 paste)

The new `/list` endpoint (used by the daily email job to read
subscribers) is gated by a token. Generate a strong one:

```bash
openssl rand -hex 32
```

Copy that string. Then:

1. **Workers & Pages** → `ks-tracker-subscribe` → **Settings** → **Variables and Secrets**
2. **+ Add** → type **Secret** → name `OWNER_TOKEN` → value `<paste>` → save.

Also add it as a **GitHub Actions secret** so the daily cron can use it:

```bash
cd /Users/chensiqi/CC/kickstarter-china-tracker
gh secret set OWNER_TOKEN  # paste same value when prompted
gh secret set SUBSCRIBE_API_URL --body "https://ks-tracker-subscribe.schen-aldrich.workers.dev"
```

## 4. (Optional) clean up unused secrets on the Worker

These were needed for the old GitHub-write path. KV doesn't need them:
- `GITHUB_TOKEN` — can delete from Worker secrets
- `GITHUB_REPO` — already removed from wrangler.toml; was a non-secret var

Leaving them is harmless (the new code doesn't read them) but tidy up if you want.

## 5. Migrate the 6 existing subscribers into KV

You need a working local checkout (which you have):

```bash
cd /Users/chensiqi/CC/kickstarter-china-tracker
export OWNER_TOKEN="<the same hex string from step 3>"
export SUBSCRIBE_API_URL="https://ks-tracker-subscribe.schen-aldrich.workers.dev"
python -m scraper.subscribers migrate
```

Expected output:
```
  migrating 6 subscribers to KV via Worker ...
    added schen.aldrich@gmail.com (...)
    added gloria0527@foxmail.com (...)
    ... (etc.)
  ✓ migration complete: 6 new, 0 already in KV
```

Verify:
```bash
python -m scraper.subscribers list
# should print all 6, fetched via the new /list endpoint
```

## 6. Push code changes (already committed locally)

```bash
git push
```

This commits:
- `subscribe-worker/worker.js` — KV-backed Worker
- `subscribe-worker/wrangler.toml` — KV binding declaration
- `scraper/subscribers.py` — reads from Worker /list, falls back to local file
- `.github/workflows/scrape.yml` — passes OWNER_TOKEN + SUBSCRIBE_API_URL into the email step
- `.gitignore` — `data/subscribers.json` ignored
- Deletion of `data/subscribers.json` from HEAD

The Cloudflare Workers GitHub integration should auto-redeploy the
worker on push (the same Build/Deploy pipeline aldrich-fyi uses). If it
doesn't, manually redeploy from the dashboard.

## 7. (Optional) scrub the email leak from git history

The HEAD no longer has `data/subscribers.json`, but `git log --all` will
still surface old versions of the file containing real emails. Anyone
who ever cloned the repo already has those — that horse has bolted —
but new clones still get history.

To remove the file from all past commits (DESTRUCTIVE — rewrites history):

```bash
# Install git-filter-repo if needed:
brew install git-filter-repo

# Strip the file from every commit it ever appeared in:
git filter-repo --path data/subscribers.json --invert-paths --force

# Force-push the rewritten history:
git push --force-with-lease origin main
```

⚠️ This is destructive. Anyone with an existing clone will need to
re-clone or do a fresh fetch + reset. You're the only collaborator,
so this is fine.

⚠️ Tags / other branches / forks would also need their history
rewritten. The repo only has `main`, no tags, no other branches —
so it's clean.

## 8. Sanity-check the live form

Once deployed, hit https://ks.aldrich.fyi/subscribe.html and try a
test subscription with a throwaway email. Check the new entry shows
up via:

```bash
python -m scraper.subscribers list
```

If you see it, the round-trip works.

---

## What the new architecture looks like

```
Subscribe form (browser)
  └─> POST https://ks-tracker-subscribe.schen-aldrich.workers.dev/
        └─> Worker writes to KV namespace SUBSCRIBERS_KV
              (CORS-protected to ks.aldrich.fyi only;
               KV is private, only this Worker reads)

Daily cron (GitHub Actions)
  └─> python -m scraper.email_notify
        └─> scraper.subscribers.emails()
              └─> GET .../list  with X-Owner-Token: <OWNER_TOKEN>
                    └─> Worker reads KV, returns subscriber list
                          └─> Resend sends to each address
```

Subscriber emails now never leave Cloudflare KV. They're not in git, not
in the public repo, not in any commit message (commit messages still mask
to `f***@trooly.ai` style anyway).

Owner / unsubscribe paths are gated by `X-Owner-Token` so a leaked
worker URL alone doesn't expose the list.
