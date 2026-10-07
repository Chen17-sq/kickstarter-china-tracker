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
a single owned event loop so browser connections survive between calls. This is acceptable
because we open the transport once per cron run; the overhead is
amortized across many GraphQL chunks.

If `nodriver` isn't installed (it's listed as `>=0.50` in requirements
but optional in practice), open_nodriver_transport returns None and
the caller falls back gracefully (today's case: skip pledge_min, keep
yesterday's value).
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
from pathlib import Path
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

    def __init__(self, browser: Any, page: Any, csrf: str, loop=None):
        self._loop = loop or asyncio.new_event_loop()
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

        return self._loop.run_until_complete(_do())

    def close(self) -> None:
        """Shut down the browser. Safe to call multiple times."""
        if self._browser is None:
            return
        async def _do() -> None:
            try:
                result = self._browser.stop()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                pass
        try:
            self._loop.run_until_complete(_do())
        except Exception:
            pass
        self._browser = None
        self._page = None
        _close_loop(self._loop)


def _close_loop(loop):
    async def cleanup():
        pending = asyncio.all_tasks(loop) - {asyncio.current_task()}
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    loop.run_until_complete(cleanup())
    loop.close()


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

    # Route through KS_PROXY if configured — same plumbing as the other
    # tiers, so a Webshare residential URL flips IPs everywhere at once.
    from .http import pick_proxy
    proxy_url = pick_proxy()

    executable = os.environ.get("KS_BROWSER_EXECUTABLE")
    if executable and not Path(executable).is_file():
        if verbose:
            print("  nodriver: configured Chromium executable does not exist")
        return None
    loop = asyncio.new_event_loop()

    async def _boot() -> NodriverTransport | None:
        try:
            args = [
                "--lang=en-US",
                "--disable-blink-features=AutomationControlled",
            ]
            if proxy_url:
                # Strip any embedded credentials — Chromium reads
                # --proxy-server as URL only; auth is handled separately.
                from urllib.parse import urlparse
                p = urlparse(proxy_url)
                clean = f"{p.scheme}://{p.hostname}:{p.port}" if p.hostname else proxy_url
                args.append(f"--proxy-server={clean}")
                if verbose:
                    print(f"  nodriver routing through KS_PROXY ({p.hostname})")
            browser = await nd.start(
                headless=True,
                browser_executable_path=executable,
                user_data_dir=None,  # ephemeral profile per run
                browser_args=args,
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
                browser.stop()
                return None
            if verbose:
                print(f"  {label} ✅ seeded via nodriver (csrf len={len(csrf)})")
            return NodriverTransport(browser=browser, page=page, csrf=csrf, loop=loop)
        except Exception as e:
            if verbose:
                print(f"  ! nodriver seed exception: {e}")
            try:
                browser.stop()
            except Exception:
                pass
            return None

    try:
        result = loop.run_until_complete(_boot())
        if result is None:
            _close_loop(loop)
        return result
    except Exception as e:
        if not loop.is_closed():
            _close_loop(loop)
        if verbose:
            print(f"  ! nodriver asyncio bridge failed: {e}")
        return None
