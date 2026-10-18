"""Staff POS access tokens (audience=pos_staff)."""
from __future__ import annotations

import logging
from typing import Any

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

logger = logging.getLogger(__name__)

ACCESS_TOKEN_MAX_AGE_SECONDS = 60 * 60
TOKEN_SALT = "finora-pos-staff-access-v1"


def _serializer() -> URLSafeTimedSerializer:
    secret = current_app.config.get("SECRET_KEY") or "dev-secret"
    return URLSafeTimedSerializer(secret_key=secret, salt=TOKEN_SALT)


def issue_access_token(*, employee_id: int, tenant_slug: str) -> str:
    payload = {
        "eid": int(employee_id),
        "tenant": tenant_slug,
        "typ": "access",
        "aud": "pos_staff",
    }
    return _serializer().dumps(payload)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        data = _serializer().loads(token, max_age=ACCESS_TOKEN_MAX_AGE_SECONDS)
    except SignatureExpired:
        logger.info("pos access token expired")
        return None
    except BadSignature:
        logger.info("pos access token invalid")
        return None
    if not isinstance(data, dict):
        return None
    if data.get("typ") != "access" or data.get("aud") != "pos_staff":
        return None
    return data
