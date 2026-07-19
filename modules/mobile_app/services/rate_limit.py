"""Lightweight in-process rate limiting for sensitive mobile API routes."""
from __future__ import annotations

import threading
import time
import hashlib
import logging
import os
from collections import defaultdict, deque

from flask import current_app, g, has_app_context, request

from modules.mobile_app.schemas import api_error

_lock = threading.Lock()
_buckets: dict[str, deque[float]] = defaultdict(deque)
_redis_client = None
_redis_url = ""
_redis_retry_after = 0.0
_logger = logging.getLogger(__name__)


def _client_key(namespace: str) -> str:
    tenant = getattr(g, "tenant", None) or "unknown"
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "0.0.0.0").split(",")[
        0
    ].strip()
    user = getattr(getattr(g, "mobile_user", None), "id", None) or "anon"
    return f"{namespace}:{tenant}:{ip}:{user}"


def allow_request(namespace: str, *, limit: int, window_seconds: int) -> bool:
    """Return True if the request is within the rate limit."""
    if limit <= 0:
        return True
    key = _client_key(namespace)
    distributed = _allow_request_redis(
        key, limit=limit, window_seconds=window_seconds
    )
    if distributed is not None:
        return distributed
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        bucket = _buckets[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        # Bound memory for idle keys
        if len(_buckets) > 5000:
            stale = [k for k, v in _buckets.items() if not v or v[-1] < cutoff]
            for k in stale[:1000]:
                _buckets.pop(k, None)
    return True


def _allow_request_redis(
    key: str, *, limit: int, window_seconds: int
) -> bool | None:
    """Use a shared atomic counter when Redis is configured; None means fallback."""
    global _redis_client, _redis_url, _redis_retry_after
    if has_app_context() and current_app.config.get("TESTING"):
        return None
    url = (os.environ.get("REDIS_URL") or "").strip()
    if not url or time.monotonic() < _redis_retry_after:
        return None
    try:
        if _redis_client is None or _redis_url != url:
            from redis import Redis

            _redis_client = Redis.from_url(
                url,
                socket_connect_timeout=0.4,
                socket_timeout=0.4,
                health_check_interval=30,
                decode_responses=True,
            )
            _redis_url = url
        window_seconds = max(1, int(window_seconds))
        bucket = int(time.time()) // window_seconds
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        redis_key = f"finora:mobile:rate:{key_hash}:{bucket}"
        count = _redis_client.eval(
            """
            local current = redis.call('INCR', KEYS[1])
            if current == 1 then
              redis.call('EXPIRE', KEYS[1], ARGV[1])
            end
            return current
            """,
            1,
            redis_key,
            window_seconds + 2,
        )
        return int(count) <= limit
    except Exception as exc:  # noqa: BLE001
        _redis_retry_after = time.monotonic() + 10
        _logger.warning("Redis rate limiter unavailable; using local fallback: %s", exc)
        return None


def enforce_rate_limit(namespace: str, *, limit: int, window_seconds: int = 60):
    """Flask helper: return an error response when limited, else None."""
    if allow_request(namespace, limit=limit, window_seconds=window_seconds):
        return None
    return api_error(
        "تم تجاوز حد الطلبات. حاول لاحقاً.",
        429,
        code="rate_limited",
    )


def reset_rate_limits_for_tests() -> None:
    global _redis_client, _redis_url, _redis_retry_after
    with _lock:
        _buckets.clear()
    _redis_client = None
    _redis_url = ""
    _redis_retry_after = 0.0
