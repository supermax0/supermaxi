"""Mobile API v1 blueprint and shared request guards."""
from __future__ import annotations

import logging
import os
from functools import wraps
from typing import Callable

from flask import Blueprint, g, request

from modules.mobile_app.schema_guard import ensure_mobile_app_schema
from modules.mobile_app.schemas import api_error
from modules.mobile_app.services.tokens import decode_access_token

logger = logging.getLogger(__name__)

mobile_api_v1_bp = Blueprint("mobile_api_v1", __name__, url_prefix="/api/mobile/v1")


def _tenant_slug_from_request() -> str | None:
    slug = (
        request.headers.get("X-Tenant-Slug")
        or request.args.get("tenant")
        or ""
    ).strip().lower()
    return slug or None


def bind_mobile_tenant() -> tuple | None:
    slug = _tenant_slug_from_request()
    if not slug:
        return api_error("X-Tenant-Slug header required", 400, code="tenant_required")

    from extensions_tenant import get_tenant_db_path, is_valid_tenant_slug

    if not is_valid_tenant_slug(slug):
        return api_error("Invalid tenant slug", 400, code="tenant_invalid")

    db_path = get_tenant_db_path(slug)
    if not os.path.exists(db_path):
        return api_error("Tenant not found", 404, code="tenant_not_found")

    g.tenant = slug
    try:
        ensure_mobile_app_schema()
    except Exception:
        logger.exception("mobile schema guard failed for tenant=%s", slug)
        return api_error("Tenant schema unavailable", 500, code="schema_error")
    return None


def require_mobile_auth(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        auth = request.headers.get("Authorization") or ""
        if not auth.lower().startswith("bearer "):
            return api_error("Authorization Bearer required", 401, code="unauthorized")
        token = auth.split(" ", 1)[1].strip()
        payload = decode_access_token(token)
        if not payload:
            return api_error("Invalid or expired access token", 401, code="token_invalid")
        tenant = getattr(g, "tenant", None)
        if payload.get("tenant") != tenant:
            return api_error("Token tenant mismatch", 403, code="tenant_mismatch")

        from extensions import db
        from modules.mobile_app.models import MobileUser, MobileUserSession

        user = db.session.get(MobileUser, int(payload["uid"]))
        if user is None or not user.is_active or user.banned_at is not None:
            return api_error("User inactive", 403, code="user_inactive")
        session_row = db.session.get(MobileUserSession, int(payload["sid"]))
        if session_row is None or not session_row.is_active:
            return api_error("Session revoked", 401, code="session_revoked")

        g.mobile_user = user
        g.mobile_session = session_row
        return view(*args, **kwargs)

    return wrapped


def optional_mobile_auth(view: Callable):
    """Attach the mobile user when a valid token exists, otherwise continue as guest.

    Public discovery endpoints use this guard so browsing never requires an
    account, while still returning personalised flags to signed-in shoppers.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        g.mobile_user = None
        g.mobile_session = None
        auth = request.headers.get("Authorization") or ""
        if not auth.lower().startswith("bearer "):
            return view(*args, **kwargs)

        payload = decode_access_token(auth.split(" ", 1)[1].strip())
        if not payload or payload.get("tenant") != getattr(g, "tenant", None):
            return view(*args, **kwargs)

        try:
            from extensions import db
            from modules.mobile_app.models import MobileUser, MobileUserSession

            user = db.session.get(MobileUser, int(payload["uid"]))
            session_row = db.session.get(MobileUserSession, int(payload["sid"]))
        except (KeyError, TypeError, ValueError):
            return view(*args, **kwargs)

        if (
            user is not None
            and user.is_active
            and user.banned_at is None
            and session_row is not None
            and session_row.is_active
        ):
            g.mobile_user = user
            g.mobile_session = session_row
        return view(*args, **kwargs)

    return wrapped


@mobile_api_v1_bp.before_request
def _mobile_before_request():
    err = bind_mobile_tenant()
    if err is not None:
        return err


# Register route modules.
from modules.mobile_app.api.v1 import auth as _auth  # noqa: E402,F401
from modules.mobile_app.api.v1 import bootstrap as _bootstrap  # noqa: E402,F401
from modules.mobile_app.api.v1 import admin_videos as _admin_videos  # noqa: E402,F401
from modules.mobile_app.api.v1 import feed as _feed  # noqa: E402,F401
from modules.mobile_app.api.v1 import media as _media  # noqa: E402,F401
from modules.mobile_app.api.v1 import comments as _comments  # noqa: E402,F401
from modules.mobile_app.api.v1 import admin_comments as _admin_comments  # noqa: E402,F401
from modules.mobile_app.api.v1 import catalog as _catalog  # noqa: E402,F401
from modules.mobile_app.api.v1 import cart_orders as _cart_orders  # noqa: E402,F401
from modules.mobile_app.api.v1 import rewards as _rewards  # noqa: E402,F401
from modules.mobile_app.api.v1 import admin_rewards as _admin_rewards  # noqa: E402,F401
from modules.mobile_app.api.v1 import ai as _ai  # noqa: E402,F401
from modules.mobile_app.api.v1 import phase8 as _phase8  # noqa: E402,F401
from modules.mobile_app.api.v1 import profile as _profile  # noqa: E402,F401
