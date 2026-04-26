# Design Rules · 设计规范（永久参考）

This is the canonical visual + content spec for **every** publication
surface of Kickstarter China Tracker. Anything that ships to a reader
— Pages site, daily Markdown report, daily HTML email, archived edition
HTML, PDF download, 小红书 carousel PNGs, README banner, social preview
— **must** follow this document. Updates require human review.

> Maintained by the user; enforced by Claude. When in doubt, defer to
> user feedback recorded inline below.

---

## 1 · Visual identity — Newsprint / Beijing Edition

The whole product is a **daily newspaper**. Not a dashboard, not a SaaS
product, not a marketing site. Every surface should make a reader feel
they are picking up a printed paper at 09:00 北京时间.

### 1.1 Color tokens

| Token | Hex | Usage |
| --- | --- | --- |
| `paper` | `#F9F9F7` | Background everywhere except black-reverse strips |
| `ink` | `#111111` | Primary text + borders |
| `accent` (Editorial Red) | `#CC0000` | ★ KS Picks, prelaunch dot, breaking, ▸ bullets, link hover |
| `n400` | `#A3A3A3` | Muted captions, placeholders |
| `n500` | `#737373` | Secondary metadata |
| `n600` | `#525252` | Body text variations |
| `n700` | `#404040` | Body italics, blurbs |
| `muted` | `#E5E5E0` | Letterbox / image fallback bg |

**No other colors.** No blue, no green, no purple, no gradients. Period.

### 1.2 Typography stack

| Family | Use | Weight |
| --- | --- | --- |
| `Playfair Display` | Display headlines, nameplate, KPI numerals, rank badges | 700 / 900 |
| `Lora` | Body text, italic dek, blurbs | 400 / italic 400 |
| `Inter` | Labels, kickers, metadata, navigation | 500 / 600 / 700 |
| `JetBrains Mono` | All numbers, dates, edition codes, code, search input | 500 / 700 |

CJK fallback chain: `Songti SC, Source Han Serif SC` for serif;
`PingFang SC, Microsoft YaHei` for sans. Never substitute a different
typeface family.

### 1.3 Geometry

- **Sharp corners**: `border-radius: 0` everywhere.
- **Borders**: `1px solid #111111` for hairlines; `4px solid #111111`
  for major dividers / KPI band edges.
- **No shadows / glows / blurs / gradients.** Hard-shadow hover effects
  are OK for interactive buttons (offset 5×5 with red).
- **Edition strip**: black-reverse bar at the top of every published
  surface. Contains pulsing red dot + `DAILY · LIVE EDITION · <date>`
  + `VOL. 1 · NO. <edition>`.
- **Footer credo** (every surface ending): italic Playfair small text
  *"All the news that's fit to print, every morning at 09:00 Beijing."*

### 1.4 Edition number

Every surface that mentions an issue carries `Vol. 1 · No. N` where
**N = days since project epoch (2026-04-25) + 1**. Implementation:
`scraper/banner.py::edition_number()` and `scraper/email_notify.py`
both compute this independently — they MUST agree.

---

## 2 · Product images — non-negotiable rules

These rules came from explicit user feedback. Every contributor must
read them before touching image rendering on any surface.

### 2.1 No filters, ever

- **Forbidden**: `grayscale()`, `sepia()`, `contrast()`, `brightness()`,
  `saturate()`, `hue-rotate()`, anything CSS `filter:` related.
- KS hero photos carry product color as signal (blue PCB, red
  prototype, brushed aluminum, fabric texture). Filtering destroys
  the reason the user shares the image.
- Source: user message 2026-04-26 — "产品图的颜色你不能调啊，
  你要保持原有的图的颜色呀"

### 2.2 No heavy crop

- KS images vary: 16:9 (most common, video-derived), 4:3, sometimes
  square. Hard-cropping to a square container slices off product
  features.
- **Container**: 4:3 ratio (`280×210` for slides, `240×180` for emails,
  `360px wide` for Markdown).
- **`object-fit: contain`** preferred over `cover`. The product is
  always shown in full; letterbox bars hide on `paper`-colored bg.
- Source: user message 2026-04-26 — "现在的尺寸是不是有点大？感觉
  有截屏的痕迹"

### 2.3 Where images live

- KS Discover JSON's `photo.full` URL is captured at scrape time
  (`scraper/discover.py` → `image_url` field on every project).
- All publication surfaces consume `p["image_url"]`. Don't fetch /
  re-host the image — link directly. KS CDN is fast and stable.

---

## 3 · Top-3 product detail blocks

When a surface has space to feature top products (slides 04 / 06 of the
small-红书 carousel; daily HTML email; daily Markdown report), it MUST
present the top 3 of each track (prelaunch + live) with full detail:

1. **Rank badge** — Playfair `No. 01` / `02` / `03`
2. **Product image** — KS hero, original colors, 4:3, `object-fit:contain`
3. **Brand · Country line** — `JetBrains Mono` 11px, ★ KS PICK pill if applicable
4. **Title** — Playfair 18-30px, bold
5. **Italic Chinese 一句话** (`blurb_zh`) — Lora italic
6. **4 Chinese highlight bullets** (▸ in red) — from
   `data/highlights_zh.json`, falls back to English `|`-split blurb
7. **Big metric** — Watchers (red) for prelaunch, USD raised (ink) for live
8. **Link to KS** — every detail card links out

Source for highlights: `data/highlights_zh.json`. Schema:
`pathname → list[str]` (4 bullets, 16-32 Chinese chars each). User
hand-curated. Future LLM auto-translate is allowed but human review
required for top 3.

---

## 4 · Track ordering

| Track | Sort key | Tie-breaker |
| --- | --- | --- |
| Prelaunch | `project_we_love` first, then `followers` desc | `title` |
| Live | `pledged_usd` desc | `title` |
| Successful | `pledged_usd` desc | `deadline` desc (most recent first) |

★ Editor's Picks always rank first within prelaunch.

---

## 5 · Surface-by-surface compliance checklist

| Surface | Edition strip | Top 3 detail | Product images | 4 zh highlights | 起步价 |
| --- | :---: | :---: | :---: | :---: | :---: |
| Pages site `/` | ✓ | hero band | thumbnails in 'today's front page' | implicit via blurb_zh | meta line |
| Pages `/stats.html` | ✓ | top 5 list | thumbnails | — | meta line |
| Pages `/editions/<date>.html` | ✓ | ✓ | ✓ (4:3, no filter) | ✓ | ✓ |
| Daily email | ✓ | ✓ | ✓ (4:3, no filter, 240×180) | ✓ | ✓ |
| Daily Markdown report | text masthead | ✓ | ✓ (`<img width=360>`) | ✓ | ✓ |
| 小红书 carousel slides 04/06 | ✓ | ✓ (3-up) | ✓ (4:3, 280×210, no filter) | ✓ | ✓ |
| README banner SVG | embedded | — | — | — | — |
| OG card | embedded | — | — | — | — |
| PDF download | inherits from edition HTML | ✓ | ✓ | ✓ | ✓ |

If a new surface is added, fill in this row before merging.

### 5.1 起步价 (price) data flow

- Source: KS GraphQL `/graph` endpoint, query
  `project { rewards(first:30) { nodes { amount { amount currency } } } }`
- Captured in `scraper/project.py::fetch_pledge_minimums()` — runs once
  per cron, batched 25 slugs/request, USD-forced via cookie.
- Stored at `data/projects.json[].min_pledge_usd` as a USD float.
- Displayed as **起步价 \$N** with N formatted by `fmt_usd()`.
- Coverage: ~60% on first scrape (live + ended have rewards; many
  prelaunches don't yet have pledge tiers configured). Falls back to
  empty / hidden gracefully — no UI breakage when missing.

---

## 6 · Persistence — where things live

| Asset | Source of truth | Refreshed by |
| --- | --- | --- |
| `brands/china_brands.yaml` | manual + PR | human |
| `data/blurbs_zh.json` | manual + LLM auto-translate | `scraper/translate.py` |
| `data/highlights_zh.json` | manual (top brands) + future LLM | human |
| `data/projects.json` | scraped | `scraper/run.py` (cron) |
| `data/subscribers.json` | Cloudflare Worker writes | end-user form submits |
| `assets/banner.svg`, `snapshot.svg`, `og-card.svg` | generated | `scraper/banner.py` cron |
| `site/editions/*.html` | generated | `scraper/email_notify.py` cron |
| `site/editions/*.pdf` | generated | `scraper/pdf.py` cron |
| `site/social/latest/slide-*.png` | generated | `scraper/social.py` cron |
| `site/sitemap.xml` | generated | `scraper/sitemap.py` cron |
| `reports/*.md`, `reports/latest.md` | generated | `scraper/report.py` cron |
| `site/social/<date>/*.png`  | generated PNG | `scraper/social.py` cron |
| `site/social/latest/*.png` | generated PNG | `scraper/social.py` cron |
| `data/highlights_zh.json` | manual + future LLM | human (24 projects covered as of 2026-04-26) |

### 6.1 Retention / cleanup policy

Daily artifacts accumulate ~5MB/day. `scraper/cleanup.py` prunes:

- `site/social/<date>/` — older than **30 days** (keeps recent visual archive)
- `site/editions/<date>.html` / `.pdf` — older than **60 days**
- `data/history/<ts>.json` — older than **90 days** (powers Δ calculations)
- `reports/<date>.md` — older than **365 days** (small, low cost)

`latest.*` files are never pruned.

---

## 7 · When user asks for a new feature

1. Read this document first.
2. If the feature renders a product to readers: it must follow §2 + §3.
3. If the feature shows numbers: JetBrains Mono, tabular-nums.
4. If the feature has chrome (header/footer): copy the edition strip + credo.
5. Update the §5 compliance table.
6. If user feedback contradicts a rule here: update the rule (cite the
   message), don't quietly exception it.

---

*Last touched: 2026-04-26 — added §2 product image rules, §3 top-3
detail spec, §5 compliance table.*
