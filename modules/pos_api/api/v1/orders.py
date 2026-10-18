"""POS order search, details, payment, cancel, and return."""
from __future__ import annotations

from flask import g, request

from modules.pos_api.api.v1.routes import pos_api_v1_bp, require_pos_auth
from modules.pos_api.schemas import api_ok, checkout_error_response
from modules.pos_api.services.rate_limit import enforce_rate_limit
from services.pos_catalog import serialize_pos_order
from services.pos_checkout import PosCheckoutError
from services.pos_order_control import (
    execute_pos_cancel,
    execute_pos_payment,
    execute_pos_return,
    get_pos_order,
    preview_pos_cancel,
    preview_pos_payment,
    preview_pos_return,
    search_pos_orders,
)


def _employee():
    return g.pos_employee


@pos_api_v1_bp.get("/orders/search")
@require_pos_auth
def orders_search():
    try:
        limit = int(request.args.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    try:
        rows = search_pos_orders(
            _employee(),
            customer=request.args.get("customer"),
            product=request.args.get("product"),
            province=request.args.get("province"),
            limit=limit,
        )
        return api_ok({"orders": rows})
    except PosCheckoutError as exc:
        return checkout_error_response(exc)


@pos_api_v1_bp.get("/orders/<int:order_id>")
@require_pos_auth
def orders_detail(order_id: int):
    try:
        order = get_pos_order(_employee(), order_id)
        return api_ok({"order": serialize_pos_order(order, include_items=True)})
    except PosCheckoutError as exc:
        return checkout_error_response(exc)


@pos_api_v1_bp.post("/orders/<int:order_id>/payments/preview")
@require_pos_auth
def payments_preview(order_id: int):
    body = request.get_json(silent=True) or {}
    try:
        payment = preview_pos_payment(
            _employee(),
            order_id,
            mode=str(body.get("mode") or "full"),
            amount=body.get("amount"),
        )
        return api_ok({"payment": payment})
    except PosCheckoutError as exc:
        return checkout_error_response(exc)


@pos_api_v1_bp.post("/orders/<int:order_id>/payments")
@require_pos_auth
def payments_execute(order_id: int):
    limited = enforce_rate_limit("pay_order", limit=20, window_seconds=60)
    if limited is not None:
        return limited
    body = request.get_json(silent=True) or {}
    try:
        payment = execute_pos_payment(
            _employee(),
            order_id,
            mode=str(body.get("mode") or "full"),
            amount=body.get("amount"),
            method=str(body.get("method") or "cash"),
        )
        return api_ok({"payment": payment})
    except PosCheckoutError as exc:
        return checkout_error_response(exc)


@pos_api_v1_bp.post("/orders/<int:order_id>/cancel/preview")
@require_pos_auth
def cancel_preview(order_id: int):
    try:
        return api_ok({"cancel": preview_pos_cancel(_employee(), order_id)})
    except PosCheckoutError as exc:
        return checkout_error_response(exc)


@pos_api_v1_bp.post("/orders/<int:order_id>/cancel")
@require_pos_auth
def cancel_execute(order_id: int):
    body = request.get_json(silent=True) or {}
    try:
        result = execute_pos_cancel(_employee(), order_id, reason=body.get("reason"))
        return api_ok(result)
    except PosCheckoutError as exc:
        return checkout_error_response(exc)


@pos_api_v1_bp.post("/orders/<int:order_id>/return/preview")
@require_pos_auth
def return_preview(order_id: int):
    try:
        return api_ok({"return": preview_pos_return(_employee(), order_id)})
    except PosCheckoutError as exc:
        return checkout_error_response(exc)


@pos_api_v1_bp.post("/orders/<int:order_id>/return")
@require_pos_auth
def return_execute(order_id: int):
    body = request.get_json(silent=True) or {}
    try:
        result = execute_pos_return(
            _employee(),
            order_id,
            reason=body.get("reason"),
            barcode=body.get("barcode"),
        )
        return api_ok(result)
    except PosCheckoutError as exc:
        return checkout_error_response(exc)
