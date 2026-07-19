"""Rewards and coupons API (Phase 6)."""
from __future__ import annotations

from flask import g, request

from modules.mobile_app.api.v1.routes import mobile_api_v1_bp, require_mobile_auth
from modules.mobile_app.schemas import api_error, api_ok
from modules.mobile_app.services import discounts as discount_service
from modules.mobile_app.services import rewards as reward_service
from modules.mobile_app.services.discounts import DiscountError
from modules.mobile_app.services.feature_flags import is_flag_enabled
from modules.mobile_app.services.rewards import RewardError


@mobile_api_v1_bp.get("/rewards")
@require_mobile_auth
def rewards_summary():
    if not is_flag_enabled("rewards_enabled", True):
        return api_error("المكافآت غير مفعّلة", 403, code="rewards_disabled")
    reward_service.grant_welcome_bonus(g.mobile_user.id)
    return api_ok(
        {
            "rewards": reward_service.get_rewards_summary(g.mobile_user.id),
            "tiers": reward_service.list_tiers(),
            "campaigns": discount_service.list_active_campaigns(),
        }
    )


@mobile_api_v1_bp.get("/rewards/history")
@require_mobile_auth
def rewards_history():
    if not is_flag_enabled("rewards_enabled", True):
        return api_error("المكافآت غير مفعّلة", 403, code="rewards_disabled")
    limit = min(100, max(1, int(request.args.get("limit") or 50)))
    return api_ok({"items": reward_service.history(g.mobile_user.id, limit=limit)})


@mobile_api_v1_bp.get("/rewards/rules")
@require_mobile_auth
def rewards_rules():
    return api_ok({"items": reward_service.list_rules()})


@mobile_api_v1_bp.get("/rewards/available-redemptions")
@require_mobile_auth
def rewards_redemptions():
    if not is_flag_enabled("rewards_enabled", True):
        return api_error("المكافآت غير مفعّلة", 403, code="rewards_disabled")
    return api_ok(
        {"items": reward_service.available_redemptions(g.mobile_user.id)}
    )


@mobile_api_v1_bp.post("/rewards/redeem")
@require_mobile_auth
def rewards_redeem():
    """Apply points onto the cart (checkout redemption)."""
    if not is_flag_enabled("rewards_enabled", True):
        return api_error("المكافآت غير مفعّلة", 403, code="rewards_disabled")
    from modules.mobile_app.services import cart_checkout as cart_service
    from modules.mobile_app.services.cart_checkout import CartError

    body = request.get_json(silent=True) or {}
    try:
        points = int(body.get("points") or 0)
    except (TypeError, ValueError):
        return api_error("points غير صالح", 400, code="validation_error")
    try:
        return api_ok(cart_service.apply_points(g.mobile_user.id, points))
    except (CartError, RewardError) as exc:
        return api_error(exc.message, 400, code=exc.code)


@mobile_api_v1_bp.get("/coupons")
@require_mobile_auth
def coupons_list():
    if not is_flag_enabled("coupons_enabled", True):
        return api_error("الكوبونات غير مفعّلة", 403, code="coupons_disabled")
    return api_ok({"items": discount_service.list_public_coupons()})


@mobile_api_v1_bp.get("/discounts")
@require_mobile_auth
def discounts_list():
    return api_ok({"items": discount_service.list_active_discounts()})


@mobile_api_v1_bp.post("/coupons/validate")
@require_mobile_auth
def coupons_validate():
    if not is_flag_enabled("coupons_enabled", True):
        return api_error("الكوبونات غير مفعّلة", 403, code="coupons_disabled")
    from modules.mobile_app.services import cart_checkout as cart_service

    body = request.get_json(silent=True) or {}
    code = str(body.get("code") or "")
    cart = cart_service.get_cart(g.mobile_user.id)
    try:
        coupon, discount = discount_service.validate_coupon(
            code, user_id=g.mobile_user.id, subtotal=int(cart.get("subtotal") or 0)
        )
        return api_ok(
            {
                "valid": True,
                "code": coupon.code,
                "discount_amount": discount,
                "discount_type": coupon.discount_type,
                "value": coupon.value,
            }
        )
    except DiscountError as exc:
        return api_error(exc.message, 400, code=exc.code)
