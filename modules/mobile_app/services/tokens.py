"""Access / refresh token helpers for mobile sessions."""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

logger = logging.getLogger(__name__)

ACCESS_TOKEN_MAX_AGE_SECONDS = 15 * 60  # 15 minutes
REFRESH_TOKEN_DAYS = 30
TOKEN_SALT = "finora-mobile-access-v1"


def _serializer() -> URLSafeTimedSerializer:
    secret = current_app.config.get("SECRET_KEY") or "dev-secret"
    return URLSafeTimedSerializer(secret_key=secret, salt=TOKEN_SALT)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_access_token(*, user_id: int, tenant_slug: str, session_id: int) -> str:
    payload = {
        "uid": int(user_id),
        "tenant": tenant_slug,
        "sid": int(session_id),
        "typ": "access",
    }
    return _serializer().dumps(payload)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        data = _serializer().loads(token, max_age=ACCESS_TOKEN_MAX_AGE_SECONDS)
    except SignatureExpired:
        logger.info("mobile access token expired")
        return None
    except BadSignature:
        logger.info("mobile access token invalid")
        return None
    if not isinstance(data, dict) or data.get("typ") != "access":
        return None
    return data


def issue_refresh_token() -> tuple[str, str, datetime]:
    raw = secrets.token_urlsafe(48)
    expires = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_DAYS)
    return raw, hash_token(raw), expires
