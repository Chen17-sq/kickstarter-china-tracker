"""Browser GraphQL transport owning a single bounded asyncio lifecycle.

CI verifies startup, two queries and cleanup against a local HTTP fixture.
A successful local browser test does not establish Kickstarter access.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import shutil
import tempfile
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

    def __init__(self, browser: Any, page: Any, csrf: str, loop=None, graph_url=GRAPH_URL, process=None, profile=None):
        self._loop = loop or asyncio.new_event_loop()
        self._browser = browser
        self._page = page
        self.csrf = csrf
        self.mode = "nodriver"
        self.graph_url = graph_url
        self._process = process
        self._profile = profile

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
                      return JSON.stringify({{ status: r.status, text: text }});
                    }} catch (e) {{
                      return JSON.stringify({{ status: -1, text: String(e) }});
                    }}
                  }})()
                """
                expr = expr_template.format(
                    url=json.dumps(self.graph_url),
                    headers=json.dumps(headers),
                    body=json.dumps(payload),
                )
                result = await self._page.evaluate(expr, await_promise=True)
            except Exception:
                return -1, None
            # nodriver deep-serializes JS objects as CDP key/value arrays,
            # not ordinary Python dicts. A JSON string is stable across versions.
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except ValueError:
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

        try:
            return self._loop.run_until_complete(asyncio.wait_for(_do(), timeout=30))
        except TimeoutError:
            return -1, None

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
            await _stop_process(self._process)
            if self._profile:
                shutil.rmtree(self._profile, ignore_errors=True)
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
    label: str = "nodriver", *, verbose: bool = True, seed_url=SEED_URL, graph_url=GRAPH_URL
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

    executable = os.environ.get("KS_BROWSER_EXECUTABLE") or nd.Config().browser_executable_path
    if not executable or not Path(executable).is_file():
        if verbose:
            print("  nodriver: Chromium executable does not exist")
        return None
    loop = asyncio.new_event_loop()

    async def _boot():
        profile = tempfile.mkdtemp(prefix="ks-chromium-")
        browser = process = None
        stderr_path = Path(profile) / "browser.stderr"
        try:
            # Own the process and wait for its ready file, rather than relying
            # on nodriver's fixed ~3-second startup polling window.
            args = ["--headless=new", "--remote-debugging-address=127.0.0.1",
                    "--remote-debugging-port=0", "--no-first-run", "--lang=en-US",
                    f"--user-data-dir={profile}"]
            if proxy_url:
                from urllib.parse import urlparse
                proxy = urlparse(proxy_url)
                if proxy.hostname:
                    args.append(f"--proxy-server={proxy.scheme}://{proxy.hostname}:{proxy.port}")
            with stderr_path.open("wb") as stderr:
                process = await asyncio.create_subprocess_exec(executable, *args, "about:blank",
                                                               stdout=asyncio.subprocess.DEVNULL, stderr=stderr)
            ready = Path(profile) / "DevToolsActivePort"
            deadline = loop.time() + 30
            while not ready.exists():
                if process.returncode is not None or loop.time() >= deadline:
                    stderr = stderr_path.read_text(errors="replace")
                    reason = "browser_sandbox_unavailable" if any(w in stderr.lower() for w in (
                        "sandbox", "apparmor", "user namespace")) else "browser_not_ready"
                    raise RuntimeError(reason)
                await asyncio.sleep(0.2)
            port = int(ready.read_text().splitlines()[0])
            browser = await nd.start(host="127.0.0.1", port=port, browser_executable_path=executable)
            page = await browser.get(seed_url)
            csrf = await page.evaluate(
                "document.querySelector('meta[name=\"csrf-token\"]')?.content || null"
            )
            if not isinstance(csrf, str) or not csrf:
                raise RuntimeError("csrf_missing")
            if verbose:
                print(f"  {label}: browser started and CSRF found")
            return NodriverTransport(browser, page, csrf, loop=loop, graph_url=graph_url,
                                     process=process, profile=profile)
        except (Exception, asyncio.CancelledError) as exc:
            if browser:
                browser.stop()
            await _stop_process(process)
            shutil.rmtree(profile, ignore_errors=True)
            if isinstance(exc, asyncio.CancelledError):
                raise
            if verbose:
                reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
                print(f"  ! nodriver boot failed: {reason}")
            return None

    try:
        result = loop.run_until_complete(asyncio.wait_for(_boot(), timeout=60))
        if result is None:
            _close_loop(loop)
        return result
    except Exception as exc:
        if not loop.is_closed():
            _close_loop(loop)
        if verbose:
            print(f"  ! nodriver bridge failed: {type(exc).__name__}")
        return None


async def _stop_process(process):
    if process is None or process.returncode is not None:
        return
    try:
        process.terminate()
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        process.kill()
        await process.wait()
    except ProcessLookupError:
        pass
