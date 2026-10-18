"""Which tenants get fail-closed Meta security, and webhook health bookkeeping.

The FINORA house tenant (``FINORA_CORE_HOUSE_TENANT``) always requires a valid app secret and a valid
``X-Hub-Signature-256`` on every event. Other tenants keep their existing behaviour unless ``META_REQUIRE_SIGNATURE=1``
is set (recommended for production once every customer connector has an app secret).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)

SIGNATURE_FAILURE_THRESHOLD = 3
SIGNATURE_FAILURE_WINDOW = 600.0
_failures: dict[int, deque] = {}
_lock = threading.Lock()


def house_tenant() -> str | None:
    from modules.finora_core.store import house_slug

    return house_slug()


def is_house_tenant(tenant_slug: str | None) -> bool:
    house = house_tenant()
    return bool(house and tenant_slug and tenant_slug.lower() == house)


def signature_required(tenant_slug: str | None) -> bool:
    return is_house_tenant(tenant_slug) or os.environ.get("META_REQUIRE_SIGNATURE") == "1"


def record_signature_failure(connector) -> bool:
    """Returns True when the connector crossed the threshold and is now marked ``webhook_invalid``.
    A threshold (not a single failure) keeps one forged request from flipping the health indicator."""
    now = time.monotonic()
    with _lock:
        hits = _failures.setdefault(connector.id, deque())
        hits.append(now)
        while hits and now - hits[0] > SIGNATURE_FAILURE_WINDOW:
            hits.popleft()
        crossed = len(hits) >= SIGNATURE_FAILURE_THRESHOLD
    if crossed:
        connector.connection_status = "webhook_invalid"
        connector.last_error = "Meta webhook signatures are failing — check META app secret"
    return crossed


def record_signature_success(connector) -> None:
    with _lock:
        _failures.pop(connector.id, None)
    if connector.connection_status == "webhook_invalid":
        connector.connection_status = "connected"
        connector.last_error = None


def mark_secret_unusable(connector, problem: str) -> None:
    connector.connection_status = "webhook_invalid"
    connector.last_error = f"META app secret {problem}: events rejected (fail closed)"
    logger.error("meta connector %s rejects events: app secret %s", connector.id, problem)


def reset_for_tests() -> None:
    with _lock:
        _failures.clear()
