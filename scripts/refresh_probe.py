#!/usr/bin/env python3
"""Read-only diagnostics: local browser lifecycle OR a bounded public source probe.

No sessions, proxy pool, scraper run, subscribers, email or repository writes.
Output must be outside the checkout. Raw headers, cookies and tokens are omitted.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def browser_probe():
    from playwright.sync_api import sync_playwright

    from scraper import nodriver_transport
    from scraper import project as project_module

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b'<html><meta name="csrf-token" content="fixture-token"><body>Local fixture</body></html>')

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            data = {"p" + key[1:]: {"watchesCount": 7, "backersCount": 3,
                                   "pledged": {"amount": 123, "currency": "USD"}}
                    for key in body.get("variables", {})}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"data": data}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    body = {"operationName": "Probe", "variables": {"s0": "fixture"},
            "query": "query Probe($s0: String!) { p0: project(slug:$s0) { watchesCount } }"}
    results = {}
    try:
        with sync_playwright() as pw:
            executable = pw.chromium.executable_path
            os.environ["KS_BROWSER_EXECUTABLE"] = shutil.which("google-chrome") or executable
            browser = pw.chromium.launch()
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(origin)
            original = project_module.GRAPH_URL
            project_module.GRAPH_URL = origin + "/graph"
            try:
                transport = project_module._Transport.from_playwright(None, browser, ctx, page, "fixture-token")
                for _ in range(2):
                    status, data = transport.post_graphql(body)
                    assert status == 200 and data["data"]["p0"]["watchesCount"] == 7
                results["playwright"] = {"status": "passed", "queries": 2}
            finally:
                project_module.GRAPH_URL = original
                browser.close()
        # Never discover a public proxy in a local-only test.
        from scraper import http
        original_pick = http.pick_proxy
        http.pick_proxy = lambda: None
        try:
            transport = nodriver_transport.open_nodriver_transport(verbose=True, seed_url=origin, graph_url=origin + "/graph")
            assert transport is not None, "nodriver failed local startup/CSRF"
            try:
                for _ in range(2):
                    status, data = transport.post_graphql(body)
                    assert status == 200 and data["data"]["p0"]["watchesCount"] == 7, "nodriver query failed"
            finally:
                transport.close()
            assert transport._loop.is_closed()
            results["nodriver"] = {"status": "passed", "queries": 2, "loop_closed": True}
        finally:
            http.pick_proxy = original_pick
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return {"status": "passed", "backends": results, "public_requests": 0, "emails_sent": 0}


def source_probe():
    import httpx
    from selectolax.lexbor import LexborHTMLParser as HTMLParser

    from scraper.graphql import CATALOG_BATCH_SIZE, fetch_projects

    result = {"status": "unverified", "requests": 0, "stages": [], "emails_sent": 0}
    origin = "https://www.kickstarter.com"
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
        def get(path, stage):
            response = client.get(origin + path)
            result["requests"] += 1
            result["stages"].append({"stage": stage, "http_status": response.status_code,
                                      "content_type": response.headers.get("content-type", "").split(";")[0]})
            return response
        response = get("/discover/advanced?state=live&format=json", "discover")
        if response.status_code != 200:
            result["status"] = "source_access_unavailable"
            return result
        with contextlib.suppress(ValueError):
            payload = response.json()
            projects = payload.get("projects") or []
            result["discover_projects"] = len(projects)
        response = get("/discover/advanced?state=upcoming", "seed")
        if response.status_code != 200:
            result["status"] = "source_access_unavailable"
            return result
        node = HTMLParser(response.text).css_first('meta[name="csrf-token"]')
        token = node.attributes.get("content") if node else None
        if not token:
            result["status"] = "csrf_missing"
            return result
        # Known public catalog only. Two catalog chunks verify that earlier
        # successful chunks survive accumulation; no production merge occurs.
        snapshot = json.loads((ROOT / "data/projects.json").read_text())
        slugs = list(dict.fromkeys(p["pathname"].rstrip("/").split("/")[-1]
                                  for p in snapshot["projects"] if p.get("status") == "live"))[:25]

        class Transport:
            def post_graphql(self, body):
                if result["requests"] >= 6:
                    return -1, None
                response = client.post(origin + "/graph", json=body,
                                       headers={"X-CSRF-Token": token, "Referer": origin + "/discover/advanced"})
                result["requests"] += 1
                result["stages"].append({"stage": "graphql", "http_status": response.status_code,
                                          "batch_size": len(body["variables"])})
                try:
                    return response.status_code, response.json()
                except ValueError:
                    return response.status_code, None
        from scraper.refresh import FAT_QUERY_FIELDS
        data = fetch_projects(slugs, transport=Transport(), fields=FAT_QUERY_FIELDS,
                              operation="Refresh", batch_size=CATALOG_BATCH_SIZE, source="probe_catalog")
        result["catalog_requested"] = len(slugs)
        result["catalog_returned"] = sum(bool(p["data"]) for p in data.values())
        result["status"] = "sample_success" if result["catalog_returned"] == len(slugs) else "sample_degraded"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["browser", "source"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT) or output.exists():
        parser.error("--output must be a new file outside the repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    code = 0
    try:
        result = browser_probe() if args.mode == "browser" else source_probe()
    except Exception as exc:
        # Exception messages can contain URLs/tokens; retain only type.
        result = {"status": "probe_error", "exception_type": type(exc).__name__}
        if args.mode == "browser" or isinstance(exc, ImportError):
            result["local_fixture_error"] = str(exc)[:600]
        code = 1
    result.update(mode=args.mode, checked_at=dt.datetime.now(dt.UTC).isoformat())
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
