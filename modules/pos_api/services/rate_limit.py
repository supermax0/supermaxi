"""In-process rate limiting for the POS machine API."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from flask import g, request

from modules.pos_api.schemas import api_error

_lock = threading.Lock()
_buckets: dict[str, deque[float]] = defaultdict(deque)


def _client_key(namespace: str) -> str:
    tenant = getattr(g, "tenant", None) or "unknown"
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "0.0.0.0").split(",")[0].strip()
    emp = getattr(getattr(g, "pos_employee", None), "id", None) or "anon"
    return f"pos:{namespace}:{tenant}:{ip}:{emp}"


def allow_request(namespace: str, *, limit: int, window_seconds: int) -> bool:
    if limit <= 0:
        return True
    key = _client_key(namespace)
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        bucket = _buckets[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        if len(_buckets) > 5000:
            stale = [k for k, v in _buckets.items() if not v or v[-1] < cutoff]
            for k in stale[:1000]:
                _buckets.pop(k, None)
    return True


def enforce_rate_limit(namespace: str, *, limit: int, window_seconds: int = 60):
    if allow_request(namespace, limit=limit, window_seconds=window_seconds):
        return None
    return api_error("Too many requests", 429, code="rate_limited")
