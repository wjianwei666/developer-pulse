from __future__ import annotations

from datetime import datetime, timezone

from ..db import db_session
from ..pipeline.digest import get_digest


def render_newsletter_html(digest_date: str) -> str | None:
    data = get_digest(digest_date)
    if not data:
        return None

    price_events = data.get("price_events_json") or []
    release_events = data.get("release_events_json") or []
    census = data.get("mcp_census_json")

    parts = [f"<h1>AgentPulse Daily Digest — {digest_date}</h1>"]

    if price_events:
        parts.append("<h2>Model Price Changes</h2>")
        parts.append("<ul>")
        for ev in price_events[:15]:
            label = ev.get("event_type", "").upper()
            line = f"<li><strong>[{label}]</strong> {ev.get('model_id')}"
            if ev.get("field_name"):
                line += f" — {ev['field_name']}"
            if ev.get("change_pct") is not None:
                sign = "+" if ev["change_pct"] >= 0 else ""
                line += f" ({sign}{ev['change_pct']:.2f}%)"
            if ev.get("blended_cost_new") is not None:
                line += f" — blended ${ev['blended_cost_new']:.6f}/1M"
            line += f" <em>(score: {ev.get('impact_score', 0)})</em></li>"
            parts.append(line)
        parts.append("</ul>")

    if release_events:
        parts.append("<h2>Ecosystem Breaking Changes</h2>")
        parts.append("<ul>")
        for ev in release_events[:15]:
            grade = ev.get("breaking_grade", "").upper()
            line = f"<li><strong>[{grade}]</strong> {ev.get('repo')} {ev.get('tag')}"
            if ev.get("deadline"):
                line += f" — deadline {ev['deadline']} ({ev.get('days_remaining')}d)"
            line += f" <em>(score: {ev.get('impact_score', 0)})</em></li>"
            if ev.get("migration_steps"):
                steps = ev["migration_steps"].split("\n")
                for s in steps[:3]:
                    parts.append(f"<dd>→ {s}</dd>")
            parts.append(line)
        parts.append("</ul>")

    if census:
        parts.append("<h2>MCP Registry Census</h2>")
        parts.append(
            f"<p>Total servers: {census.get('total')} | "
            f"New: {census.get('new_count')} | "
            f"Deprecated: {census.get('deprecated')} | "
            f"Drift detected: {census.get('drift_count')}</p>"
        )

    parts.append("<hr>")
    parts.append(
        '<p style="font-size:12px;color:#888">'
        "AgentPulse — AI Agent Ecosystem & Model Price Monitor. "
        'Generated content. <a href="https://agentpulse.local/api/unsubscribe">Unsubscribe</a></p>'
    )
    return "\n".join(parts)


def render_newsletter_text(digest_date: str) -> str | None:
    data = get_digest(digest_date)
    if not data:
        return None

    price_events = data.get("price_events_json") or []
    release_events = data.get("release_events_json") or []
    census = data.get("mcp_census_json")

    lines = [f"AgentPulse Daily Digest — {digest_date}", "=" * 50, ""]

    if price_events:
        lines.append("MODEL PRICE CHANGES")
        lines.append("-" * 30)
        for ev in price_events[:15]:
            label = ev.get("event_type", "").upper()
            line = f"[{label}] {ev.get('model_id')}"
            if ev.get("field_name"):
                line += f" — {ev['field_name']}"
            if ev.get("change_pct") is not None:
                sign = "+" if ev["change_pct"] >= 0 else ""
                line += f" ({sign}{ev['change_pct']:.2f}%)"
            if ev.get("blended_cost_new") is not None:
                line += f" — blended ${ev['blended_cost_new']:.6f}/1M"
            lines.append(line)
        lines.append("")

    if release_events:
        lines.append("ECOSYSTEM BREAKING CHANGES")
        lines.append("-" * 30)
        for ev in release_events[:15]:
            grade = ev.get("breaking_grade", "").upper()
            line = f"[{grade}] {ev.get('repo')} {ev.get('tag')}"
            if ev.get("deadline"):
                line += f" — deadline {ev['deadline']} ({ev.get('days_remaining')}d)"
            lines.append(line)
            if ev.get("migration_steps"):
                for s in ev["migration_steps"].split("\n")[:3]:
                    lines.append(f"  -> {s}")
        lines.append("")

    if census:
        lines.append("MCP REGISTRY CENSUS")
        lines.append("-" * 30)
        lines.append(
            f"Total: {census.get('total')} | New: {census.get('new_count')} | "
            f"Deprecated: {census.get('deprecated')} | Drift: {census.get('drift_count')}"
        )
        lines.append("")

    lines.append("=" * 50)
    lines.append("AgentPulse — Generated content. Unsubscribe: https://agentpulse.local/api/unsubscribe")
    return "\n".join(lines)


def get_confirmed_subscribers(tier: str = "free") -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            "SELECT email FROM subscribers WHERE status='confirmed' AND tier=?",
            (tier,),
        ).fetchall()
    return [dict(r) for r in rows]


def send_newsletter(digest_date: str) -> dict:
    html = render_newsletter_html(digest_date)
    text = render_newsletter_text(digest_date)
    if not html or not text:
        return {"status": "no_digest", "date": digest_date}

    subscribers = get_confirmed_subscribers()
    return {
        "status": "ready_to_send",
        "date": digest_date,
        "recipient_count": len(subscribers),
        "subject": f"AgentPulse Digest — {digest_date}",
        "html_preview": html[:500],
        "text_preview": text[:500],
    }