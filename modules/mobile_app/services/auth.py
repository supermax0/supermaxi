"""Authentication orchestration: OTP verify → Customer link → session tokens."""
from __future__ import annotations

import logging
from datetime import datetime

from extensions import db
from models.customer import Customer
from modules.mobile_app.models import MobileUser, MobileUserDevice, MobileUserSession
from modules.mobile_app.services import otp as otp_service
from modules.mobile_app.services.tokens import (
    hash_token,
    issue_access_token,
    issue_refresh_token,
)

logger = logging.getLogger(__name__)


def _find_or_create_customer(phone: str, name: str) -> Customer:
    customer = Customer.query.filter_by(phone=phone).first()
    if customer:
        if name and (not customer.name or customer.name.strip() in ("", phone)):
            customer.name = name
        return customer
    customer = Customer(name=name or phone, phone=phone)
    db.session.add(customer)
    db.session.flush()
    return customer


def _find_or_create_user(phone: str, name: str, email: str | None) -> MobileUser:
    user = MobileUser.query.filter_by(phone=phone).first()
    if user is None:
        customer = _find_or_create_customer(phone, name)
        user = MobileUser(
            phone=phone,
            name=name or customer.name or phone,
            email=email,
            customer_id=customer.id,
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()
        return user

    if name:
        user.name = name
    if email is not None:
        user.email = email or None
    if not user.customer_id:
        customer = _find_or_create_customer(phone, user.name or name)
        user.customer_id = customer.id
    return user


def _upsert_device(
    user: MobileUser,
    *,
    device_id: str,
    platform: str,
    push_token: str | None,
    app_version: str | None,
) -> MobileUserDevice:
    device = MobileUserDevice.query.filter_by(user_id=user.id, device_id=device_id).first()
    if device is None:
        device = MobileUserDevice(
            user_id=user.id,
            device_id=device_id,
            platform=(platform or "unknown")[:30],
        )
        db.session.add(device)
        db.session.flush()
    device.platform = (platform or device.platform or "unknown")[:30]
    if push_token is not None:
        device.push_token = push_token[:512] if push_token else None
    if app_version is not None:
        device.app_version = (app_version or "")[:40] or None
    device.last_seen_at = datetime.utcnow()
    return device


def create_session_for_user(
    user: MobileUser,
    *,
    tenant_slug: str,
    device_id: str,
    platform: str = "unknown",
    push_token: str | None = None,
    app_version: str | None = None,
) -> dict:
    device = _upsert_device(
        user,
        device_id=device_id,
        platform=platform,
        push_token=push_token,
        app_version=app_version,
    )
    refresh_raw, refresh_hash, expires_at = issue_refresh_token()
    session_row = MobileUserSession(
        user_id=user.id,
        device_id=device.id,
        refresh_token_hash=refresh_hash,
        expires_at=expires_at,
    )
    db.session.add(session_row)
    db.session.flush()
    access = issue_access_token(
        user_id=user.id, tenant_slug=tenant_slug, session_id=session_row.id
    )
    db.session.commit()
    return {
        "access_token": access,
        "refresh_token": refresh_raw,
        "token_type": "Bearer",
        "expires_in": 15 * 60,
        "user": user.to_public_dict(),
    }


def login_with_otp(
    *,
    phone: str,
    code: str,
    name: str,
    email: str | None,
    tenant_slug: str,
    device_id: str,
    platform: str = "unknown",
    push_token: str | None = None,
    app_version: str | None = None,
) -> tuple[bool, str, dict | None]:
    ok, message, _otp_row = otp_service.verify_otp_code(phone, code)
    if not ok:
        return False, message, None

    user = _find_or_create_user(phone, name=name or "", email=email)
    if not user.is_active or user.banned_at is not None:
        return False, "الحساب غير مفعّل.", None

    db.session.commit()
    tokens = create_session_for_user(
        user,
        tenant_slug=tenant_slug,
        device_id=device_id,
        platform=platform,
        push_token=push_token,
        app_version=app_version,
    )
    try:
        from modules.mobile_app.services import rewards as reward_service
        from modules.mobile_app.services.feature_flags import is_flag_enabled

        if is_flag_enabled("rewards_enabled", True):
            reward_service.grant_welcome_bonus(user.id)
    except Exception:
        logger.exception("welcome bonus failed for user=%s", user.id)
    return True, "تم تسجيل الدخول.", tokens


def login_with_phone(
    *,
    phone: str,
    name: str,
    email: str | None,
    tenant_slug: str,
    device_id: str,
    platform: str = "unknown",
    push_token: str | None = None,
    app_version: str | None = None,
) -> tuple[bool, str, dict | None]:
    """Create or resume a shopper account using a phone number directly.

    This tenant intentionally uses frictionless phone-only registration. The
    endpoint remains rate-limited and device sessions can still be revoked.
    """
    user = _find_or_create_user(phone, name=name or "", email=email)
    if not user.is_active or user.banned_at is not None:
        db.session.rollback()
        return False, "الحساب غير مفعّل.", None

    db.session.commit()
    tokens = create_session_for_user(
        user,
        tenant_slug=tenant_slug,
        device_id=device_id,
        platform=platform,
        push_token=push_token,
        app_version=app_version,
    )
    try:
        from modules.mobile_app.services import rewards as reward_service
        from modules.mobile_app.services.feature_flags import is_flag_enabled

        if is_flag_enabled("rewards_enabled", True):
            reward_service.grant_welcome_bonus(user.id)
    except Exception:
        logger.exception("welcome bonus failed for user=%s", user.id)
    return True, "تم تسجيل الدخول.", tokens


def refresh_session(*, refresh_token: str, tenant_slug: str) -> tuple[bool, str, dict | None]:
    token_hash = hash_token(refresh_token)
    row = MobileUserSession.query.filter_by(refresh_token_hash=token_hash).first()
    if row is None or not row.is_active:
        return False, "جلسة غير صالحة.", None

    user = db.session.get(MobileUser, row.user_id)
    if user is None or not user.is_active or user.banned_at is not None:
        return False, "الحساب غير مفعّل.", None

    # Rotate refresh token
    row.revoked_at = datetime.utcnow()
    new_raw, new_hash, expires_at = issue_refresh_token()
    new_session = MobileUserSession(
        user_id=user.id,
        device_id=row.device_id,
        refresh_token_hash=new_hash,
        expires_at=expires_at,
    )
    db.session.add(new_session)
    db.session.flush()
    access = issue_access_token(
        user_id=user.id, tenant_slug=tenant_slug, session_id=new_session.id
    )
    db.session.commit()
    return True, "تم تجديد الجلسة.", {
        "access_token": access,
        "refresh_token": new_raw,
        "token_type": "Bearer",
        "expires_in": 15 * 60,
        "user": user.to_public_dict(),
    }


def logout_session(*, refresh_token: str | None = None, session_id: int | None = None) -> None:
    row = None
    if refresh_token:
        row = MobileUserSession.query.filter_by(
            refresh_token_hash=hash_token(refresh_token)
        ).first()
    elif session_id is not None:
        row = db.session.get(MobileUserSession, session_id)
    if row and row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        db.session.commit()


def logout_all_sessions(user_id: int) -> int:
    now = datetime.utcnow()
    rows = MobileUserSession.query.filter(
        MobileUserSession.user_id == user_id,
        MobileUserSession.revoked_at.is_(None),
    ).all()
    for row in rows:
        row.revoked_at = now
    db.session.commit()
    return len(rows)
