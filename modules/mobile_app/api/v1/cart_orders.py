"""Cart, checkout, and orders API (Phase 5)."""
from __future__ import annotations

from flask import g, request

from modules.mobile_app.api.v1.routes import mobile_api_v1_bp, require_mobile_auth
from modules.mobile_app.schemas import api_error, api_ok
from modules.mobile_app.services import cart_checkout as cart_service
from modules.mobile_app.services.cart_checkout import CartError
from modules.mobile_app.services.rate_limit import enforce_rate_limit


@mobile_api_v1_bp.get("/cart")
@require_mobile_auth
def cart_get():
    return api_ok(cart_service.get_cart(g.mobile_user.id))


@mobile_api_v1_bp.post("/cart/items")
@require_mobile_auth
def cart_add_item():
    body = request.get_json(silent=True) or {}
    try:
        product_id = int(body.get("product_id") or 0)
        quantity = int(body.get("quantity") or 1)
        video_id = body.get("video_id")
        video_id = int(video_id) if video_id not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        return api_error("بيانات غير صالحة", 400, code="validation_error")
    if product_id <= 0:
        return api_error("product_id مطلوب", 400, code="validation_error")
    try:
        data = cart_service.add_item(
            user_id=g.mobile_user.id,
            product_id=product_id,
            quantity=quantity,
            video_id=video_id,
        )
        return api_ok(data)
    except CartError as exc:
        return api_error(exc.message, 400, code=exc.code)


@mobile_api_v1_bp.patch("/cart/items/<int:item_id>")
@require_mobile_auth
def cart_update_item(item_id: int):
    body = request.get_json(silent=True) or {}
    try:
        quantity = int(body.get("quantity"))
    except (TypeError, ValueError):
        return api_error("quantity مطلوب", 400, code="validation_error")
    try:
        return api_ok(
            cart_service.update_item(
                user_id=g.mobile_user.id, item_id=item_id, quantity=quantity
            )
        )
    except CartError as exc:
        status = 404 if exc.code == "not_found" else 400
        return api_error(exc.message, status, code=exc.code)


@mobile_api_v1_bp.delete("/cart/items/<int:item_id>")
@require_mobile_auth
def cart_remove_item(item_id: int):
    try:
        return api_ok(cart_service.remove_item(user_id=g.mobile_user.id, item_id=item_id))
    except CartError as exc:
        status = 404 if exc.code == "not_found" else 400
        return api_error(exc.message, status, code=exc.code)


@mobile_api_v1_bp.delete("/cart")
@require_mobile_auth
def cart_clear():
    return api_ok(cart_service.clear_cart(g.mobile_user.id))


@mobile_api_v1_bp.post("/cart/validate")
@require_mobile_auth
def cart_validate():
    ok, message, data = cart_service.validate_cart(g.mobile_user.id)
    return api_ok({**data, "valid": ok, "message": message})


@mobile_api_v1_bp.post("/cart/apply-coupon")
@require_mobile_auth
def cart_apply_coupon():
    body = request.get_json(silent=True) or {}
    try:
        return api_ok(cart_service.apply_coupon(g.mobile_user.id, str(body.get("code") or "")))
    except CartError as exc:
        return api_error(exc.message, 400, code=exc.code)


@mobile_api_v1_bp.delete("/cart/coupon")
@require_mobile_auth
def cart_remove_coupon():
    return api_ok(cart_service.remove_coupon(g.mobile_user.id))


@mobile_api_v1_bp.post("/cart/apply-points")
@require_mobile_auth
def cart_apply_points():
    body = request.get_json(silent=True) or {}
    try:
        points = int(body.get("points") or 0)
    except (TypeError, ValueError):
        return api_error("points غير صالح", 400, code="validation_error")
    try:
        return api_ok(cart_service.apply_points(g.mobile_user.id, points))
    except CartError as exc:
        return api_error(exc.message, 400, code=exc.code)


@mobile_api_v1_bp.delete("/cart/points")
@require_mobile_auth
def cart_remove_points():
    return api_ok(cart_service.remove_points(g.mobile_user.id))


@mobile_api_v1_bp.post("/checkout/preview")
@require_mobile_auth
def checkout_preview():
    body = request.get_json(silent=True) or {}
    shipping = int(body.get("shipping_fee") or 0)
    return api_ok(cart_service.checkout_preview(g.mobile_user.id, shipping_fee=shipping))


@mobile_api_v1_bp.post("/orders")
@require_mobile_auth
def create_order():
    limited = enforce_rate_limit("create_order", limit=10, window_seconds=60)
    if limited is not None:
        return limited
    body = request.get_json(silent=True) or {}
    video_id = body.get("video_id")
    try:
        video_id = int(video_id) if video_id not in (None, "", 0, "0") else None
        shipping = int(body.get("shipping_fee") or 0)
    except (TypeError, ValueError):
        return api_error("بيانات غير صالحة", 400, code="validation_error")
    try:
        result = cart_service.place_order(
            user_id=g.mobile_user.id,
            customer_name=str(body.get("customer_name") or ""),
            phone=str(body.get("phone") or g.mobile_user.phone or ""),
            city=str(body.get("city") or ""),
            address=str(body.get("address") or ""),
            notes=str(body.get("notes") or ""),
            shipping_fee=shipping,
            video_id=video_id,
        )
        return api_ok(result, status=201)
    except CartError as exc:
        return api_error(exc.message, 400, code=exc.code)


@mobile_api_v1_bp.get("/orders")
@require_mobile_auth
def list_orders():
    limit = min(100, max(1, int(request.args.get("limit") or 30)))
    return api_ok({"items": cart_service.list_orders(g.mobile_user.id, limit=limit)})


@mobile_api_v1_bp.get("/orders/<int:order_id>")
@require_mobile_auth
def get_order(order_id: int):
    order = cart_service.get_order(g.mobile_user.id, order_id)
    if order is None:
        return api_error("الطلب غير موجود", 404, code="not_found")
    return api_ok({"order": order})


@mobile_api_v1_bp.post("/orders/<int:order_id>/cancel")
@require_mobile_auth
def cancel_order(order_id: int):
    try:
        return api_ok({"order": cart_service.cancel_order(g.mobile_user.id, order_id)})
    except CartError as exc:
        status = 404 if exc.code == "not_found" else 400
        return api_error(exc.message, status, code=exc.code)
