"""Render the daily HTML edition to a printable PDF via headless Chromium.

We already have site/editions/<date>.html (the email-styled Newsprint
edition). To produce a shareable file for 小红书 / 微信 / Twitter, run
that page through Playwright's print-to-PDF.

Outputs (every cron run):
  site/editions/<date>.pdf  — dated, immutable
  site/editions/latest.pdf  — bookmark-stable

Public URLs (Pages):
  https://chen17-sq.github.io/kickstarter-china-tracker/editions/2026-04-26.pdf
  https://chen17-sq.github.io/kickstarter-china-tracker/editions/latest.pdf

Local: requires `playwright` Python package and the Chromium binary:
    pip install playwright
    python -m playwright install chromium

In CI: scrape.yml installs both. If Playwright/Chromium is missing,
this module logs a warning and exits cleanly — never aborts the cron.
"""
from __future__ import annotations
import asyncio
import datetime as dt
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EDITIONS = REPO_ROOT / "site" / "editions"


async def _render_pdf(html_url: str, out_path: Path) -> None:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 720, "height": 1024})
        page = await context.new_page()
        await page.goto(html_url, wait_until="networkidle", timeout=30_000)
        # Brief settle so web fonts paint before snapshot
        await page.wait_for_timeout(800)
        await page.pdf(
            path=str(out_path),
            # Print as wide page suited to the 680-px-max content area
            width="780px",
            height="1100px",
            print_background=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            prefer_css_page_size=False,
        )
        await context.close()
        await browser.close()


def render_today() -> Path | None:
    """Render today's edition HTML to PDF. Returns path on success, None on skip."""
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    html = EDITIONS / f"{today}.html"
    if not html.exists():
        print(f"  pdf: {html.name} missing — run email_notify first", file=sys.stderr)
        return None
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("  pdf: playwright not installed — skipping", file=sys.stderr)
        return None

    pdf = EDITIONS / f"{today}.pdf"
    try:
        asyncio.run(_render_pdf(f"file://{html.absolute()}", pdf))
    except Exception as e:
        print(f"  pdf: render failed ({e}) — skipping", file=sys.stderr)
        return None

    # Also publish a stable 'latest.pdf' alias
    shutil.copy2(pdf, EDITIONS / "latest.pdf")
    return pdf


if __name__ == "__main__":
    p = render_today()
    if p:
        print(f"wrote {p.relative_to(REPO_ROOT)} (and latest.pdf)")
    else:
        sys.exit(1)
