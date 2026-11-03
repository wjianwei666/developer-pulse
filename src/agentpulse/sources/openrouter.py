from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import httpx

from ..config import settings

PRICING_FIELDS = [
    "pricing_input",
    "pricing_output",
    "pricing_cache_read",
    "pricing_cache_creation",
    "pricing_reasoning",
    "pricing_cache_write",
    "pricing_image",
    "pricing_search",
]


def _per_token_to_per_million(value: str | float | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value) * 1_000_000
    except (TypeError, ValueError):
        return None


def fetch_openrouter_models() -> list[dict]:
    headers = {"User-Agent": settings.request_user_agent}
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=settings.request_timeout, headers=headers) as client:
                resp = client.get(settings.openrouter_url)
                resp.raise_for_status()
                data = resp.json()
                raw: list[dict] = []
                for item in data.get("data", []):
                    pricing = item.get("pricing", {}) or {}
                    model = {
                        "model_id": item["id"],
                        "name": item.get("name"),
                        "provider": item.get("provider"),
                        "context_length": item.get("context_length"),
                        "pricing_input": _per_token_to_per_million(pricing.get("prompt")),
                        "pricing_output": _per_token_to_per_million(pricing.get("completion")),
                        "pricing_cache_read": _per_token_to_per_million(pricing.get("cache_read")),
                        "pricing_cache_creation": _per_token_to_per_million(pricing.get("cache_creation")),
                        "pricing_reasoning": _per_token_to_per_million(pricing.get("reasoning")),
                        "pricing_cache_write": _per_token_to_per_million(pricing.get("cache_write")),
                        "pricing_image": _per_token_to_per_million(pricing.get("image")),
                        "pricing_search": _per_token_to_per_million(pricing.get("search")),
                        "archived": 1 if item.get("archived") else 0,
                        "deprecation_date": item.get("deprecation_date"),
                        "raw_json": json.dumps(item, ensure_ascii=False),
                    }
                    raw.append(model)
                return raw
        except Exception as exc:
            last_exc = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"OpenRouter fetch failed after 3 retries: {last_exc}")


def save_price_snapshot(models: list[dict]) -> int:
    from ..db import db_session

    now = datetime.now(timezone.utc).isoformat()
    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO snapshots (source, snapshot_type, created_at) VALUES (?, ?, ?)",
            ("openrouter", "price", now),
        )
        snapshot_id = cur.lastrowid
        rows = [
            (
                snapshot_id,
                m["model_id"],
                m["name"],
                m["provider"],
                m["context_length"],
                m["pricing_input"],
                m["pricing_output"],
                m["pricing_cache_read"],
                m["pricing_cache_creation"],
                m["pricing_reasoning"],
                m["pricing_cache_write"],
                m["pricing_image"],
                m["pricing_search"],
                m["archived"],
                m["deprecation_date"],
                m["raw_json"],
            )
            for m in models
        ]
        conn.executemany(
            """INSERT OR REPLACE INTO price_snapshots
               (snapshot_id, model_id, name, provider, context_length,
                pricing_input, pricing_output, pricing_cache_read, pricing_cache_creation,
                pricing_reasoning, pricing_cache_write, pricing_image, pricing_search,
                archived, deprecation_date, raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    return snapshot_id