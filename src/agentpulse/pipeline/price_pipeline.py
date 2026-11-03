from __future__ import annotations

from datetime import datetime, timezone

from ..config import settings
from ..db import db_session
from .scoring import adoption_weight, grade_from_score, score_price_event

PRICE_FIELDS = [
    "pricing_input",
    "pricing_output",
    "pricing_cache_read",
    "pricing_cache_creation",
    "pricing_reasoning",
    "pricing_cache_write",
    "pricing_image",
    "pricing_search",
]


def blended_cost(row: dict) -> float | None:
    cache_read = row.get("pricing_cache_read")
    inp = row.get("pricing_input")
    out = row.get("pricing_output")
    cache_base = cache_read if cache_read is not None else inp
    if cache_base is None or inp is None or out is None:
        return None
    return (
        cache_base * settings.blended_cache_ratio
        + inp * settings.blended_input_ratio
        + out * settings.blended_output_ratio
    )


def _pct_change(old: float | None, new: float | None) -> float | None:
    if old is None or new is None or old == 0:
        return None
    return (new - old) / old * 100.0


def _days_remaining(date_str: str | None) -> int | None:
    if not date_str:
        return None
    try:
        if len(date_str) == 10:
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        delta = dt - datetime.now(timezone.utc)
        return delta.days
    except (ValueError, TypeError):
        return None


def compute_percentile(blended: float, all_blended: list[float]) -> float:
    if not all_blended or blended is None:
        return 0.0
    below = sum(1 for b in all_blended if b is not None and b < blended)
    return below / len(all_blended) * 100.0


def _get_latest_snapshot(conn, snapshot_type: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM snapshots WHERE snapshot_type = ? ORDER BY id DESC LIMIT 1",
        (snapshot_type,),
    ).fetchone()
    return row["id"] if row else None


_ALLOWED_SNAPSHOT_TABLES = {"price_snapshots", "release_snapshots", "mcp_snapshots"}


def _fetch_snapshot_rows(conn, snapshot_id: int, table: str, id_col: str) -> dict[str, dict]:
    if table not in _ALLOWED_SNAPSHOT_TABLES:
        raise ValueError(f"Disallowed table: {table}")
    rows = conn.execute(f"SELECT * FROM {table} WHERE snapshot_id = ?", (snapshot_id,)).fetchall()
    return {r[id_col]: dict(r) for r in rows}


def detect_price_changes(new_snapshot_id: int) -> list[dict]:
    with db_session() as conn:
        prev_id = _get_latest_snapshot(conn, "price")
        new_rows = _fetch_snapshot_rows(conn, new_snapshot_id, "price_snapshots", "model_id")
        if prev_id is None or prev_id == new_snapshot_id:
            return []
        old_rows = _fetch_snapshot_rows(conn, prev_id, "price_snapshots", "model_id")

    all_new_blended = [blended_cost(r) for r in new_rows.values()]
    all_new_blended = [b for b in all_new_blended if b is not None]

    events: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    for model_id, new in new_rows.items():
        old = old_rows.get(model_id)
        if old is None:
            events.append(
                {
                    "model_id": model_id,
                    "event_type": "new",
                    "field_name": None,
                    "old_value": None,
                    "new_value": None,
                    "change_pct": None,
                    "blended_cost_old": None,
                    "blended_cost_new": blended_cost(new),
                    "percentile_shift": 0.0,
                    "source": "openrouter",
                    "source_url": f"https://openrouter.ai/{model_id}",
                    "detected_at": now,
                    "snapshot_id": new_snapshot_id,
                }
            )
            continue

        if old.get("archived") != new.get("archived") and new.get("archived"):
            events.append(
                {
                    "model_id": model_id,
                    "event_type": "removed",
                    "field_name": "archived",
                    "old_value": str(old.get("archived")),
                    "new_value": str(new.get("archived")),
                    "change_pct": None,
                    "blended_cost_old": blended_cost(old),
                    "blended_cost_new": blended_cost(new),
                    "percentile_shift": 0.0,
                    "source": "openrouter",
                    "source_url": f"https://openrouter.ai/{model_id}",
                    "detected_at": now,
                    "snapshot_id": new_snapshot_id,
                }
            )

        for field in PRICE_FIELDS:
            old_v = old.get(field)
            new_v = new.get(field)
            if old_v == new_v:
                continue
            change = _pct_change(old_v, new_v)
            if change is not None and abs(change) < settings.price_noise_threshold_pct:
                continue
            old_blended = blended_cost(old)
            new_blended = blended_cost(new)
            old_pct = compute_percentile(old_blended, all_new_blended) if old_blended else 0.0
            new_pct = compute_percentile(new_blended, all_new_blended) if new_blended else 0.0
            events.append(
                {
                    "model_id": model_id,
                    "event_type": "price",
                    "field_name": field,
                    "old_value": str(old_v) if old_v is not None else None,
                    "new_value": str(new_v) if new_v is not None else None,
                    "change_pct": round(change, 4) if change is not None else None,
                    "blended_cost_old": round(old_blended, 6) if old_blended is not None else None,
                    "blended_cost_new": round(new_blended, 6) if new_blended is not None else None,
                    "percentile_shift": round(new_pct - old_pct, 2),
                    "source": "openrouter",
                    "source_url": f"https://openrouter.ai/{model_id}",
                    "detected_at": now,
                    "snapshot_id": new_snapshot_id,
                }
            )

        old_ctx = old.get("context_length")
        new_ctx = new.get("context_length")
        if old_ctx != new_ctx:
            change = _pct_change(old_ctx, new_ctx)
            events.append(
                {
                    "model_id": model_id,
                    "event_type": "context",
                    "field_name": "context_length",
                    "old_value": str(old_ctx),
                    "new_value": str(new_ctx),
                    "change_pct": round(change, 4) if change is not None else None,
                    "blended_cost_old": blended_cost(old),
                    "blended_cost_new": blended_cost(new),
                    "percentile_shift": 0.0,
                    "source": "openrouter",
                    "source_url": f"https://openrouter.ai/{model_id}",
                    "detected_at": now,
                    "snapshot_id": new_snapshot_id,
                }
            )

        old_dep = old.get("deprecation_date")
        new_dep = new.get("deprecation_date")
        if old_dep != new_dep and new_dep:
            events.append(
                {
                    "model_id": model_id,
                    "event_type": "deprecation",
                    "field_name": "deprecation_date",
                    "old_value": old_dep,
                    "new_value": new_dep,
                    "change_pct": None,
                    "blended_cost_old": blended_cost(old),
                    "blended_cost_new": blended_cost(new),
                    "percentile_shift": 0.0,
                    "source": "openrouter",
                    "source_url": f"https://openrouter.ai/{model_id}",
                    "detected_at": now,
                    "snapshot_id": new_snapshot_id,
                }
            )

    for model_id in old_rows:
        if model_id not in new_rows:
            events.append(
                {
                    "model_id": model_id,
                    "event_type": "removed",
                    "field_name": None,
                    "old_value": None,
                    "new_value": None,
                    "change_pct": None,
                    "blended_cost_old": blended_cost(old_rows[model_id]),
                    "blended_cost_new": None,
                    "percentile_shift": 0.0,
                    "source": "openrouter",
                    "source_url": f"https://openrouter.ai/{model_id}",
                    "detected_at": now,
                    "snapshot_id": new_snapshot_id,
                }
            )

    return events


def enrich_price_events(events: list[dict]) -> list[dict]:
    for ev in events:
        adoption = adoption_weight(ev["model_id"])
        days = _days_remaining(ev.get("new_value") if ev["event_type"] == "deprecation" else None)
        score = score_price_event(
            event_type=ev["event_type"],
            field_name=ev.get("field_name"),
            change_pct=ev.get("change_pct") or 0.0,
            blended_cost_old=ev.get("blended_cost_old"),
            blended_cost_new=ev.get("blended_cost_new"),
            percentile_shift=ev.get("percentile_shift") or 0.0,
            adoption=adoption,
            days_remaining=days,
        )
        ev["impact_score"] = round(score, 2)
        if ev["event_type"] in ("new", "removed", "deprecation"):
            ev["grade"] = "alert" if score >= settings.score_alert_threshold else "digest"
        else:
            ev["grade"] = grade_from_score(score)
    return events


def _event_fingerprint(e: dict) -> tuple:
    return (
        e["model_id"],
        e["event_type"],
        e.get("field_name"),
        e.get("old_value"),
        e.get("new_value"),
    )


def save_price_events(events: list[dict]) -> int:
    from ..db import db_session

    if not events:
        return 0

    with db_session() as conn:
        existing = conn.execute(
            """SELECT model_id, event_type, field_name, old_value, new_value
               FROM price_events"""
        ).fetchall()
        existing_fps = {
            (r["model_id"], r["event_type"], r["field_name"], r["old_value"], r["new_value"])
            for r in existing
        }

    unique_events = [e for e in events if _event_fingerprint(e) not in existing_fps]

    with db_session() as conn:
        rows = [
            (
                e["model_id"],
                e["event_type"],
                e.get("field_name"),
                e.get("old_value"),
                e.get("new_value"),
                e.get("change_pct"),
                e.get("impact_score"),
                e.get("grade"),
                e.get("blended_cost_old"),
                e.get("blended_cost_new"),
                e.get("percentile_shift"),
                e.get("source"),
                e.get("source_url"),
                e["detected_at"],
                e.get("snapshot_id"),
            )
            for e in unique_events
        ]
        conn.executemany(
            """INSERT INTO price_events
               (model_id, event_type, field_name, old_value, new_value, change_pct,
                impact_score, grade, blended_cost_old, blended_cost_new, percentile_shift,
                source, source_url, detected_at, snapshot_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    return len(unique_events)


def run_price_pipeline() -> dict:
    from ..sources.openrouter import fetch_openrouter_models, save_price_snapshot

    models = fetch_openrouter_models()
    snapshot_id = save_price_snapshot(models)
    events = detect_price_changes(snapshot_id)
    events = enrich_price_events(events)
    saved = save_price_events(events)

    alert_events = [e for e in events if e.get("grade") == "alert"]
    digest_events = [e for e in events if e.get("grade") == "digest"]
    if alert_events or digest_events:
        try:
            from ..distribution.webhooks import dispatch_webhooks
            dispatch_webhooks(alert_events + digest_events, [])
        except Exception:
            pass

    return {"snapshot_id": snapshot_id, "models_collected": len(models), "events_detected": saved}