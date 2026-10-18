"""POS API v1 blueprint and auth guards."""
from __future__ import annotations

import logging
import os
from functools import wraps
from typing import Callable

from flask import Blueprint, g, request

from modules.pos_api.schemas import api_error
from modules.pos_api.services.tokens import decode_access_token

logger = logging.getLogger(__name__)

pos_api_v1_bp = Blueprint("pos_api_v1", __name__, url_prefix="/api/v1/pos")

_PUBLIC_ENDPOINTS = {"pos_api_v1.login"}


def _slug_from_api_key() -> str | None:
    auth = request.headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    from modules.pos_api.services.api_keys import parse_api_key

    parsed = parse_api_key(auth.split(" ", 1)[1].strip())
    if not parsed:
        return None
    return parsed[0]


def _tenant_slug_from_request() -> str | None:
    slug = (request.headers.get("X-Tenant-Slug") or request.args.get("tenant") or "").strip().lower()
    if not slug and request.method in ("POST", "PUT", "PATCH"):
        body = request.get_json(silent=True) or {}
        slug = str(body.get("tenant_slug") or body.get("tenant") or "").strip().lower()
    return slug or _slug_from_api_key()


def bind_pos_tenant():
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
        from utils.branch_migration import ensure_branch_schema
        from utils.invoice_schema_guard import ensure_invoice_schema
        from utils.order_item_schema_guard import ensure_order_item_schema
        from utils.order_stock_policy import ensure_policy_initialized
        from utils.product_schema_guard import ensure_customer_blacklist_columns, ensure_product_schema

        ensure_product_schema()
        ensure_order_item_schema()
        ensure_invoice_schema()
        ensure_customer_blacklist_columns()
        ensure_branch_schema()
        ensure_policy_initialized()
        from modules.pos_api.schema_guard import ensure_pos_api_schema

        ensure_pos_api_schema()
    except Exception:
        logger.exception("pos schema guard failed for tenant=%s", slug)
        return api_error("Tenant schema unavailable", 500, code="schema_error")
    return None


def require_pos_auth(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        auth = request.headers.get("Authorization") or ""
        if not auth.lower().startswith("bearer "):
            return api_error("Authorization Bearer required", 401, code="unauthorized")
        token = auth.split(" ", 1)[1].strip()
        from modules.pos_api.services.api_keys import find_api_key, parse_api_key

        api_key_row = find_api_key(token) if parse_api_key(token) else None
        payload = None if api_key_row else decode_access_token(token)
        if api_key_row is None and not payload:
            return api_error("Invalid or expired access token", 401, code="token_invalid")
        tenant = getattr(g, "tenant", None)
        if payload and payload.get("tenant") != tenant:
            return api_error("Token tenant mismatch", 403, code="tenant_mismatch")

        from extensions import db
        from models.employee import Employee
        from services.pos_checkout import bind_pos_employee_context
        from utils.permission_checks import employee_can

        employee_id = api_key_row.employee_id if api_key_row else int(payload["eid"])
        employee = db.session.get(Employee, employee_id)
        if employee is None or not employee.is_active:
            return api_error("Employee inactive", 403, code="user_inactive")
        if not employee_can(employee, "view_pos"):
            return api_error("ليست لديك صلاحية نقطة البيع", 403, code="forbidden")
        bind_pos_employee_context(employee)
        g.pos_employee = employee
        return view(*args, **kwargs)

    return wrapped


@pos_api_v1_bp.before_request
def _pos_api_before_request():
    err = bind_pos_tenant()
    if err is not None:
        return err
    if request.endpoint in _PUBLIC_ENDPOINTS:
        return None
    return None


from modules.pos_api.api.v1 import auth as _auth  # noqa: E402,F401
from modules.pos_api.api.v1 import catalog as _catalog  # noqa: E402,F401
from modules.pos_api.api.v1 import orders as _orders  # noqa: E402,F401
