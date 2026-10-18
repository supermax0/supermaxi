"""POS catalog + checkout endpoints."""
from __future__ import annotations

from flask import g, request

from modules.pos_api.api.v1.routes import pos_api_v1_bp, require_pos_auth
from modules.pos_api.schemas import api_ok, checkout_error_response
from modules.pos_api.services.rate_limit import enforce_rate_limit
from services.pos_catalog import recent_pos_orders, search_pos_customers, search_pos_products
from services.pos_checkout import PosCheckoutError, create_pos_order, preview_pos_order, resolve_checkout_branch


def _employee():
    return g.pos_employee


def _branch_id(body=None):
    raw = None
    if isinstance(body, dict):
        raw = body.get("branch_id")
    if raw in (None, "", 0, "0"):
        raw = request.args.get("branch_id")
    return raw


@pos_api_v1_bp.get("/customers")
@require_pos_auth
def customers_search():
    q = (request.args.get("q") or "").strip()
    try:
        branch_id = resolve_checkout_branch(_employee(), _branch_id(), allow_admin_any_branch=True)
        rows = search_pos_customers(_employee(), q, branch_id=branch_id)
        return api_ok({"customers": rows})
    except PosCheckoutError as exc:
        return checkout_error_response(exc)


@pos_api_v1_bp.get("/products")
@require_pos_auth
def products_search():
    q = (request.args.get("q") or "").strip()
    try:
        branch_id = resolve_checkout_branch(_employee(), _branch_id(), allow_admin_any_branch=True)
        rows = search_pos_products(_employee(), q, branch_id=branch_id)
        return api_ok({"products": rows})
    except PosCheckoutError as exc:
        return checkout_error_response(exc)


@pos_api_v1_bp.post("/orders/preview")
@require_pos_auth
def orders_preview():
    body = request.get_json(silent=True) or {}
    try:
        preview = preview_pos_order(
            employee=_employee(),
            customer_id=body.get("customer_id"),
            items=body.get("items") or [],
            branch_id=body.get("branch_id"),
            note=body.get("note"),
            source="pos_api",
            raw_data=body,
        )
        return api_ok({"preview": preview})
    except PosCheckoutError as exc:
        return checkout_error_response(exc)


@pos_api_v1_bp.post("/orders")
@require_pos_auth
def orders_create():
    limited = enforce_rate_limit("create_order", limit=20, window_seconds=60)
    if limited is not None:
        return limited
    body = request.get_json(silent=True) or {}
    token = (
        request.headers.get("Idempotency-Key")
        or body.get("idempotency_key")
        or body.get("submission_token")
        or ""
    ).strip()
    try:
        created = create_pos_order(
            employee=_employee(),
            customer_id=body.get("customer_id"),
            items=body.get("items") or [],
            branch_id=body.get("branch_id"),
            note=body.get("note"),
            scheduled_date=body.get("scheduled_date"),
            page_id=body.get("page_id"),
            discount_amount=body.get("discount_amount"),
            order_id=body.get("order_id"),
            submission_token=token,
            source="pos_api",
            raw_data=body,
        )
        payload = {
            "order_id": created.get("order_id") or created.get("invoice_id"),
            "invoice_id": created.get("invoice_id"),
            "total": created.get("total"),
            "stock_locked": created.get("stock_locked"),
            "stock_lock_reason": created.get("stock_lock_reason"),
            "duplicate": bool(created.get("duplicate")),
        }
        if created.get("installment_lifecycle"):
            payload["installment_lifecycle"] = created["installment_lifecycle"]
        return api_ok(payload)
    except PosCheckoutError as exc:
        return checkout_error_response(exc)


@pos_api_v1_bp.get("/orders/recent")
@require_pos_auth
def orders_recent():
    try:
        limit = int(request.args.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    return api_ok({"orders": recent_pos_orders(_employee(), limit=limit)})
