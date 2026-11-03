from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    snapshot_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    snapshot_id INTEGER NOT NULL,
    model_id TEXT NOT NULL,
    name TEXT,
    provider TEXT,
    context_length INTEGER,
    pricing_input REAL,
    pricing_output REAL,
    pricing_cache_read REAL,
    pricing_cache_creation REAL,
    pricing_reasoning REAL,
    pricing_cache_write REAL,
    pricing_image REAL,
    pricing_search REAL,
    archived INTEGER DEFAULT 0,
    deprecation_date TEXT,
    raw_json TEXT,
    PRIMARY KEY (snapshot_id, model_id),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

CREATE TABLE IF NOT EXISTS price_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    field_name TEXT,
    old_value TEXT,
    new_value TEXT,
    change_pct REAL,
    impact_score REAL,
    grade TEXT,
    blended_cost_old REAL,
    blended_cost_new REAL,
    percentile_shift REAL,
    source TEXT,
    source_url TEXT,
    detected_at TEXT NOT NULL,
    snapshot_id INTEGER,
    notified INTEGER DEFAULT 0,
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

CREATE INDEX IF NOT EXISTS idx_price_events_model ON price_events(model_id);
CREATE INDEX IF NOT EXISTS idx_price_events_detected ON price_events(detected_at);

CREATE TABLE IF NOT EXISTS release_snapshots (
    snapshot_id INTEGER NOT NULL,
    repo TEXT NOT NULL,
    tag TEXT NOT NULL,
    version TEXT,
    title TEXT,
    content TEXT,
    published_at TEXT,
    url TEXT,
    PRIMARY KEY (snapshot_id, repo, tag),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

CREATE TABLE IF NOT EXISTS release_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    tag TEXT NOT NULL,
    breaking_grade TEXT NOT NULL,
    impact_score REAL,
    migration_steps TEXT,
    deadline TEXT,
    days_remaining INTEGER,
    source TEXT,
    source_url TEXT,
    detected_at TEXT NOT NULL,
    snapshot_id INTEGER,
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

CREATE INDEX IF NOT EXISTS idx_release_events_repo ON release_events(repo);
CREATE INDEX IF NOT EXISTS idx_release_events_detected ON release_events(detected_at);

CREATE TABLE IF NOT EXISTS mcp_snapshots (
    snapshot_id INTEGER NOT NULL,
    server_id TEXT NOT NULL,
    name TEXT,
    version TEXT,
    pkg_version TEXT,
    remote_url TEXT,
    is_remote INTEGER DEFAULT 0,
    PRIMARY KEY (snapshot_id, server_id),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

CREATE TABLE IF NOT EXISTS mcp_census (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    total INTEGER,
    new_count INTEGER,
    deprecated INTEGER,
    deleted INTEGER,
    remote_ratio REAL,
    drift_count INTEGER,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_date TEXT NOT NULL UNIQUE,
    title TEXT,
    price_events_json TEXT,
    release_events_json TEXT,
    mcp_census_json TEXT,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscribers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    tier TEXT NOT NULL DEFAULT 'free',
    status TEXT NOT NULL DEFAULT 'pending',
    confirm_token TEXT,
    github_login TEXT,
    api_key TEXT,
    created_at TEXT NOT NULL,
    confirmed_at TEXT
);

CREATE TABLE IF NOT EXISTS run_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    detail TEXT
);
"""


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def get_connection() -> sqlite3.Connection:
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            conn = _connect(settings.db_path)
            return conn
        except sqlite3.Error as exc:
            last_err = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"Failed to connect to SQLite after retries: {last_err}")


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {r[1] for r in conn.execute("PRAGMA table_info(subscribers)").fetchall()}
    for col in ("github_login", "api_key"):
        if col not in existing:
            conn.execute(f"ALTER TABLE subscribers ADD COLUMN {col} TEXT")


def init_db() -> None:
    with db_session() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)