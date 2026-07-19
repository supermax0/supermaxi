"""OTP creation, rate limiting, and verification."""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta

from extensions import db
from modules.mobile_app.models import MobileOtpRequest

logger = logging.getLogger(__name__)

OTP_TTL_SECONDS = 5 * 60
OTP_COOLDOWN_SECONDS = 60
OTP_MAX_PER_HOUR = 5
OTP_LENGTH = 6


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    return f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"


def _deliver_otp(phone: str, code: str) -> bool:
    """Pluggable SMS hook — log provider by default, HTTP webhook when configured."""
    from modules.mobile_app.providers.sms import deliver_otp

    ok = deliver_otp(phone, code)
    if not ok:
        logger.warning("mobile_otp delivery failed phone=%s", phone)
    return ok


def request_otp(phone: str, *, request_ip: str | None = None) -> tuple[bool, str, dict]:
    now = datetime.utcnow()
    hour_ago = now - timedelta(hours=1)
    recent_count = (
        MobileOtpRequest.query.filter(
            MobileOtpRequest.phone == phone,
            MobileOtpRequest.created_at >= hour_ago,
        ).count()
    )
    if recent_count >= OTP_MAX_PER_HOUR:
        return False, "تم تجاوز حد طلبات رمز التحقق. حاول لاحقاً.", {"code": "otp_rate_limited"}

    last = (
        MobileOtpRequest.query.filter_by(phone=phone)
        .order_by(MobileOtpRequest.created_at.desc())
        .first()
    )
    if last and last.created_at and (now - last.created_at).total_seconds() < OTP_COOLDOWN_SECONDS:
        wait = OTP_COOLDOWN_SECONDS - int((now - last.created_at).total_seconds())
        return False, f"انتظر {wait} ثانية قبل طلب رمز جديد.", {"code": "otp_cooldown", "retry_after": wait}

    code = _generate_code()
    row = MobileOtpRequest(
        phone=phone,
        code_hash=_hash_code(code),
        attempts=0,
        max_attempts=5,
        expires_at=now + timedelta(seconds=OTP_TTL_SECONDS),
        request_ip=(request_ip or "")[:64] or None,
    )
    db.session.add(row)
    if not _deliver_otp(phone, code):
        db.session.rollback()
        return False, "تعذر إرسال رمز التحقق حالياً. حاول لاحقاً.", {
            "code": "otp_delivery_failed"
        }
    db.session.commit()

    payload = {
        "expires_in": OTP_TTL_SECONDS,
        "phone": phone,
    }
    # Expose OTP only when explicitly enabled (tests / local debug).
    from flask import current_app

    if current_app.config.get("MOBILE_OTP_DEBUG_RETURN_CODE"):
        payload["debug_code"] = code

    return True, "تم إرسال رمز التحقق.", payload


def verify_otp_code(phone: str, code: str) -> tuple[bool, str, MobileOtpRequest | None]:
    now = datetime.utcnow()
    row = (
        MobileOtpRequest.query.filter(
            MobileOtpRequest.phone == phone,
            MobileOtpRequest.consumed_at.is_(None),
        )
        .order_by(MobileOtpRequest.created_at.desc())
        .first()
    )
    if row is None:
        return False, "لا يوجد رمز تحقق نشط.", None
    if row.expires_at < now:
        return False, "انتهت صلاحية رمز التحقق.", None
    if row.attempts >= row.max_attempts:
        return False, "تم تجاوز عدد محاولات التحقق.", None

    row.attempts = int(row.attempts or 0) + 1
    if row.code_hash != _hash_code(str(code).strip()):
        db.session.commit()
        return False, "رمز التحقق غير صحيح.", None

    row.consumed_at = now
    db.session.commit()
    return True, "تم التحقق.", row
