"""Coupon / discount engine for mobile cart (Phase 6)."""
from __future__ import annotations

from datetime import datetime

from extensions import db
from modules.mobile_app.models import (
    MobileCampaign,
    MobileCoupon,
    MobileCouponRedemption,
    MobileDiscount,
)


class DiscountError(Exception):
    def __init__(self, message: str, code: str = "discount_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def _in_window(starts_at, ends_at, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    if starts_at and starts_at > now:
        return False
    if ends_at and ends_at < now:
        return False
    return True


def compute_coupon_discount(coupon: MobileCoupon, subtotal: int) -> int:
    subtotal = max(0, int(subtotal))
    if subtotal < int(coupon.min_subtotal or 0):
        return 0
    dtype = (coupon.discount_type or "percent").lower()
    value = max(0, int(coupon.value or 0))
    if dtype == "fixed":
        amount = min(value, subtotal)
    else:
        amount = int(subtotal * value / 100)
    if coupon.max_discount is not None:
        amount = min(amount, int(coupon.max_discount))
    return max(0, amount)


def validate_coupon(code: str, *, user_id: int, subtotal: int) -> tuple[MobileCoupon, int]:
    normalized = str(code or "").strip().upper()
    if not normalized:
        raise DiscountError("أدخل رمز الكوبون", "coupon_required")
    coupon = MobileCoupon.query.filter_by(code=normalized).first()
    if coupon is None or not coupon.is_active:
        raise DiscountError("الكوبون غير صالح", "coupon_invalid")
    if not _in_window(coupon.starts_at, coupon.ends_at):
        raise DiscountError("الكوبون منتهي أو لم يبدأ بعد", "coupon_expired")
    if coupon.max_uses is not None:
        used = MobileCouponRedemption.query.filter_by(coupon_id=coupon.id).count()
        if used >= int(coupon.max_uses):
            raise DiscountError("تم استنفاد استخدامات الكوبون", "coupon_exhausted")
    per_user = int(coupon.max_uses_per_user or 1)
    used_by_user = MobileCouponRedemption.query.filter_by(
        coupon_id=coupon.id, user_id=user_id
    ).count()
    if used_by_user >= per_user:
        raise DiscountError("استخدمت هذا الكوبون مسبقاً", "coupon_user_limit")
    if subtotal < int(coupon.min_subtotal or 0):
        raise DiscountError(
            f"الحد الأدنى للسلة {coupon.min_subtotal} د.ع",
            "coupon_min_subtotal",
        )
    discount = compute_coupon_discount(coupon, subtotal)
    if discount <= 0:
        raise DiscountError("الكوبون لا يطبّق على هذه السلة", "coupon_no_effect")
    return coupon, discount


def record_coupon_redemption(
    *,
    coupon_id: int,
    user_id: int,
    invoice_id: int,
    discount_amount: int,
) -> MobileCouponRedemption:
    row = MobileCouponRedemption(
        coupon_id=coupon_id,
        user_id=user_id,
        invoice_id=invoice_id,
        discount_amount=discount_amount,
    )
    db.session.add(row)
    db.session.flush()
    return row


def list_public_coupons() -> list[dict]:
    now = datetime.utcnow()
    rows = MobileCoupon.query.filter_by(is_active=True).order_by(MobileCoupon.id.desc()).all()
    out = []
    for c in rows:
        if not _in_window(c.starts_at, c.ends_at, now):
            continue
        out.append(
            {
                "id": c.id,
                "code": c.code,
                "name": c.name or c.code,
                "discount_type": c.discount_type,
                "value": c.value,
                "min_subtotal": c.min_subtotal,
                "max_discount": c.max_discount,
                "ends_at": c.ends_at.isoformat() if c.ends_at else None,
            }
        )
    return out


def list_active_discounts() -> list[dict]:
    now = datetime.utcnow()
    rows = MobileDiscount.query.filter_by(is_active=True).all()
    out = []
    for d in rows:
        if not _in_window(d.starts_at, d.ends_at, now):
            continue
        out.append(
            {
                "id": d.id,
                "name": d.name,
                "discount_type": d.discount_type,
                "value": d.value,
                "min_subtotal": d.min_subtotal,
                "category": d.category,
                "product_id": d.product_id,
                "video_id": d.video_id,
                "campaign_id": d.campaign_id,
            }
        )
    return out


def list_active_campaigns() -> list[dict]:
    now = datetime.utcnow()
    rows = (
        MobileCampaign.query.filter_by(is_active=True)
        .order_by(MobileCampaign.priority.desc(), MobileCampaign.id.desc())
        .all()
    )
    out = []
    for c in rows:
        if not _in_window(c.starts_at, c.ends_at, now):
            continue
        out.append(
            {
                "id": c.id,
                "name": c.name,
                "slug": c.slug,
                "description": c.description or "",
                "bonus_multiplier": c.bonus_multiplier,
                "starts_at": c.starts_at.isoformat() if c.starts_at else None,
                "ends_at": c.ends_at.isoformat() if c.ends_at else None,
            }
        )
    return out


def create_coupon(
    *,
    code: str,
    name: str = "",
    discount_type: str = "percent",
    value: int = 0,
    min_subtotal: int = 0,
    max_discount: int | None = None,
    max_uses: int | None = None,
    max_uses_per_user: int = 1,
    campaign_id: int | None = None,
) -> MobileCoupon:
    normalized = str(code or "").strip().upper()
    if not normalized:
        raise DiscountError("رمز الكوبون مطلوب", "coupon_required")
    if MobileCoupon.query.filter_by(code=normalized).first():
        raise DiscountError("رمز الكوبون مستخدم", "coupon_exists")
    coupon = MobileCoupon(
        code=normalized,
        name=name or normalized,
        discount_type=discount_type if discount_type in {"percent", "fixed"} else "percent",
        value=max(0, int(value)),
        min_subtotal=max(0, int(min_subtotal)),
        max_discount=max_discount,
        max_uses=max_uses,
        max_uses_per_user=max(1, int(max_uses_per_user)),
        campaign_id=campaign_id,
        is_active=True,
    )
    db.session.add(coupon)
    db.session.commit()
    return coupon
