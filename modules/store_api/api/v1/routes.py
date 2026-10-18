"""Store catalog API v1: Bearer token, read-only products."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import Blueprint, g, request

from modules.store_api.schemas import api_error, api_ok

logger = logging.getLogger(__name__)

store_api_v1_bp = Blueprint("store_api_v1", __name__, url_prefix="/api/v1/store")
store_api_v1_bp.strict_slashes = False

_lock = threading.Lock()
_buckets: dict[str, deque[float]] = defaultdict(deque)


def _client_ip() -> str:
    return (request.headers.get("X-Forwarded-For") or request.remote_addr or "0.0.0.0").split(",")[0].strip()


def _allow(namespace: str, *, limit: int = 120, window_seconds: int = 60) -> bool:
    key = f"store:{namespace}:{getattr(g, 'tenant', '')}:{_client_ip()}"
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        bucket = _buckets[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
    return True


def _bearer_token() -> str:
    auth = request.headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return ""
    return auth.split(" ", 1)[1].strip()


def bind_store_tenant():
    from modules.store_api.services.api_keys import parse_api_key

    token = _bearer_token()
    parsed = parse_api_key(token)
    if not parsed:
        return api_error("رمز API مطلوب. أرسل Authorization: Bearer sk_...", 401, code="unauthorized")
    slug = parsed[0]
    from extensions_tenant import get_tenant_db_path, is_valid_tenant_slug

    if not is_valid_tenant_slug(slug):
        return api_error("رمز API غير صالح", 401, code="token_invalid")
    if not os.path.exists(get_tenant_db_path(slug)):
        return api_error("المتجر غير موجود", 404, code="tenant_not_found")
    g.tenant = slug
    g.store_api_token = token
    try:
        from modules.installments.schema import ensure_installment_schema
        from modules.store_api.schema_guard import ensure_store_api_schema
        from utils.product_schema_guard import ensure_product_schema

        ensure_product_schema()
        ensure_installment_schema()
        ensure_store_api_schema()
    except Exception:
        logger.exception("store api schema guard failed for tenant=%s", slug)
        return api_error("تعذر تجهيز المتجر", 500, code="schema_error")
    return None


def require_store_key(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        from modules.store_api.services.api_keys import find_api_key

        row = find_api_key(getattr(g, "store_api_token", ""))
        if row is None:
            return api_error("رمز API غير صالح أو ملغى", 401, code="token_invalid")
        if not _allow("catalog"):
            return api_error("طلبات كثيرة. أعد المحاولة بعد قليل", 429, code="rate_limited")
        g.store_api_key = row
        return view(*args, **kwargs)

    return wrapped


@store_api_v1_bp.before_request
def _store_api_before_request():
    return bind_store_tenant()


def _positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


@store_api_v1_bp.get("")
@require_store_key
def store_profile():
    from modules.store_api.services.catalog import store_profile as build_profile

    from modules.store_api.services.control import PERMISSIONS

    return api_ok({"connected": True, "store": build_profile(g.tenant), "permissions": PERMISSIONS})


@store_api_v1_bp.get("/products")
@require_store_key
def products():
    from modules.store_api.services.catalog import list_public_products

    page = _positive_int(request.args.get("page"), 1)
    per_page = _positive_int(request.args.get("per_page"), 24)
    if str(request.args.get("include_hidden") or "").lower() in {"1", "true", "yes"}:
        from modules.store_api.services.control import StoreControlError, list_managed_products

        try:
            payload = list_managed_products(g.tenant, q=(request.args.get("q") or "").strip(), page=page, per_page=per_page)
        except StoreControlError as exc:
            return api_error(exc.message, exc.status, code=exc.code)
        return api_ok(payload)
    payload = list_public_products(
        g.tenant,
        q=(request.args.get("q") or "").strip(),
        category=(request.args.get("category") or "").strip(),
        sort=(request.args.get("sort") or "latest").strip(),
        availability=(request.args.get("availability") or "all").strip(),
        page=page,
        per_page=per_page,
    )
    return api_ok(payload)


@store_api_v1_bp.get("/products/<int:product_id>")
@require_store_key
def product_detail(product_id: int):
    from modules.store_api.services.catalog import get_public_product

    from modules.store_api.services.control import public_or_managed

    include_hidden = str(request.args.get("include_hidden") or "").lower() in {"1", "true", "yes"}
    item = public_or_managed(g.tenant, product_id, include_hidden=include_hidden)
    if item is None:
        return api_error("المنتج غير موجود في المتجر", 404, code="not_found")
    return api_ok({"product": item})


@store_api_v1_bp.get("/categories")
@require_store_key
def categories():
    from modules.store_api.services.catalog import list_categories

    return api_ok({"categories": list_categories(g.tenant)})


@store_api_v1_bp.post("/categories/rename")
@require_store_key
def rename_category():
    from modules.store_api.services.control import rename_category as rename_store_category

    return _control_call(rename_store_category, g.tenant, _json_body())


@store_api_v1_bp.post("/products/bulk")
@require_store_key
def bulk_products():
    from modules.store_api.services.control import bulk_visibility

    return _control_call(bulk_visibility, g.tenant, _json_body())


@store_api_v1_bp.get("/customers")
@require_store_key
def customers():
    from modules.store_api.services.control import list_customers

    return api_ok(
        list_customers(
            q=(request.args.get("q") or "").strip(),
            page=_positive_int(request.args.get("page"), 1),
            per_page=_positive_int(request.args.get("per_page"), 24),
        )
    )


@store_api_v1_bp.patch("/customers/<int:customer_id>")
@require_store_key
def update_customer(customer_id: int):
    from modules.store_api.services.control import update_customer as update_store_customer

    return _control_call(update_store_customer, customer_id, _json_body())


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {}
    return body


def _write_guard():
    if not _allow("write", limit=60):
        return api_error("طلبات كثيرة. أعد المحاولة بعد قليل", 429, code="rate_limited")
    return None


def _control_call(func, *args, status: int = 200, **kwargs):
    from modules.store_api.services.control import StoreControlError

    blocked = _write_guard()
    if blocked is not None:
        return blocked
    try:
        return api_ok(func(*args, **kwargs), status)
    except StoreControlError as exc:
        return api_error(exc.message, exc.status, code=exc.code)


@store_api_v1_bp.post("/products")
@require_store_key
def create_product():
    from modules.store_api.services.control import create_product as create_store_product

    return _control_call(create_store_product, g.tenant, _json_body(), status=201)


@store_api_v1_bp.patch("/products/<int:product_id>")
@require_store_key
def update_product(product_id: int):
    from modules.store_api.services.control import update_product as update_store_product

    return _control_call(update_store_product, g.tenant, product_id, _json_body())


@store_api_v1_bp.delete("/products/<int:product_id>")
@require_store_key
def unpublish_product(product_id: int):
    from modules.store_api.services.control import unpublish_product as hide_store_product

    return _control_call(hide_store_product, g.tenant, product_id)


@store_api_v1_bp.get("/orders")
@require_store_key
def orders():
    from modules.store_api.services.control import StoreControlError, list_orders

    try:
        return api_ok(
            list_orders(
                page=_positive_int(request.args.get("page"), 1),
                per_page=_positive_int(request.args.get("per_page"), 24),
                status=(request.args.get("status") or "").strip(),
            )
        )
    except StoreControlError as exc:
        return api_error(exc.message, exc.status, code=exc.code)


@store_api_v1_bp.get("/orders/<int:order_id>")
@require_store_key
def order_detail(order_id: int):
    from modules.store_api.services.control import get_order

    item = get_order(order_id)
    if item is None:
        return api_error("الطلب غير موجود في المتجر", 404, code="not_found")
    return api_ok({"order": item})


@store_api_v1_bp.patch("/orders/<int:order_id>")
@require_store_key
def update_order(order_id: int):
    from modules.store_api.services.control import update_order as update_store_order

    return _control_call(update_store_order, order_id, _json_body())


@store_api_v1_bp.get("/settings")
@require_store_key
def read_settings():
    from modules.store_api.services.control import read_settings as read_store_settings

    return api_ok({"settings": read_store_settings()})


@store_api_v1_bp.patch("/settings")
@require_store_key
def update_settings():
    from modules.store_api.services.control import update_settings as update_store_settings

    return _control_call(update_store_settings, _json_body())
