from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from ..config import settings


def _fetch_page(client, params: dict, headers: dict) -> dict | None:
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = client.get(settings.mcp_registry_url, params=params, headers=headers)
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception as exc:
            last_exc = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"MCP registry fetch failed after 3 retries: {last_exc}")


def fetch_mcp_servers() -> list[dict]:
    servers: list[dict] = []
    cursor: str | None = None
    headers = {"User-Agent": settings.request_user_agent}
    with httpx.Client(timeout=settings.request_timeout) as client:
        while True:
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            data = _fetch_page(client, params, headers)
            if data is None:
                break
            for item in data.get("data", []):
                servers.append(
                    {
                        "server_id": item.get("id") or item.get("name"),
                        "name": item.get("name"),
                        "version": item.get("version"),
                        "pkg_version": item.get("pkg_version") or item.get("package_version"),
                        "remote_url": item.get("url") or item.get("remote_url"),
                        "is_remote": 1 if (item.get("url") or item.get("remote_url")) else 0,
                    }
                )
            cursor = data.get("next_cursor") or data.get("cursor")
            if not cursor:
                break
            time.sleep(settings.request_pagination_interval)
    return servers


def save_mcp_snapshot(servers: list[dict]) -> int:
    from ..db import db_session

    now = datetime.now(timezone.utc).isoformat()
    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO snapshots (source, snapshot_type, created_at) VALUES (?, ?, ?)",
            ("mcp_registry", "mcp", now),
        )
        snapshot_id = cur.lastrowid
        rows = [
            (
                snapshot_id,
                s["server_id"],
                s["name"],
                s["version"],
                s["pkg_version"],
                s["remote_url"],
                s["is_remote"],
            )
            for s in servers
        ]
        conn.executemany(
            """INSERT OR REPLACE INTO mcp_snapshots
               (snapshot_id, server_id, name, version, pkg_version, remote_url, is_remote)
               VALUES (?,?,?,?,?,?,?)""",
            rows,
        )
    return snapshot_id