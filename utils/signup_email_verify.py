"""رمز تحقق البريد الإلكتروني قبل التسجيل."""
from __future__ import annotations

import hashlib
import re
import secrets
import time
from typing import Optional, Tuple

from flask import session

OTP_TTL_SECONDS = 10 * 60
RESEND_COOLDOWN_SECONDS = 60
MAX_VERIFY_ATTEMPTS = 5
SESSION_OTP_KEY = "signup_email_otp"
SESSION_VERIFIED_KEY = "signup_email_verified"

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    e = normalize_email(email)
    return bool(e) and len(e) <= 254 and bool(_EMAIL_RE.match(e))


def _hash_code(email: str, code: str) -> str:
    payload = f"{normalize_email(email)}:{code}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _now() -> float:
    return time.time()


def clear_signup_email_verification() -> None:
    session.pop(SESSION_OTP_KEY, None)
    session.pop(SESSION_VERIFIED_KEY, None)


def is_email_verified_for_signup(email: str) -> bool:
    verified = normalize_email(session.get(SESSION_VERIFIED_KEY) or "")
    return bool(verified) and verified == normalize_email(email)


def issue_signup_verification_code(email: str) -> Tuple[bool, str, Optional[str]]:
    """
    إنشاء رمز وإرساله. يُرجع (ok, message, code_for_dev).
    code_for_dev يُملأ فقط في وضع التطوير عند فشل الإرسال أو DEBUG.
    """
    email_norm = normalize_email(email)
    if not is_valid_email(email_norm):
        return False, "يرجى إدخال بريد إلكتروني صحيح", None

    otp_state = session.get(SESSION_OTP_KEY) or {}
    last_sent = float(otp_state.get("sent_at") or 0)
    if last_sent and (_now() - last_sent) < RESEND_COOLDOWN_SECONDS:
        wait = int(RESEND_COOLDOWN_SECONDS - (_now() - last_sent))
        return False, f"يرجى الانتظار {wait} ثانية قبل إعادة الإرسال", None

    # تغيير البريد يلغي التحقق السابق
    if session.get(SESSION_VERIFIED_KEY) and normalize_email(session.get(SESSION_VERIFIED_KEY)) != email_norm:
        session.pop(SESSION_VERIFIED_KEY, None)

    code = f"{secrets.randbelow(900000) + 100000:06d}"
    session[SESSION_OTP_KEY] = {
        "email": email_norm,
        "code_hash": _hash_code(email_norm, code),
        "expires_at": _now() + OTP_TTL_SECONDS,
        "sent_at": _now(),
        "attempts": 0,
    }
    session.modified = True

    from utils.email_helper import send_signup_verification_email

    sent = send_signup_verification_email(email_norm, code)
    if not sent:
        from flask import current_app
        if current_app.debug or current_app.config.get("ENV") == "development":
            return True, "تعذّر إرسال البريد (وضع التطوير). استخدم الرمز المعروض.", code
        return False, "تعذّر إرسال رمز التحقق. تأكد من إعدادات البريد أو حاول لاحقاً.", None

    return True, "تم إرسال رمز التحقق إلى بريدك الإلكتروني", None


def verify_signup_email_code(email: str, code: str) -> Tuple[bool, str]:
    email_norm = normalize_email(email)
    code_clean = (code or "").strip()

    if not is_valid_email(email_norm):
        return False, "يرجى إدخال بريد إلكتروني صحيح"
    if not re.fullmatch(r"\d{6}", code_clean):
        return False, "رمز التحقق يجب أن يكون 6 أرقام"

    otp_state = session.get(SESSION_OTP_KEY) or {}
    if not otp_state or normalize_email(otp_state.get("email")) != email_norm:
        return False, "لم يُرسل رمز لهذا البريد. اضغط «إرسال الرمز» أولاً"

    if _now() > float(otp_state.get("expires_at") or 0):
        session.pop(SESSION_OTP_KEY, None)
        return False, "انتهت صلاحية الرمز. أعد الإرسال"

    attempts = int(otp_state.get("attempts") or 0) + 1
    otp_state["attempts"] = attempts
    session[SESSION_OTP_KEY] = otp_state

    if attempts > MAX_VERIFY_ATTEMPTS:
        session.pop(SESSION_OTP_KEY, None)
        return False, "تجاوزت عدد المحاولات. أعد إرسال رمز جديد"

    expected = otp_state.get("code_hash") or ""
    if not secrets.compare_digest(_hash_code(email_norm, code_clean), expected):
        session.modified = True
        return False, "رمز التحقق غير صحيح"

    session[SESSION_VERIFIED_KEY] = email_norm
    session.pop(SESSION_OTP_KEY, None)
    session.modified = True
    return True, "تم التحقق من بريدك الإلكتروني بنجاح"
