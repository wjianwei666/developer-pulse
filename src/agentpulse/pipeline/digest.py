from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ..db import db_session


def collect_events_for_digest(digest_date: str) -> dict:
    start = (datetime.fromisoformat(digest_date).replace(tzinfo=timezone.utc) - timedelta(days=1)).isoformat()
    end = datetime.fromisoformat(digest_date).replace(tzinfo=timezone.utc).isoformat()

    with db_session() as conn:
        price_events = conn.execute(
            """SELECT * FROM price_events
               WHERE detected_at >= ? AND detected_at < ?
               ORDER BY impact_score DESC""",
            (start, end),
        ).fetchall()

        release_events = conn.execute(
            """SELECT * FROM release_events
               WHERE detected_at >= ? AND detected_at < ?
               ORDER BY impact_score DESC""",
            (start, end),
        ).fetchall()

        census = conn.execute(
            """SELECT * FROM mcp_census
               WHERE recorded_at >= ? AND recorded_at < ?
               ORDER BY recorded_at DESC LIMIT 1""",
            (start, end),
        ).fetchone()

    def row_to_dict(row):
        d = dict(row)
        for k, v in list(d.items()):
            if isinstance(v, bytes):
                d[k] = v.decode("utf-8", errors="replace")
        return d

    price_dicts = [row_to_dict(r) for r in price_events]
    release_dicts = [row_to_dict(r) for r in release_events]
    census_dict = row_to_dict(census) if census else None

    alerts = [e for e in price_dicts if e.get("grade") == "alert"]
    alerts += [e for e in release_dicts if e.get("grade") == "alert"]
    alerts.sort(key=lambda e: e.get("impact_score", 0), reverse=True)

    digest_items = [e for e in price_dicts if e.get("grade") == "digest"]
    digest_items += [e for e in release_dicts if e.get("grade") == "digest"]
    digest_items.sort(key=lambda e: e.get("impact_score", 0), reverse=True)

    visible_price = [e for e in price_dicts if e.get("grade") in ("alert", "digest")]
    visible_release = [e for e in release_dicts if e.get("grade") in ("alert", "digest")]

    return {
        "date": digest_date,
        "alerts": alerts,
        "digest": digest_items,
        "price_events": visible_price,
        "release_events": visible_release,
        "mcp_census": census_dict,
        "stats": {
            "price_total": len(price_dicts),
            "price_visible": len(visible_price),
            "release_total": len(release_dicts),
            "release_visible": len(visible_release),
            "alert_count": len(alerts),
        },
    }


def generate_digest_title(data: dict) -> str:
    alert_count = len(data["alerts"])
    price_count = len(data["price_events"])
    release_count = len(data["release_events"])
    parts = [f"AgentPulse Digest — {data['date']}"]
    if alert_count:
        parts.append(f"{alert_count} alert(s)")
    parts.append(f"{price_count} price, {release_count} ecosystem")
    return " | ".join(parts)


def save_digest(data: dict) -> int:
    title = generate_digest_title(data)
    now = datetime.now(timezone.utc).isoformat()
    with db_session() as conn:
        existing = conn.execute(
            "SELECT id FROM digests WHERE digest_date = ?", (data["date"],)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE digests SET title=?, price_events_json=?, release_events_json=?,
                   mcp_census_json=?, generated_at=? WHERE id=?""",
                (
                    title,
                    json.dumps(data["price_events"], ensure_ascii=False),
                    json.dumps(data["release_events"], ensure_ascii=False),
                    json.dumps(data["mcp_census"], ensure_ascii=False) if data["mcp_census"] else None,
                    now,
                    existing["id"],
                ),
            )
            return existing["id"]
        cur = conn.execute(
            """INSERT INTO digests
               (digest_date, title, price_events_json, release_events_json, mcp_census_json, generated_at)
               VALUES (?,?,?,?,?,?)""",
            (
                data["date"],
                title,
                json.dumps(data["price_events"], ensure_ascii=False),
                json.dumps(data["release_events"], ensure_ascii=False),
                json.dumps(data["mcp_census"], ensure_ascii=False) if data["mcp_census"] else None,
                now,
            ),
        )
        return cur.lastrowid


def run_digest_pipeline(digest_date: str | None = None) -> dict:
    if digest_date is None:
        digest_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = collect_events_for_digest(digest_date)
    digest_id = save_digest(data)
    return {"digest_id": digest_id, "date": digest_date, **{k: len(v) if isinstance(v, list) else (1 if v else 0) for k, v in data.items() if k != "date"}}


def get_digest(digest_date: str) -> dict | None:
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM digests WHERE digest_date = ?", (digest_date,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    for key in ("price_events_json", "release_events_json", "mcp_census_json"):
        if d.get(key):
            d[key] = json.loads(d[key])
    return d


def list_digests(limit: int = 30) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            "SELECT id, digest_date, title, generated_at FROM digests ORDER BY digest_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]