# Proxy support (`KS_PROXY`)

The scraper supports routing all outbound HTTPS requests through an
external proxy via the `KS_PROXY` environment variable. **Dormant by
default** — if `KS_PROXY` is unset (the usual case), behavior is
unchanged. When set, both the curl_cffi path and the Playwright
fallback honor it.

## When you'd want this

You usually don't. The current anti-bot stack (TLS rotation + warm
session + Playwright fallback) handles every degradation mode we've
seen so far. Reach for proxies when:

1. **KS specifically blocks the GH Actions IP range.** The GitHub
   Actions runner pool uses a small set of AWS ASN IPs that bot-detection
   vendors fingerprint. If sanity gate alerts you that ALL of
   `curl_cffi` + `Playwright fallback` are getting 403'd consistently,
   the IP is the variable left.
2. **You want extra IP diversity** to lower the per-IP request rate
   below any per-IP thresholds.
3. **Geographic targeting** — proxy through a US residential IP if KS
   starts geo-discriminating.

## Format

```bash
# Single proxy
export KS_PROXY="http://proxy.example.com:8080"

# Authenticated
export KS_PROXY="http://alice:secret@proxy.example.com:8080"

# Pool — one is picked at random per request
export KS_PROXY="http://p1.example:8080,http://p2.example:8080,http://p3.example:8080"
```

`http://` is correct even for HTTPS targets — the proxy speaks HTTPS to
the upstream and HTTP/CONNECT to us.

## Cheapest setup — Cloudflare Worker as proxy

Cloudflare Workers give you a free 100K-request/day proxy at a CF IP
(not your GH Actions IP). Workflow:

1. Create a new Worker (`wrangler init my-ks-proxy --type=worker`)
2. Drop in this minimal proxy code:

   ```js
   export default {
     async fetch(req) {
       const url = new URL(req.url);
       // Strip the worker hostname; rewrite to kickstarter.com
       url.host = "www.kickstarter.com";
       url.protocol = "https:";
       return fetch(new Request(url, req));
     },
   };
   ```

3. Deploy with `wrangler deploy`. You'll get
   `https://my-ks-proxy.<acct>.workers.dev`.
4. In our scraper, set `KS_PROXY=https://my-ks-proxy.<acct>.workers.dev`.

Note this is a **rewriting** proxy, not a forwarding proxy — it changes
the host header. For a true forwarding proxy you'd need a paid solution
(Bright Data, Smartproxy, etc.) or your own VPS running `tinyproxy`.

If you want forwarding (so the upstream still sees `kickstarter.com` as
host), use a residential-proxy service.

## Setting in GitHub Actions

```yaml
# .github/workflows/scrape.yml
env:
  KS_PROXY: ${{ secrets.KS_PROXY }}  # set in repo Settings → Secrets
```

The secret is read at job start. Empty secret = dormant. No code
changes needed to toggle.

## Where it plugs in

| Path | Honors `KS_PROXY`? |
|---|---|
| `warm_client()` (discover crawl seeded session) | yes |
| `fetch()` (per-request, when no client passed in) | yes |
| `make_client()` (any ad-hoc session) | yes |
| `_try_curl_cffi_seed()` (project.py GraphQL seed) | yes |
| Playwright browser launch (`_DiscoverPlaywright`, project.py fallback) | yes |

Each curl_cffi attempt picks ONE proxy at random from the pool, so
across the 4-impersonation rotation you may hit 4 different proxies.
Playwright browsers bind to one proxy for their lifetime (you can't
switch mid-page).

## Verifying it's working

```bash
KS_PROXY=http://my-proxy:8080 python -c "
from scraper.http import warm_client
warm_client(verbose=True)
"
```

Look for the log line: `warm_client: routing through KS_PROXY (my-proxy)`.

## Caveats

* If the proxy is DOWN, everything fails — there's no fallback to direct.
  Pick a proxy provider with good uptime, or use a pool of 3+ so one
  bad apple doesn't sink the run.
* CF clearance cookies are tied to the IP that received them. If you
  set a single proxy URL, all retries will share an IP → cookies stay
  valid. If you set a pool, each retry may hit a different IP and CF
  may challenge again. Single-proxy is the safer default.
* No support for SOCKS proxies right now — only HTTP/HTTPS. Add if
  needed (`socks5://` URLs require the `pysocks` extra).
