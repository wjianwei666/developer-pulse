from __future__ import annotations

from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, tostring

from ..db import db_session


def _cdata(text: str | None) -> str:
    if not text:
        return ""
    return text.replace("]]>", "]]&gt;")


def build_rss() -> str:
    with db_session() as conn:
        price_events = conn.execute(
            "SELECT * FROM price_events ORDER BY detected_at DESC LIMIT 20"
        ).fetchall()
        release_events = conn.execute(
            "SELECT * FROM release_events ORDER BY detected_at DESC LIMIT 20"
        ).fetchall()

    rss = Element("rss", {"version": "2.0"})
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = "AgentPulse — AI Agent Ecosystem & Model Price Monitor"
    SubElement(channel, "link").text = "https://developer.zhiyuanyundun.com"
    SubElement(channel, "description").text = (
        "Model pricing & ecosystem change intelligence for agent builders — real-time LLM price changes and breaking changes in the AI agent ecosystem."
    )
    SubElement(channel, "lastBuildDate").text = datetime.now(timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )

    for ev in price_events:
        item = SubElement(channel, "item")
        title_parts = [f"[{ev['event_type'].upper()}] {ev['model_id']}"]
        if ev.get("field_name"):
            title_parts.append(ev["field_name"])
        if ev.get("change_pct") is not None:
            sign = "+" if ev["change_pct"] >= 0 else ""
            title_parts.append(f"{sign}{ev['change_pct']:.2f}%")
        SubElement(item, "title").text = " ".join(title_parts)
        SubElement(item, "link").text = ev.get("source_url") or "https://developer.zhiyuanyundun.com"
        SubElement(item, "guid").text = f"price-{ev['id']}"
        SubElement(item, "pubDate").text = ev["detected_at"]
        desc = []
        if ev.get("old_value") is not None:
            desc.append(f"Old: {ev['old_value']}")
        if ev.get("new_value") is not None:
            desc.append(f"New: {ev['new_value']}")
        if ev.get("blended_cost_new") is not None:
            desc.append(f"Blended cost: ${ev['blended_cost_new']:.6f}/1M tokens")
        desc.append(f"Impact score: {ev.get('impact_score', 0)}")
        SubElement(item, "description").text = " | ".join(desc)

    for ev in release_events:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = f"[{ev['breaking_grade'].upper()}] {ev['repo']} {ev['tag']}"
        SubElement(item, "link").text = ev.get("source_url") or "https://developer.zhiyuanyundun.com"
        SubElement(item, "guid").text = f"release-{ev['id']}"
        SubElement(item, "pubDate").text = ev["detected_at"]
        desc = [f"Breaking grade: {ev['breaking_grade']}", f"Impact score: {ev.get('impact_score', 0)}"]
        if ev.get("deadline"):
            desc.append(f"Deadline: {ev['deadline']} ({ev.get('days_remaining')} days)")
        if ev.get("migration_steps"):
            desc.append(f"Migration: {ev['migration_steps'][:200]}")
        SubElement(item, "description").text = " | ".join(desc)

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(rss, encoding="unicode")