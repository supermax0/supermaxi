"""Profile, addresses, and account lifecycle for mobile shoppers."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func

from extensions import db
from models.customer import Customer
from models.invoice import Invoice
from modules.mobile_app.models import (
    MobileAnalyticsEvent,
    MobileFavorite,
    MobileOrderAttribution,
    MobileUser,
    MobileUserAddress,
    MobileVideo,
    MobileVideoLike,
    MobileVideoSave,
)
from modules.mobile_app.services import catalog as catalog_service
from modules.mobile_app.services import rewards as reward_service
from modules.mobile_app.services.auth import logout_all_sessions


class ProfileError(Exception):
    def __init__(self, message: str, code: str = "profile_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def get_profile(user_id: int) -> dict:
    user = db.session.get(MobileUser, user_id)
    if user is None:
        raise ProfileError("المستخدم غير موجود", "not_found")
    rewards = reward_service.get_rewards_summary(user_id)
    customer = db.session.get(Customer, user.customer_id) if user.customer_id else None
    return {
        "user": user.to_public_dict(),
        "rewards": rewards,
        "customer": {
            "id": customer.id if customer else None,
            "name": (customer.name if customer else user.name) or "",
            "phone": (customer.phone if customer else user.phone) or "",
            "city": (customer.city if customer else "") or "",
            "address": (customer.address if customer else "") or "",
        },
        "insights": _customer_insights(user, customer),
    }


def _customer_insights(user: MobileUser, customer: Customer | None) -> dict:
    """Return shopper-owned aggregates useful for personalization and account UX."""
    from models.product import Product
    from modules.mobile_app.services import catalog as catalog_service

    if user.customer_id:
        orders_count, total_spent = (
            db.session.query(
                func.count(Invoice.id),
                func.coalesce(func.sum(Invoice.total), 0),
            )
            .filter(Invoice.customer_id == user.customer_id)
            .one()
        )
    else:
        orders_count, total_spent = (
            db.session.query(
                func.count(Invoice.id),
                func.coalesce(func.sum(Invoice.total), 0),
            )
            .join(
                MobileOrderAttribution,
                MobileOrderAttribution.invoice_id == Invoice.id,
            )
            .filter(MobileOrderAttribution.user_id == user.id)
            .one()
        )

    favorites_count = MobileFavorite.query.filter_by(user_id=user.id).count()
    favorite_rows = (
        MobileFavorite.query.filter_by(user_id=user.id)
        .order_by(MobileFavorite.id.desc())
        .limit(50)
        .all()
    )
    favorite_product_ids = [row.product_id for row in favorite_rows]
    products = (
        Product.query.filter(Product.id.in_(favorite_product_ids)).all()
        if favorite_product_ids
        else []
    )
    category_counts: dict[str, int] = {}
    for product in products:
        category = str(
            catalog_service.to_mobile_product(product).get("category") or ""
        ).strip()
        if category:
            category_counts[category] = category_counts.get(category, 0) + 1

    video_views = MobileAnalyticsEvent.query.filter_by(
        user_id=user.id, event_name="video_view"
    ).count()
    addresses_count = MobileUserAddress.query.filter_by(user_id=user.id).count()
    completion_fields = [
        bool((user.name or "").strip()),
        bool((user.email or "").strip()),
        bool((getattr(customer, "city", "") or "").strip()),
        bool((getattr(customer, "address", "") or "").strip()),
        addresses_count > 0,
    ]
    return {
        "orders_count": int(orders_count or 0),
        "total_spent": max(0, int(total_spent or 0)),
        "favorites_count": favorites_count,
        "video_views": video_views,
        "addresses_count": addresses_count,
        "profile_completion": round(
            (sum(1 for value in completion_fields if value) / len(completion_fields))
            * 100
        ),
        "member_since": user.created_at.isoformat() if user.created_at else None,
        "preferred_categories": [
            category
            for category, _ in sorted(
                category_counts.items(), key=lambda pair: (-pair[1], pair[0])
            )[:5]
        ],
    }


def update_profile(user_id: int, payload: dict) -> dict:
    user = db.session.get(MobileUser, user_id)
    if user is None:
        raise ProfileError("المستخدم غير موجود", "not_found")
    if "name" in payload and str(payload.get("name") or "").strip():
        user.name = str(payload["name"]).strip()[:150]
    if "email" in payload:
        email = str(payload.get("email") or "").strip()
        user.email = email[:200] or None
    if user.customer_id:
        customer = db.session.get(Customer, user.customer_id)
        if customer:
            if "name" in payload and user.name:
                customer.name = user.name
            if "city" in payload:
                customer.city = str(payload.get("city") or "").strip()[:100] or None
            if "address" in payload:
                customer.address = str(payload.get("address") or "").strip()[:255] or None
    user.updated_at = datetime.utcnow()
    db.session.commit()
    return get_profile(user_id)


def list_addresses(user_id: int) -> list[dict]:
    rows = (
        MobileUserAddress.query.filter_by(user_id=user_id)
        .order_by(MobileUserAddress.is_default.desc(), MobileUserAddress.id.desc())
        .all()
    )
    return [_addr_dict(r) for r in rows]


def create_address(user_id: int, payload: dict) -> dict:
    city = str(payload.get("city") or "").strip()
    address = str(payload.get("address") or "").strip()
    if len(city) < 2 or len(address) < 5:
        raise ProfileError("المدينة والعنوان مطلوبان", "validation_error")
    make_default = bool(payload.get("is_default"))
    if make_default:
        MobileUserAddress.query.filter_by(user_id=user_id).update({"is_default": False})
    elif not MobileUserAddress.query.filter_by(user_id=user_id).count():
        make_default = True
    user = db.session.get(MobileUser, user_id)
    row = MobileUserAddress(
        user_id=user_id,
        label=str(payload.get("label") or "المنزل").strip()[:80] or "المنزل",
        full_name=str(payload.get("full_name") or (user.name if user else "")).strip()[:150],
        phone=str(payload.get("phone") or (user.phone if user else "")).strip()[:32],
        city=city[:100],
        address=address[:255],
        notes=(str(payload.get("notes") or "").strip()[:255] or None),
        is_default=make_default,
    )
    db.session.add(row)
    db.session.commit()
    return _addr_dict(row)


def update_address(user_id: int, address_id: int, payload: dict) -> dict:
    row = MobileUserAddress.query.filter_by(id=address_id, user_id=user_id).first()
    if row is None:
        raise ProfileError("العنوان غير موجود", "not_found")
    for field in ("label", "full_name", "phone", "city", "address", "notes"):
        if field in payload:
            value = str(payload.get(field) or "").strip()
            setattr(row, field, value or None if field == "notes" else value)
    if payload.get("is_default"):
        MobileUserAddress.query.filter_by(user_id=user_id).update({"is_default": False})
        row.is_default = True
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return _addr_dict(row)


def delete_address(user_id: int, address_id: int) -> None:
    row = MobileUserAddress.query.filter_by(id=address_id, user_id=user_id).first()
    if row is None:
        raise ProfileError("العنوان غير موجود", "not_found")
    was_default = row.is_default
    db.session.delete(row)
    db.session.flush()
    if was_default:
        nxt = (
            MobileUserAddress.query.filter_by(user_id=user_id)
            .order_by(MobileUserAddress.id.desc())
            .first()
        )
        if nxt:
            nxt.is_default = True
    db.session.commit()


def liked_videos(user_id: int, *, limit: int = 40) -> list[dict]:
    likes = (
        MobileVideoLike.query.filter_by(user_id=user_id)
        .order_by(MobileVideoLike.id.desc())
        .limit(limit)
        .all()
    )
    out = []
    for like in likes:
        video = db.session.get(MobileVideo, like.video_id)
        if video is None or video.deleted_at is not None:
            continue
        if video.status not in {"published", "ready"} or video.processing_status != "ready":
            continue
        out.append(video.to_feed_dict(liked=True, saved=False))
    return out


def saved_videos(user_id: int, *, limit: int = 40) -> list[dict]:
    saves = (
        MobileVideoSave.query.filter_by(user_id=user_id)
        .order_by(MobileVideoSave.id.desc())
        .limit(limit)
        .all()
    )
    out = []
    for save in saves:
        video = db.session.get(MobileVideo, save.video_id)
        if video is None or video.deleted_at is not None:
            continue
        if video.status not in {"published", "ready"} or video.processing_status != "ready":
            continue
        out.append(video.to_feed_dict(liked=False, saved=True))
    return out


def deactivate_account(user_id: int, *, reason: str = "") -> None:
    user = db.session.get(MobileUser, user_id)
    if user is None:
        raise ProfileError("المستخدم غير موجود", "not_found")
    user.is_active = False
    user.banned_at = datetime.utcnow()
    user.ban_reason = (reason or "حذف الحساب بطلب المستخدم")[:500]
    user.updated_at = datetime.utcnow()
    logout_all_sessions(user_id)
    db.session.commit()


def _addr_dict(row: MobileUserAddress) -> dict:
    return {
        "id": row.id,
        "label": row.label,
        "full_name": row.full_name,
        "phone": row.phone,
        "city": row.city,
        "address": row.address,
        "notes": row.notes or "",
        "is_default": bool(row.is_default),
    }
