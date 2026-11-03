from __future__ import annotations

import time
from datetime import datetime, timezone

import feedparser
import httpx

from ..config import settings


def _parse_date(entry) -> str | None:
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if not published:
        return None
    dt = datetime(*published[:6], tzinfo=timezone.utc)
    return dt.isoformat()


def fetch_releases(repo: str) -> list[dict]:
    url = f"https://github.com/{repo}/releases.atom"
    headers = {"User-Agent": settings.request_user_agent}
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=settings.request_timeout, headers=headers) as client:
                resp = client.get(url)
                if resp.status_code == 404:
                    return []
                resp.raise_for_status()
                text = resp.text
            break
        except Exception as exc:
            last_exc = exc
            time.sleep(2 ** attempt)
    else:
        raise RuntimeError(f"GitHub fetch failed for {repo} after 3 retries: {last_exc}")

    feed = feedparser.parse(text)
    releases: list[dict] = []
    for entry in feed.entries:
        tag = entry.get("id", "").rsplit("/", 1)[-1]
        link = entry.get("link", "")
        content = ""
        if entry.get("content"):
            content = entry["content"][0].get("value", "")
        elif entry.get("summary"):
            content = entry["summary"]
        releases.append(
            {
                "repo": repo,
                "tag": tag,
                "version": tag.lstrip("v"),
                "title": entry.get("title", ""),
                "content": content,
                "published_at": _parse_date(entry),
                "url": link,
            }
        )
    return releases


def fetch_all_releases(repos: list[str] | None = None) -> list[dict]:
    repos = repos or settings.github_repos
    all_releases: list[dict] = []
    for repo in repos:
        try:
            all_releases.extend(fetch_releases(repo))
        except Exception:
            continue
    return all_releases


def save_release_snapshot(releases: list[dict]) -> int:
    from ..db import db_session

    now = datetime.now(timezone.utc).isoformat()
    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO snapshots (source, snapshot_type, created_at) VALUES (?, ?, ?)",
            ("github", "release", now),
        )
        snapshot_id = cur.lastrowid
        rows = [
            (
                snapshot_id,
                r["repo"],
                r["tag"],
                r["version"],
                r["title"],
                r["content"],
                r["published_at"],
                r["url"],
            )
            for r in releases
        ]
        conn.executemany(
            """INSERT OR REPLACE INTO release_snapshots
               (snapshot_id, repo, tag, version, title, content, published_at, url)
               VALUES (?,?,?,?,?,?,?,?)""",
            rows,
        )
    return snapshot_id