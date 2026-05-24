"""nodriver — Tier 3 heavy artillery for KS GraphQL when patchright fails.

nodriver (https://github.com/ultrafunkamsterdam/nodriver) is the actively-
maintained successor to undetected-chromedriver, by the same author. It
talks raw Chrome DevTools Protocol — NO Playwright shim — and is the
benchmark leader (90.3% pass) against modern CF detection as of May 2026.

We use it as Tier 3, after curl_cffi (Tier 1) and patchright/playwright
(Tier 2) have both failed. The cost is a slower startup (~5s vs
patchright's ~3s) and async-only API (we bridge to sync via asyncio.run).

Architecture:
  Tier 1: curl_cffi with rotated TLS impersonations (fastest)
  Tier 2: patchright headless Chromium via page.evaluate(fetch())
  Tier 3: nodriver raw CDP — last resort

This module exposes one function: `open_nodriver_transport(label)`,
which returns the same `_Transport`-shaped object (post_graphql + close)
that project.py expects. Drop-in.

Bridge strategy: nodriver is async-only. We wrap every call in
asyncio.run() so the rest of project.py stays sync. This is acceptable
because we open the transport once per cron run; the overhead is
amortized across many GraphQL chunks.

If `nodriver` isn't installed (it's listed as `>=0.50` in requirements
but optional in practice), open_nodriver_transport returns None and
the caller falls back gracefully (today's case: skip pledge_min, keep
yesterday's value).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

GRAPH_URL = "https://www.kickstarter.com/graph"
SEED_URL = "https://www.kickstarter.com/discover/advanced?state=upcoming"


class NodriverTransport:
    """_Transport-shaped object backed by nodriver. Async bridge inside.

    Provides:
      post_graphql(body) → (status, json|None)
      close()
      .mode = "nodriver"
      .csrf = <token>
    """

    def __init__(self, browser: Any, page: Any, csrf: str):
        self._browser = browser
        self._page = page
        self.csrf = csrf
        self.mode = "nodriver"

    def post_graphql(self, body: dict) -> tuple[int, dict | None]:
        """POST a GraphQL query via the in-browser fetch — like patchright
        path but driven by raw CDP, which CF can't fingerprint as easily."""
        headers = {
            "X-CSRF-Token": self.csrf,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = json.dumps(body)

        async def _do() -> tuple[int, dict | None]:
            try:
                # nodriver's page.evaluate is async; it accepts a JS expr
                # that we wrap to call fetch with args. The browser handles
                # cookies, sec-ch-ua, TLS — everything CF checks.
                # Build the JS via .format(); avoiding f-strings because
                # the JS template has its own {...} object-literal braces.
                expr_template = """
                  (async () => {{
                    try {{
                      const r = await fetch({url}, {{
                        method: 'POST',
                        headers: {headers},
                        body: {body},
                        credentials: 'include',
                      }});
                      const text = await r.text();
                      return {{ status: r.status, text: text }};
                    }} catch (e) {{
                      return {{ status: -1, text: String(e) }};
                    }}
                  }})()
                """
                expr = expr_template.format(
                    url=json.dumps(GRAPH_URL),
                    headers=json.dumps(headers),
                    body=json.dumps(payload),
                )
                result = await self._page.evaluate(expr, await_promise=True)
            except Exception:
                return -1, None
            if not isinstance(result, dict):
                return -1, None
            status = int(result.get("status", -1))
            text = result.get("text") or ""
            if status != 200:
                return status, None
            try:
                return status, json.loads(text)
            except Exception:
                return status, None

        return asyncio.run(_do())

    def close(self) -> None:
        """Shut down the browser. Safe to call multiple times."""
        if self._browser is None:
            return
        async def _do() -> None:
            try:
                await self._browser.stop()
            except Exception:
                pass
        try:
            asyncio.run(_do())
        except Exception:
            pass
        self._browser = None
        self._page = None


def open_nodriver_transport(
    label: str = "nodriver", *, verbose: bool = True
) -> NodriverTransport | None:
    """Boot a nodriver browser, fetch CSRF, return a NodriverTransport.

    Returns None if (a) nodriver isn't installed or (b) the browser
    refuses to start in this environment (e.g. missing display headers
    on certain CI images). Caller should fall through to the next tier
    or skip this fetch.
    """
    try:
        import nodriver as nd
    except ImportError:
        if verbose:
            print("  ! nodriver not installed; cannot use Tier 3 fallback")
        return None

    async def _boot() -> NodriverTransport | None:
        try:
            browser = await nd.start(
                headless=True,
                user_data_dir=None,  # ephemeral profile per run
                browser_args=[
                    "--lang=en-US",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
        except Exception as e:
            if verbose:
                print(f"  ! nodriver browser.start failed: {e}")
            return None

        try:
            page = await browser.get(SEED_URL)
            # Wait briefly for any CF challenge to clear
            await asyncio.sleep(2.5)
            # Extract CSRF the same way Playwright does
            csrf = await page.evaluate(
                "document.querySelector('meta[name=\"csrf-token\"]')?.content || null"
            )
            if not csrf or not isinstance(csrf, str):
                if verbose:
                    print("  ! nodriver: no CSRF found on seed page")
                await browser.stop()
                return None
            if verbose:
                print(f"  {label} ✅ seeded via nodriver (csrf len={len(csrf)})")
            return NodriverTransport(browser=browser, page=page, csrf=csrf)
        except Exception as e:
            if verbose:
                print(f"  ! nodriver seed exception: {e}")
            try:
                await browser.stop()
            except Exception:
                pass
            return None

    try:
        return asyncio.run(_boot())
    except Exception as e:
        if verbose:
            print(f"  ! nodriver asyncio bridge failed: {e}")
        return None
