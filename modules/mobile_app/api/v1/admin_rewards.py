"""Admin endpoints for coupons / campaigns / points (Phase 6)."""
from __future__ import annotations

from functools import wraps

from flask import g, request

from modules.mobile_app.api.v1.routes import mobile_api_v1_bp
from modules.mobile_app.schemas import api_error, api_ok, require_json_fields
from modules.mobile_app.services import discounts as discount_service
from modules.mobile_app.services import rewards as reward_service
from modules.mobile_app.services.discounts import DiscountError
from modules.mobile_app.services.rewards import RewardError
from utils.permission_checks import check_permission, get_current_employee


def require_staff_rewards_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        employee = get_current_employee()
        if employee is None:
            from flask import current_app

            if current_app.config.get("TESTING") and request.headers.get("X-Test-Staff-Id"):
                from extensions import db
                from models.employee import Employee

                employee = db.session.get(Employee, int(request.headers["X-Test-Staff-Id"]))
                if employee:
                    g.mobile_staff = employee
                    return view(*args, **kwargs)
            return api_error("Staff login required", 401, code="staff_required")
        role = (employee.role or "").strip().lower()
        if role != "admin" and not (
            check_permission("mobile_app.manage_rewards")
            or check_permission("mobile_app.manage_coupons")
            or check_permission("mobile_app.adjust_points")
        ):
            return api_error("Permission denied", 403, code="forbidden")
        g.mobile_staff = employee
        return view(*args, **kwargs)

    return wrapped


@mobile_api_v1_bp.post("/admin/coupons")
@require_staff_rewards_admin
def admin_create_coupon():
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "code", "value")
    if missing:
        return api_error(missing, 400, code="validation_error")
    try:
        coupon = discount_service.create_coupon(
            code=str(body.get("code")),
            name=str(body.get("name") or ""),
            discount_type=str(body.get("discount_type") or "percent"),
            value=int(body.get("value") or 0),
            min_subtotal=int(body.get("min_subtotal") or 0),
            max_discount=(
                int(body["max_discount"]) if body.get("max_discount") is not None else None
            ),
            max_uses=int(body["max_uses"]) if body.get("max_uses") is not None else None,
            max_uses_per_user=int(body.get("max_uses_per_user") or 1),
            campaign_id=int(body["campaign_id"]) if body.get("campaign_id") else None,
        )
        return api_ok(
            {
                "coupon": {
                    "id": coupon.id,
                    "code": coupon.code,
                    "discount_type": coupon.discount_type,
                    "value": coupon.value,
                }
            },
            status=201,
        )
    except (DiscountError, TypeError, ValueError) as exc:
        msg = getattr(exc, "message", str(exc))
        code = getattr(exc, "code", "validation_error")
        return api_error(msg, 400, code=code)


@mobile_api_v1_bp.post("/admin/campaigns")
@require_staff_rewards_admin
def admin_create_campaign():
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "name")
    if missing:
        return api_error(missing, 400, code="validation_error")
    from extensions import db
    from modules.mobile_app.models import MobileCampaign

    campaign = MobileCampaign(
        name=str(body.get("name")).strip(),
        slug=(str(body.get("slug") or "").strip() or None),
        description=str(body.get("description") or ""),
        bonus_multiplier=float(body.get("bonus_multiplier") or 1.0),
        priority=int(body.get("priority") or 0),
        is_active=True,
    )
    db.session.add(campaign)
    db.session.commit()
    return api_ok(
        {
            "campaign": {
                "id": campaign.id,
                "name": campaign.name,
                "bonus_multiplier": campaign.bonus_multiplier,
            }
        },
        status=201,
    )


@mobile_api_v1_bp.post("/admin/rewards/adjust")
@require_staff_rewards_admin
def admin_adjust_points():
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "user_id", "points", "direction")
    if missing:
        return api_error(missing, 400, code="validation_error")
    try:
        result = reward_service.adjust_points(
            user_id=int(body["user_id"]),
            points=int(body["points"]),
            direction=str(body.get("direction") or "credit"),
            description=str(body.get("description") or "تعديل يدوي"),
            staff_id=getattr(g.mobile_staff, "id", None),
        )
        return api_ok(result)
    except (RewardError, TypeError, ValueError) as exc:
        msg = getattr(exc, "message", str(exc))
        code = getattr(exc, "code", "validation_error")
        return api_error(msg, 400, code=code)
