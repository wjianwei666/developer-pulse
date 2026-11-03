from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import settings
from .db import db_session
from .governance.cost_control import log_run
from .pipeline.digest import run_digest_pipeline
from .pipeline.ecosystem_pipeline import run_mcp_pipeline, run_release_pipeline
from .pipeline.price_pipeline import run_price_pipeline

logger = logging.getLogger("agentpulse.scheduler")

SNAPSHOT_TABLES = {
    "price": "price_snapshots",
    "release": "release_snapshots",
    "mcp": "mcp_snapshots",
}


def cleanup_old_snapshots(keep_per_type: int = 50) -> dict:
    with db_session() as conn:
        deleted = 0
        for snap_type, table in SNAPSHOT_TABLES.items():
            rows = conn.execute(
                "SELECT id FROM snapshots WHERE snapshot_type = ? ORDER BY id DESC",
                (snap_type,),
            ).fetchall()
            keep_ids = {r["id"] for r in rows[:keep_per_type]}
            old_ids = [r["id"] for r in rows[keep_per_type:]]
            for sid in old_ids:
                conn.execute(f"DELETE FROM {table} WHERE snapshot_id = ?", (sid,))
                conn.execute("DELETE FROM snapshots WHERE id = ?", (sid,))
                deleted += 1
        return {"deleted_snapshots": deleted}


def _safe_run(name: str, fn) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    try:
        result = fn()
        log_run(name, "success", started, str(result))
        logger.info("Pipeline %s succeeded: %s", name, result)
        return result
    except Exception as exc:
        log_run(name, "failed", started, str(exc))
        logger.exception("Pipeline %s failed", name)
        return {"error": str(exc)}


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")

    scheduler.add_job(
        lambda: _safe_run("price", run_price_pipeline),
        IntervalTrigger(hours=settings.openrouter_poll_hours),
        id="price_pipeline",
        replace_existing=True,
    )

    scheduler.add_job(
        lambda: _safe_run("release", run_release_pipeline),
        IntervalTrigger(hours=settings.github_poll_hours),
        id="release_pipeline",
        replace_existing=True,
    )

    scheduler.add_job(
        lambda: _safe_run("mcp", run_mcp_pipeline),
        IntervalTrigger(hours=settings.mcp_poll_hours),
        id="mcp_pipeline",
        replace_existing=True,
    )

    hour, minute = settings.digest_time_utc.split(":")
    scheduler.add_job(
        lambda: _safe_run("digest", run_digest_pipeline),
        CronTrigger(hour=int(hour), minute=int(minute)),
        id="digest_pipeline",
        replace_existing=True,
    )

    scheduler.add_job(
        lambda: _safe_run("cleanup", cleanup_old_snapshots),
        CronTrigger(hour=3, minute=0),
        id="cleanup_snapshots",
        replace_existing=True,
    )

    return scheduler