from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone

from ..db import db_session


class RateLimiter:
    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        window_start = now - self.window
        hits = [t for t in self._hits[key] if t > window_start]
        self._hits[key] = hits
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True


rate_limiter = RateLimiter()


class CostTracker:
    def __init__(self, monthly_budget_usd: float = 50.0):
        self.monthly_budget = monthly_budget_usd
        self._spent: float = 0.0

    def add_cost(self, amount_usd: float) -> None:
        self._spent += amount_usd
        with db_session() as conn:
            conn.execute(
                "INSERT INTO run_log (pipeline, status, started_at, detail) VALUES (?, ?, ?, ?)",
                ("cost_tracker", "info", datetime.now(timezone.utc).isoformat(), f"+${amount_usd:.6f}"),
            )

    @property
    def spent(self) -> float:
        return self._spent

    @property
    def remaining(self) -> float:
        return max(0.0, self.monthly_budget - self._spent)

    @property
    def is_over_budget(self) -> bool:
        return self._spent >= self.monthly_budget


cost_tracker = CostTracker()


def log_run(pipeline: str, status: str, started_at: str, detail: str = "") -> None:
    with db_session() as conn:
        conn.execute(
            "INSERT INTO run_log (pipeline, status, started_at, finished_at, detail) VALUES (?, ?, ?, ?, ?)",
            (pipeline, status, started_at, datetime.now(timezone.utc).isoformat(), detail),
        )