"""Staff phone access/refresh tokens (audience=phone_staff)."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

logger = logging.getLogger(__name__)

ACCESS_TOKEN_MAX_AGE_SECONDS = 15 * 60
REFRESH_TOKEN_DAYS = 30
TOKEN_SALT = "finora-phone-staff-access-v1"


def _serializer() -> URLSafeTimedSerializer:
    secret = current_app.config.get("SECRET_KEY") or "dev-secret"
    return URLSafeTimedSerializer(secret_key=secret, salt=TOKEN_SALT)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_access_token(
    *,
    employee_id: int,
    tenant_slug: str,
    session_id: int,
) -> str:
    payload = {
        "eid": int(employee_id),
        "tenant": tenant_slug,
        "sid": int(session_id),
        "typ": "access",
        "aud": "phone_staff",
    }
    return _serializer().dumps(payload)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        data = _serializer().loads(token, max_age=ACCESS_TOKEN_MAX_AGE_SECONDS)
    except SignatureExpired:
        logger.info("phone access token expired")
        return None
    except BadSignature:
        logger.info("phone access token invalid")
        return None
    if not isinstance(data, dict):
        return None
    if data.get("typ") != "access" or data.get("aud") != "phone_staff":
        return None
    return data


def issue_refresh_token() -> tuple[str, str, datetime]:
    raw = secrets.token_urlsafe(48)
    expires = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_DAYS)
    return raw, hash_token(raw), expires
