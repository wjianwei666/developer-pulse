from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import httpx

from ..config import settings

WEBHOOK_TIMEOUT = 15


def _build_slack_blocks(price_events: list[dict], release_events: list[dict]) -> list[dict]:
    blocks: list[dict] = []
    blocks.append(
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f":zap: AgentPulse Alert — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            },
        }
    )

    if price_events:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Model Price Changes*"},
            }
        )
        for ev in price_events[:10]:
            grade_emoji = ":red_circle:" if ev.get("grade") == "alert" else ":large_yellow_circle:"
            fields = []
            fields.append(f"{grade_emoji} *{ev['model_id']}*  [{ev.get('event_type', '').upper()}]")
            if ev.get("field_name"):
                fields.append(f"Field: `{ev['field_name']}`")
            if ev.get("change_pct") is not None:
                sign = "+" if ev["change_pct"] >= 0 else ""
                fields.append(f"Change: {sign}{ev['change_pct']:.2f}%")
            if ev.get("blended_cost_new") is not None:
                fields.append(f"Blended: `${ev['blended_cost_new']:.2f}/1M`")
            fields.append(f"Score: {ev.get('impact_score', 0)}")
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "  ".join(fields)},
                }
            )

    if release_events:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Ecosystem Breaking Changes*"},
            }
        )
        for ev in release_events[:10]:
            grade = ev.get("breaking_grade", "unknown").upper()
            grade_emoji = {
                "BREAKING": ":red_circle:",
                "LIKELY": ":large_orange_circle:",
                "WATCH": ":large_yellow_circle:",
            }.get(grade, ":white_circle:")
            fields = []
            fields.append(f"{grade_emoji} *{ev['repo']}* `{ev.get('tag', '')}`  [{grade}]")
            if ev.get("deadline"):
                fields.append(f"Deadline: {ev['deadline']} ({ev.get('days_remaining')}d)")
            fields.append(f"Score: {ev.get('impact_score', 0)}")
            if ev.get("source_url"):
                fields.append(f"<{ev['source_url']}|View Release>")
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "  ".join(fields)},
                }
            )
            if ev.get("migration_steps"):
                steps = ev["migration_steps"].split("\n")[:3]
                steps_text = "\n".join(f"• {s}" for s in steps)
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": steps_text}],
                    }
                )

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":robot_face: AgentPulse — AI Agent Ecosystem & Model Price Monitor",
                }
            ],
        }
    )
    return blocks


def _build_discord_embeds(price_events: list[dict], release_events: list[dict]) -> list[dict]:
    embeds: list[dict] = []

    if price_events:
        fields = []
        for ev in price_events[:10]:
            grade_label = ":red_circle:" if ev.get("grade") == "alert" else ":yellow_circle:"
            name = f"{grade_label} [{ev.get('event_type', '').upper()}] {ev['model_id']}"
            value_parts = []
            if ev.get("field_name"):
                value_parts.append(f"Field: `{ev['field_name']}`")
            if ev.get("change_pct") is not None:
                sign = "+" if ev["change_pct"] >= 0 else ""
                value_parts.append(f"{sign}{ev['change_pct']:.2f}%")
            if ev.get("blended_cost_new") is not None:
                value_parts.append(f"Blended: ${ev['blended_cost_new']:.2f}/1M")
            value_parts.append(f"Score: {ev.get('impact_score', 0)}")
            fields.append({"name": name, "value": " | ".join(value_parts), "inline": False})
        embeds.append(
            {
                "title": "Model Price Changes",
                "color": 0xDA3633 if any(e.get("grade") == "alert" for e in price_events) else 0xD29922,
                "fields": fields,
            }
        )

    if release_events:
        fields = []
        for ev in release_events[:10]:
            grade = ev.get("breaking_grade", "unknown").upper()
            grade_emoji = {"BREAKING": ":red_circle:", "LIKELY": ":orange_circle:", "WATCH": ":yellow_circle:"}.get(
                grade, ":white_circle:"
            )
            name = f"{grade_emoji} [{grade}] {ev['repo']} `{ev.get('tag', '')}`"
            value_parts = []
            if ev.get("deadline"):
                value_parts.append(f"Deadline: {ev['deadline']} ({ev.get('days_remaining')}d)")
            value_parts.append(f"Score: {ev.get('impact_score', 0)}")
            if ev.get("source_url"):
                value_parts.append(f"[View Release]({ev['source_url']})")
            fields.append({"name": name, "value": " | ".join(value_parts), "inline": False})
            if ev.get("migration_steps"):
                fields.append(
                    {
                        "name": "Migration Steps",
                        "value": ev["migration_steps"][:300],
                        "inline": False,
                    }
                )
        embeds.append(
            {
                "title": "Ecosystem Breaking Changes",
                "color": 0xF85149 if any(e.get("breaking_grade") == "breaking" for e in release_events) else 0xDB6D28,
                "fields": fields,
            }
        )

    return embeds


def send_slack_alert(price_events: list[dict], release_events: list[dict]) -> bool:
    url = settings.slack_webhook_url
    if not url:
        return False
    blocks = _build_slack_blocks(price_events, release_events)
    payload = {"blocks": blocks}
    for attempt in range(3):
        try:
            with httpx.Client(timeout=WEBHOOK_TIMEOUT) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                return True
        except Exception:
            time.sleep(2**attempt)
    return False


def send_discord_alert(price_events: list[dict], release_events: list[dict]) -> bool:
    url = settings.discord_webhook_url
    if not url:
        return False
    embeds = _build_discord_embeds(price_events, release_events)
    payload = {
        "username": "AgentPulse",
        "avatar_url": "https://agentpulse.local/favicon.ico",
        "embeds": embeds,
    }
    for attempt in range(3):
        try:
            with httpx.Client(timeout=WEBHOOK_TIMEOUT) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                return True
        except Exception:
            time.sleep(2**attempt)
    return False


def dispatch_webhooks(price_events: list[dict], release_events: list[dict]) -> dict[str, bool]:
    results: dict[str, bool] = {}
    if price_events or release_events:
        results["slack"] = send_slack_alert(price_events, release_events)
        results["discord"] = send_discord_alert(price_events, release_events)
    return results