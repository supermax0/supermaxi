"""Meta Graph reliability: error classification, channel health, and outbound retry with backoff.

Shared by every Meta send path (AI replies, manual inbox replies, FINORA CORE) so a failure is classified the same way
everywhere and a message is only ever marked ``sent`` after Meta returned a real message id.
"""
from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Channel health values persisted in AISalesChannelAccount.connection_status.
HEALTH_CONNECTED = "connected"
HEALTH_TOKEN_EXPIRED = "auth_expired"  # historical value kept for compatibility with the existing inbox UI
HEALTH_TOKEN_INVALID = "token_invalid"
HEALTH_PERMISSION_MISSING = "permission_missing"
HEALTH_WEBHOOK_INVALID = "webhook_invalid"
HEALTH_DISCONNECTED = "disconnected"

# Meta error codes — https://developers.facebook.com/docs/graph-api/guides/error-handling
_AUTH_CODES = {102, 190}
_EXPIRED_SUBCODES = {463, 467}  # expired / invalid-after-logout
_PERMISSION_CODES = {3, 10} | set(range(200, 300))
_RATE_CODES = {4, 17, 32, 613, 80001, 80002, 80003, 80004, 80005, 80006, 80008, 80014}
_TRANSIENT_CODES = {1, 2}
# Policy failures are the customer's state, not the channel's: never retry, never mark the channel unhealthy.
_POLICY_SUBCODES = {2018278, 2018108, 2534022, 1545041, 2018001}
_RECIPIENT_CODES = {551, 100}

MAX_SEND_ATTEMPTS = 5
BASE_DELAY_SECONDS = 2.0
MAX_DELAY_SECONDS = 15 * 60


@dataclass(frozen=True)
class MetaFailure:
    kind: str  # token_expired | token_invalid | permission_missing | rate_limited | transient | policy | invalid_request | unknown
    retryable: bool
    retry_after: float | None
    code: int | None
    subcode: int | None
    message: str


def _error_body(exc: Exception) -> dict[str, Any]:
    body = getattr(exc, "response_body", None)
    if isinstance(body, dict):
        err = body.get("error")
        return err if isinstance(err, dict) else {}
    return {}


def _retry_after(exc: Exception) -> float | None:
    """Honour Meta's own back-off hints when present (Retry-After header or business-use-case usage)."""
    headers = getattr(exc, "response_headers", None) or {}
    value = headers.get("Retry-After") if hasattr(headers, "get") else None
    if value and str(value).isdigit():
        return float(value)
    usage = headers.get("X-Business-Use-Case-Usage") if hasattr(headers, "get") else None
    if usage:
        try:
            parsed = json.loads(usage)
            minutes = [
                int(item.get("estimated_time_to_regain_access") or 0)
                for rows in parsed.values()
                for item in (rows if isinstance(rows, list) else [])
            ]
            if minutes and max(minutes) > 0:
                return float(max(minutes) * 60)
        except (ValueError, AttributeError, TypeError):
            logger.debug("unparseable X-Business-Use-Case-Usage header")
    return None


def classify(exc: Exception) -> MetaFailure:
    err = _error_body(exc)
    code = getattr(exc, "meta_code", None) or err.get("code")
    subcode = err.get("error_subcode")
    status = getattr(exc, "status_code", None)
    try:
        code = int(code) if code is not None else None
        subcode = int(subcode) if subcode is not None else None
    except (TypeError, ValueError):
        code, subcode = None, None
    message = str(err.get("message") or exc)[:500]
    if getattr(exc, "provider", None) == "telegram" and status == 403:
        # Blocking one bot chat is a recipient failure, not loss of the bot's permissions.
        return MetaFailure("invalid_request", False, None, code, subcode, message)

    if subcode in _POLICY_SUBCODES:
        return MetaFailure("policy", False, None, code, subcode, message)
    if code in _AUTH_CODES or status == 401:
        kind = "token_expired" if subcode in _EXPIRED_SUBCODES or "expired" in message.lower() else "token_invalid"
        return MetaFailure(kind, False, None, code, subcode, message)
    if code in _RATE_CODES or status == 429:
        return MetaFailure("rate_limited", True, _retry_after(exc), code, subcode, message)
    if code in _PERMISSION_CODES or status == 403:
        return MetaFailure("permission_missing", False, None, code, subcode, message)
    if code in _TRANSIENT_CODES or (status is not None and status >= 500) or err.get("is_transient") is True:
        return MetaFailure("transient", True, _retry_after(exc), code, subcode, message)
    if status is None and code is None:
        # requests-level failure (timeout, DNS, connection reset): the message may not have reached Meta.
        return MetaFailure("transient", True, None, None, None, message)
    if code in _RECIPIENT_CODES:
        return MetaFailure("invalid_request", False, None, code, subcode, message)
    return MetaFailure("unknown", False, None, code, subcode, message)


def health_for(failure: MetaFailure) -> str | None:
    """Channel health implied by a failure; ``None`` means the channel itself is fine."""
    return {
        "token_expired": HEALTH_TOKEN_EXPIRED,
        "token_invalid": HEALTH_TOKEN_INVALID,
        "permission_missing": HEALTH_PERMISSION_MISSING,
    }.get(failure.kind)


def apply_channel_failure(channel, failure: MetaFailure) -> None:
    health = health_for(failure)
    channel.last_error = f"[{failure.kind}] {failure.message}"[:2000]
    if health:
        channel.connection_status = health
        logger.warning("meta channel %s health → %s (code=%s sub=%s)", channel.id, health, failure.code, failure.subcode)


def apply_channel_success(channel) -> None:
    if channel.connection_status != HEALTH_CONNECTED:
        logger.info("meta channel %s health → connected", channel.id)
    channel.connection_status = HEALTH_CONNECTED
    channel.last_error = None


def backoff_delay(attempt: int, retry_after: float | None = None) -> float:
    """Exponential backoff with full jitter, never shorter than Meta's own hint."""
    computed = min(MAX_DELAY_SECONDS, BASE_DELAY_SECONDS * (2 ** max(0, attempt - 1)))
    jittered = computed * (0.5 + random.random() * 0.5)
    return max(jittered, retry_after or 0.0)


class SendRejected(Exception):
    """Meta accepted the HTTP request but returned no message id — never treated as sent."""


_MID_RE = re.compile(r"^[A-Za-z0-9_.:=+/\-]{6,300}$")


def require_message_id(external_id: str | None) -> str:
    if not external_id or not _MID_RE.match(external_id):
        raise SendRejected("Meta did not return a message id")
    return external_id


def record_send_failure(message, channel, exc: Exception, *, now: datetime | None = None) -> MetaFailure:
    """Persist a send failure on the message: either schedule a retry or mark it failed. Caller commits."""
    now = now or datetime.utcnow()
    failure = classify(exc) if not isinstance(exc, SendRejected) else MetaFailure(
        "unknown", False, None, None, None, str(exc)
    )
    meta = message.get_media_metadata() if hasattr(message, "get_media_metadata") else {}
    attempts = int((meta.get("send") or {}).get("attempts") or 0) + 1
    apply_channel_failure(channel, failure)
    message.failure_code = str(failure.code or failure.kind)[:100]
    message.failure_message = failure.message
    if failure.retryable and attempts < MAX_SEND_ATTEMPTS:
        delay = backoff_delay(attempts, failure.retry_after)
        message.status = "retry_scheduled"
        meta["send"] = {"attempts": attempts, "next_attempt_at": (now + timedelta(seconds=delay)).isoformat(), "last_kind": failure.kind}
    else:
        message.status = "failed"
        meta["send"] = {"attempts": attempts, "last_kind": failure.kind, "gave_up_at": now.isoformat()}
    if hasattr(message, "set_media_metadata"):
        message.set_media_metadata(meta)
    return failure


def record_send_success(message, channel, external_id: str, *, now: datetime | None = None) -> None:
    now = now or datetime.utcnow()
    message.external_message_id = require_message_id(external_id)
    message.status = "sent"
    message.sent_at = now
    message.failure_code = None
    message.failure_message = None
    apply_channel_success(channel)


def due_for_retry(message, now: datetime | None = None) -> bool:
    if message.status != "retry_scheduled":
        return False
    meta = message.get_media_metadata() if hasattr(message, "get_media_metadata") else {}
    raw = (meta.get("send") or {}).get("next_attempt_at")
    try:
        return datetime.fromisoformat(raw) <= (now or datetime.utcnow()) if raw else True
    except ValueError:
        return True
