from __future__ import annotations

import re
from datetime import datetime, timezone

from ..db import db_session
from .scoring import adoption_weight, grade_from_score, score_release_event

BREAKING_KEYWORDS = [
    r"\bbreaking\b",
    r"\bbreaking change\b",
    r"\bmust migrate\b",
    r"\brequires migration\b",
    r"\bincompatible\b",
    r"\bdeprecated\b",
    r"\bdeprecation\b",
    r"\bwill be removed\b",
    r"\bremove[d]?\b",
    r"\breplace\b",
]

DEPRECATION_KEYWORDS = [r"\bdeprecated\b", r"\bdeprecation\b", r"\bwill be removed\b", r"\b sunset\b", r"\bsunsetting\b"]

NOISE_KEYWORDS = [r"\bdocs\b", r"\bdocumentation\b", r"\bchore\b", r"\bci\b", r"\btypo\b", r"\breadme\b"]

DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def parse_semver(version: str) -> tuple[int, int, int] | None:
    m = SEMVER.match(version or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def semver_jump(old: str, new: str) -> str:
    o, n = parse_semver(old), parse_semver(new)
    if not o or not n:
        return "none"
    if n[0] > o[0]:
        return "major"
    if n[1] > o[1]:
        return "minor"
    if n[2] > o[2]:
        return "patch"
    return "none"


def detect_breaking_grade(content: str, version_jump: str) -> str:
    text = content or ""
    lower = text.lower()

    has_breaking = any(re.search(p, lower) for p in BREAKING_KEYWORDS[:5])
    has_deprecation = any(re.search(p, lower) for p in DEPRECATION_KEYWORDS)
    is_noise = bool(re.search(r"^\s*[\[(]?(docs?|chore|ci|typo|readme)", lower))

    if has_breaking:
        return "breaking"
    if has_deprecation and version_jump in ("major", "minor"):
        return "breaking"
    if version_jump == "major":
        return "likely"
    if has_deprecation:
        return "watch"
    if is_noise:
        return "noise"
    return "safe"


def extract_migration_steps(content: str, max_steps: int = 3) -> list[str]:
    if not content:
        return []
    sentences = SENTENCE_SPLIT.split(content)
    sentences = [s.strip() for s in sentences if s.strip()]
    action_sentences = [
        s for s in sentences
        if re.search(r"\b(migrat|update|upgrade|change|replace|remove|add|set|use|run|install)\b", s, re.IGNORECASE)
    ]
    steps = action_sentences[:max_steps]
    cleaned = []
    for s in steps:
        s = re.sub(r"<[^>]+>", "", s)
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) > 500:
            s = s[:500] + "..."
        cleaned.append(s)
    return cleaned


def extract_deadline(content: str) -> tuple[str | None, int | None]:
    if not content:
        return None, None
    match = DATE_PATTERN.search(content)
    if not match:
        return None, None
    date_str = match.group(1)
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        days = (dt - datetime.now(timezone.utc)).days
        return date_str, days
    except ValueError:
        return None, None


def _repo_adoption(repo: str) -> float:
    name = repo.split("/")[-1].lower()
    for vendor, weight in {
        "mastra": 80, "langgraph": 90, "langchain": 90,
        "servers": 70, "openai-python": 95, "anthropic-sdk-python": 90,
        "ai": 75,
    }.items():
        if vendor in name:
            return float(weight)
    return 50.0


def detect_release_changes(new_snapshot_id: int) -> list[dict]:
    with db_session() as conn:
        prev = conn.execute(
            "SELECT id FROM snapshots WHERE snapshot_type = 'release' AND id < ? ORDER BY id DESC LIMIT 1",
            (new_snapshot_id,),
        ).fetchone()
        prev_id = prev["id"] if prev else None

        new_rows = conn.execute(
            "SELECT * FROM release_snapshots WHERE snapshot_id = ?", (new_snapshot_id,)
        ).fetchall()
        new_map = {(r["repo"], r["tag"]): dict(r) for r in new_rows}

        old_tags: set[tuple[str, str]] = set()
        if prev_id:
            old_rows = conn.execute(
                "SELECT repo, tag FROM release_snapshots WHERE snapshot_id = ?", (prev_id,)
            ).fetchall()
            old_tags = {(r["repo"], r["tag"]) for r in old_rows}

    now = datetime.now(timezone.utc).isoformat()
    events: list[dict] = []

    sorted_by_repo: dict[str, list[dict]] = {}
    for (repo, tag), row in new_map.items():
        sorted_by_repo.setdefault(repo, []).append(row)

    for repo, rows in sorted_by_repo.items():
        rows_sorted = sorted(rows, key=lambda r: r.get("published_at") or "", reverse=True)
        prev_version_for_repo: str | None = None
        for row in rows_sorted:
            key = (repo, row["tag"])
            if key in old_tags:
                prev_version_for_repo = row.get("version")
                continue

            content = row.get("content") or ""
            version = row.get("version") or ""
            jump = semver_jump(prev_version_for_repo or "", version) if prev_version_for_repo else "patch"
            grade = detect_breaking_grade(content, jump)
            steps = extract_migration_steps(content)
            deadline, days_remaining = extract_deadline(content)
            adoption = _repo_adoption(repo)
            score = score_release_event(
                breaking_grade=grade,
                adoption=adoption,
                days_remaining=days_remaining,
                has_migration_steps=bool(steps),
                is_noise=(grade == "noise"),
            )
            grade_final = grade_from_score(score)

            events.append(
                {
                    "repo": repo,
                    "tag": row["tag"],
                    "breaking_grade": grade,
                    "impact_score": round(score, 2),
                    "migration_steps": "\n".join(steps) if steps else "",
                    "deadline": deadline,
                    "days_remaining": days_remaining,
                    "source": "github",
                    "source_url": row.get("url"),
                    "detected_at": now,
                    "snapshot_id": new_snapshot_id,
                    "grade": grade_final,
                }
            )
            prev_version_for_repo = version

    return events


def save_release_events(events: list[dict]) -> int:
    from ..db import db_session

    if not events:
        return 0

    with db_session() as conn:
        existing = conn.execute(
            "SELECT repo, tag FROM release_events"
        ).fetchall()
        existing_fps = {(r["repo"], r["tag"]) for r in existing}

    unique_events = [e for e in events if (e["repo"], e["tag"]) not in existing_fps]

    with db_session() as conn:
        rows = [
            (
                e["repo"],
                e["tag"],
                e["breaking_grade"],
                e.get("impact_score"),
                e.get("migration_steps"),
                e.get("deadline"),
                e.get("days_remaining"),
                e.get("source"),
                e.get("source_url"),
                e["detected_at"],
                e.get("snapshot_id"),
            )
            for e in unique_events
        ]
        conn.executemany(
            """INSERT INTO release_events
               (repo, tag, breaking_grade, impact_score, migration_steps, deadline,
                days_remaining, source, source_url, detected_at, snapshot_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    return len(unique_events)


def run_release_pipeline() -> dict:
    from ..sources.github_releases import fetch_all_releases, save_release_snapshot

    releases = fetch_all_releases()
    snapshot_id = save_release_snapshot(releases)
    events = detect_release_changes(snapshot_id)
    saved = save_release_events(events)

    alert_events = [e for e in events if e.get("impact_score", 0) >= 60]
    digest_events = [e for e in events if 40 <= e.get("impact_score", 0) < 60]
    if alert_events or digest_events:
        try:
            from ..distribution.webhooks import dispatch_webhooks
            dispatch_webhooks([], alert_events + digest_events)
        except Exception:
            pass

    return {"snapshot_id": snapshot_id, "releases_collected": len(releases), "events_detected": saved}


def run_mcp_census(new_snapshot_id: int) -> dict:
    with db_session() as conn:
        prev = conn.execute(
            "SELECT id FROM snapshots WHERE snapshot_type = 'mcp' AND id < ? ORDER BY id DESC LIMIT 1",
            (new_snapshot_id,),
        ).fetchone()
        prev_id = prev["id"] if prev else None

        new_rows = conn.execute(
            "SELECT * FROM mcp_snapshots WHERE snapshot_id = ?", (new_snapshot_id,)
        ).fetchall()
        new_map = {r["server_id"]: dict(r) for r in new_rows}

        old_map: dict[str, dict] = {}
        if prev_id:
            old_rows = conn.execute(
                "SELECT * FROM mcp_snapshots WHERE snapshot_id = ?", (prev_id,)
            ).fetchall()
            old_map = {r["server_id"]: dict(r) for r in old_rows}

    total = len(new_map)
    new_count = sum(1 for sid in new_map if sid not in old_map)
    deleted = sum(1 for sid in old_map if sid not in new_map)
    deprecated = sum(1 for r in new_map.values() if r.get("version") == "deprecated")
    remote_count = sum(1 for r in new_map.values() if r.get("is_remote"))
    remote_ratio = remote_count / total if total else 0.0

    drift_count = 0
    for sid, new in new_map.items():
        old = old_map.get(sid)
        if not old:
            continue
        if new.get("version") == old.get("version") and new.get("pkg_version") != old.get("pkg_version"):
            drift_count += 1

    now = datetime.now(timezone.utc).isoformat()
    with db_session() as conn:
        conn.execute(
            """INSERT INTO mcp_census
               (snapshot_id, total, new_count, deprecated, deleted, remote_ratio, drift_count, recorded_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (new_snapshot_id, total, new_count, deprecated, deleted, round(remote_ratio, 4), drift_count, now),
        )
    return {
        "snapshot_id": new_snapshot_id,
        "total": total,
        "new": new_count,
        "deprecated": deprecated,
        "deleted": deleted,
        "remote_ratio": round(remote_ratio, 4),
        "drift_count": drift_count,
    }


def run_mcp_pipeline() -> dict:
    from ..sources.mcp_registry import fetch_mcp_servers, save_mcp_snapshot

    servers = fetch_mcp_servers()
    snapshot_id = save_mcp_snapshot(servers)
    census = run_mcp_census(snapshot_id)
    return {"snapshot_id": snapshot_id, "servers_collected": len(servers), **census}