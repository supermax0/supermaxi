"""Desktop authentication: short-lived signed access tokens + rotating, hashed refresh tokens."""
from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable

from flask import current_app, g, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .errors import CoreApiError, auth_error, permission_error
from .models import FcDesktopSession, FcOperatorRole
from .permissions import DEFAULT_ROLE, permissions_for
from .store import core_session

logger = logging.getLogger(__name__)

ACCESS_TTL_SECONDS = 15 * 60
REFRESH_TTL = timedelta(days=14)
_SALT = "finora-core-desktop-access-v1"


@dataclass(frozen=True)
class Operator:
    superadmin_id: int
    username: str
    role: str
    session_id: int

    @property
    def permissions(self) -> frozenset[str]:
        return permissions_for(self.role)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.superadmin_id,
            "username": self.username,
            "role": self.role,
            "permissions": sorted(self.permissions),
        }


def _serializer() -> URLSafeTimedSerializer:
    secret = current_app.config.get("SECRET_KEY")
    if not secret:
        raise RuntimeError("SECRET_KEY must be configured for FINORA CORE tokens")
    return URLSafeTimedSerializer(secret_key=secret, salt=_SALT)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ───────────────────────────── login throttling ─────────────────────────────

_FAIL_WINDOW = 10 * 60
_FAIL_LIMIT = 5
_failures: dict[str, list[float]] = {}
_fail_lock = threading.Lock()


def _throttle_key(username: str) -> str:
    return f"{request.remote_addr or '?'}|{username.lower()}"


def check_login_allowed(username: str) -> None:
    now = time.monotonic()
    with _fail_lock:
        hits = [t for t in _failures.get(_throttle_key(username), []) if now - t < _FAIL_WINDOW]
        _failures[_throttle_key(username)] = hits
        if len(hits) >= _FAIL_LIMIT:
            raise CoreApiError("RATE_LIMITED", "محاولات كثيرة. حاول بعد دقائق", 429)


def record_login_failure(username: str) -> None:
    with _fail_lock:
        _failures.setdefault(_throttle_key(username), []).append(time.monotonic())


def clear_login_failures(username: str) -> None:
    with _fail_lock:
        _failures.pop(_throttle_key(username), None)


# ───────────────────────────── tokens ─────────────────────────────


def role_for(s, superadmin_id: int) -> str:
    row = s.get(FcOperatorRole, superadmin_id)
    return row.role if row else DEFAULT_ROLE


def issue_tokens(s, *, superadmin_id: int, username: str, session: FcDesktopSession | None = None) -> dict[str, Any]:
    """Creates a session (login) or rotates an existing one (refresh). Caller commits."""
    raw_refresh = secrets.token_urlsafe(48)
    now = datetime.utcnow()
    if session is None:
        session = FcDesktopSession(
            superadmin_id=superadmin_id,
            refresh_hash=hash_token(raw_refresh),
            user_agent=(request.headers.get("User-Agent") or "")[:300],
            ip=(request.remote_addr or "")[:64],
            expires_at=now + REFRESH_TTL,
        )
        s.add(session)
        s.flush()
    else:
        session.previous_hash = session.refresh_hash
        session.refresh_hash = hash_token(raw_refresh)
        session.last_used_at = now
        session.expires_at = now + REFRESH_TTL
    access = _serializer().dumps({"sa": superadmin_id, "sid": session.id, "aud": "finora_core", "typ": "access"})
    role = role_for(s, superadmin_id)
    operator = Operator(superadmin_id, username, role, session.id)
    return {
        "accessToken": access,
        "refreshToken": raw_refresh,
        "expiresIn": ACCESS_TTL_SECONDS,
        "operator": operator.to_dict(),
    }


def rotate_refresh(raw_refresh: str) -> dict[str, Any]:
    from models.core.super_admin import SuperAdmin

    digest = hash_token(raw_refresh)
    with core_session() as s:
        session = s.query(FcDesktopSession).filter_by(refresh_hash=digest).first()
        if session is None:
            reused = s.query(FcDesktopSession).filter_by(previous_hash=digest).first()
            if reused and reused.revoked_at is None:
                # A rotated-out token came back: assume theft, kill the session.
                reused.revoked_at = datetime.utcnow()
                reused.revoke_reason = "refresh_reuse"
                s.commit()
                logger.warning("finora_core refresh token reuse detected; session %s revoked", reused.id)
            raise auth_error()
        if session.revoked_at or session.expires_at < datetime.utcnow():
            raise auth_error()
        admin = s.get(SuperAdmin, session.superadmin_id)
        if admin is None:
            raise auth_error()
        tokens = issue_tokens(s, superadmin_id=admin.id, username=admin.username, session=session)
        s.commit()
        return tokens


def revoke(session_id: int, reason: str) -> None:
    with core_session() as s:
        session = s.get(FcDesktopSession, session_id)
        if session and session.revoked_at is None:
            session.revoked_at = datetime.utcnow()
            session.revoke_reason = reason
            s.commit()


def authenticate_request() -> Operator:
    from models.core.super_admin import SuperAdmin

    header = request.headers.get("Authorization") or ""
    if not header.startswith("Bearer "):
        raise auth_error("سجّل الدخول للمتابعة")
    try:
        data = _serializer().loads(header[7:].strip(), max_age=ACCESS_TTL_SECONDS)
    except SignatureExpired as exc:
        raise auth_error() from exc
    except BadSignature as exc:
        raise auth_error() from exc
    if not isinstance(data, dict) or data.get("aud") != "finora_core" or data.get("typ") != "access":
        raise auth_error()
    with core_session() as s:
        session = s.get(FcDesktopSession, int(data.get("sid") or 0))
        if session is None or session.revoked_at is not None or session.superadmin_id != data.get("sa"):
            raise auth_error()
        admin = s.get(SuperAdmin, session.superadmin_id)
        if admin is None:
            raise auth_error()
        return Operator(admin.id, admin.username, role_for(s, admin.id), session.id)


def require(permission: str | None = None) -> Callable:
    """Authenticate the bearer token and enforce a permission. Sets ``g.fc_operator``."""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            operator = authenticate_request()
            if permission and permission not in operator.permissions:
                raise permission_error()
            g.fc_operator = operator
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def current_operator() -> Operator:
    return g.fc_operator
