"""Sliding-window rate limiter (per process) for the chat endpoint."""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float, clock=time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[object, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key) -> tuple[bool, int]:
        """Record a hit. Returns (allowed, retry_after_seconds)."""
        now = self.clock()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False, max(1, int(hits[0] + self.window - now) + 1)
            hits.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


USER_LIMITER = SlidingWindowLimiter(_env_int("AI_TUTOR_ASK_PER_USER", 20), 60)
TENANT_LIMITER = SlidingWindowLimiter(_env_int("AI_TUTOR_ASK_PER_TENANT", 120), 60)


def check_ask(tenant_id: int, user_id: int) -> tuple[bool, int]:
    ok, retry = USER_LIMITER.check((tenant_id, user_id))
    if not ok:
        return False, retry
    return TENANT_LIMITER.check(tenant_id)
