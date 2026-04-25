"""Optional: post the latest CHANGELOG.md to Slack/Discord webhook.

Reads SLACK_WEBHOOK or DISCORD_WEBHOOK env vars (set as repo secrets).
Skip silently if neither is configured.
"""
from __future__ import annotations
import os
from pathlib import Path
import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def main() -> None:
    if not CHANGELOG.exists():
        print("No CHANGELOG.md — nothing to notify.")
        return
    body = CHANGELOG.read_text(encoding="utf-8").strip()
    if not body:
        return

    # Slack-friendly truncation (4k char block limit)
    body = body[:3500] + ("\n…(truncated)" if len(body) > 3500 else "")

    slack = os.getenv("SLACK_WEBHOOK")
    discord = os.getenv("DISCORD_WEBHOOK")

    if slack:
        httpx.post(slack, json={"text": body}, timeout=10).raise_for_status()
        print("Slack OK")
    if discord:
        httpx.post(discord, json={"content": body}, timeout=10).raise_for_status()
        print("Discord OK")
    if not (slack or discord):
        print("No webhook configured.")


if __name__ == "__main__":
    main()
