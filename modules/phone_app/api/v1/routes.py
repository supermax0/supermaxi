"""Phone API v1 blueprint and auth guards."""

from __future__ import annotations

import logging
import os
from functools import wraps
from typing import Callable

from flask import Blueprint, g, request

from modules.phone_app.schema_guard import ensure_phone_app_schema
from modules.phone_app.schemas import api_error
from modules.phone_app.services.tokens import decode_access_token

logger = logging.getLogger(__name__)

phone_api_v1_bp = Blueprint("phone_api_v1", __name__, url_prefix="/api/phone/v1")


def _tenant_slug_from_request() -> str | None:
    slug = (
        request.headers.get("X-Tenant-Slug")
        or request.args.get("tenant")
        or ""
    ).strip().lower()
    if not slug and request.method in ("POST", "PUT", "PATCH"):
        body = request.get_json(silent=True) or {}
        slug = str(body.get("tenant_slug") or body.get("tenant") or "").strip().lower()
    return slug or None


def bind_phone_tenant() -> tuple | None:
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
        ensure_phone_app_schema()
    except Exception:
        logger.exception("phone schema guard failed for tenant=%s", slug)
        return api_error("Tenant schema unavailable", 500, code="schema_error")
    return None


def require_phone_auth(view: Callable):
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
        from models.employee import Employee
        from modules.phone_app.models import PhoneAppDevice, PhoneRefreshToken

        employee = db.session.get(Employee, int(payload["eid"]))
        if employee is None or not employee.is_active:
            return api_error("Employee inactive", 403, code="user_inactive")
        session_row = db.session.get(PhoneRefreshToken, int(payload["sid"]))
        if session_row is None or session_row.revoked_at is not None:
            return api_error("Session revoked", 401, code="session_revoked")

        # Device must belong to employee and not be revoked (when registered).
        device = PhoneAppDevice.query.filter_by(
            employee_id=employee.id, device_uuid=session_row.device_id
        ).first()
        if device is not None and (device.revoked_at is not None or not device.is_active):
            return api_error("Device revoked", 403, code="device_revoked")

        # Touch last_seen
        if device is not None:
            from datetime import datetime

            device.last_seen_at = datetime.utcnow()

        g.phone_employee = employee
        g.phone_session = session_row
        g.phone_device = device
        return view(*args, **kwargs)

    return wrapped


@phone_api_v1_bp.before_request
def _phone_before_request():
    err = bind_phone_tenant()
    if err is not None:
        return err


from modules.phone_app.api.v1 import auth as _auth  # noqa: E402,F401
from modules.phone_app.api.v1 import bootstrap as _bootstrap  # noqa: E402,F401
from modules.phone_app.api.v1 import customers as _customers  # noqa: E402,F401
from modules.phone_app.api.v1 import calls as _calls  # noqa: E402,F401
from modules.phone_app.api.v1 import notes as _notes  # noqa: E402,F401
from modules.phone_app.api.v1 import tasks as _tasks  # noqa: E402,F401
from modules.phone_app.api.v1 import orders as _orders  # noqa: E402,F401
from modules.phone_app.api.v1 import products as _products  # noqa: E402,F401
from modules.phone_app.api.v1 import devices as _devices  # noqa: E402,F401
from modules.phone_app.api.v1 import search as _search  # noqa: E402,F401
from modules.phone_app.api.v1 import recordings as _recordings  # noqa: E402,F401
