"""Small Redis-backed JSON cache for anonymous mobile discovery traffic."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any

from flask import current_app, g, has_app_context

_client = None
_client_url = ""
_retry_after = 0.0
_logger = logging.getLogger(__name__)


def _redis_client():
    global _client, _client_url, _retry_after
    if has_app_context() and current_app.config.get("TESTING"):
        return None
    url = (os.environ.get("REDIS_URL") or "").strip()
    if not url or time.monotonic() < _retry_after:
        return None
    try:
        if _client is None or _client_url != url:
            from redis import Redis

            _client = Redis.from_url(
                url,
                socket_connect_timeout=0.25,
                socket_timeout=0.25,
                health_check_interval=30,
                decode_responses=True,
            )
            _client_url = url
        return _client
    except Exception as exc:  # noqa: BLE001
        _retry_after = time.monotonic() + 10
        _logger.warning("Redis discovery cache unavailable: %s", exc)
        return None


def _key(namespace: str, parts: Any) -> str:
    tenant = str(getattr(g, "tenant", None) or "unknown")
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"finora:mobile:cache:{namespace}:{tenant}:{digest}"


def get_json(namespace: str, parts: Any) -> dict | list | None:
    client = _redis_client()
    if client is None:
        return None
    try:
        raw = client.get(_key(namespace, parts))
        if not raw:
            return None
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, (dict, list)) else None
    except Exception as exc:  # noqa: BLE001
        _logger.warning("Redis discovery cache read failed: %s", exc)
        return None


def set_json(namespace: str, parts: Any, value: dict | list, *, ttl: int) -> None:
    client = _redis_client()
    if client is None:
        return
    try:
        client.setex(
            _key(namespace, parts),
            max(1, int(ttl)),
            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        )
    except Exception as exc:  # noqa: BLE001
        _logger.warning("Redis discovery cache write failed: %s", exc)
