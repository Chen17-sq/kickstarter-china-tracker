# Contributing

The most valuable contribution: **expand `brands/china_brands.yaml`**.

The brand whitelist is what makes "this Chinese brand listed under a Delaware address" gets caught. Every Kickstarter project listed under a US address but actually from a Chinese team is a missed signal until someone adds it to the YAML.

## How to add a brand

1. Find the project's KS URL — the `creator-slug` is the second path segment:
   `https://www.kickstarter.com/projects/CREATOR_SLUG/PROJECT_SLUG`
2. Verify the brand background:
   - Search the brand's official website for "About"
   - Search news coverage (gizmochina, technode, 36kr, ifanr)
   - Check the company's WeChat / Weibo / .cn domain
3. Add an entry under `high_confidence`:
   ```yaml
   - {brand: "BrandName",  creator_slugs: ["the-slug"], hq: "深圳", source: "official-site"}
   ```
4. Open a PR with the project URL in the description and brief evidence.

`source` field values:
- `official-site` — verified on the brand's own site (best)
- `direct-verification` — confirmed from KS project page or a credible mention
- `news` — only mentioned in news coverage (lowest, ok for prelaunch)

## How to fix a misclassification

If a project is wrongly tagged as Chinese:
- Add it under `not_china:` with the slug and the actual HQ
- Open a PR

## Code changes

- `pip install -r requirements.txt`
- `pip install -e .[dev]`
- Run a single project to debug: `python -m scraper.project /projects/xlean/xlean-tr1-dual-form-transformable-floor-washing-robot`
- Run end-to-end: `python -m scraper.run`
- Lint: `ruff check`

## Bug reports

Open an issue with:
- The KS project URL
- What field is wrong
- The expected value
- (Optional) a screenshot from the actual KS page
