"""Authentication endpoints for mobile OTP / session flow."""
from __future__ import annotations

from flask import g, request

from modules.mobile_app.api.v1.routes import mobile_api_v1_bp, require_mobile_auth
from modules.mobile_app.schemas import (
    api_error,
    api_ok,
    normalize_phone,
    require_json_fields,
)
from modules.mobile_app.services import auth as auth_service
from modules.mobile_app.services import otp as otp_service
from modules.mobile_app.services.feature_flags import is_flag_enabled
from modules.mobile_app.services.rate_limit import enforce_rate_limit


@mobile_api_v1_bp.post("/auth/phone-login")
def phone_login():
    """Frictionless shopper registration/login without an OTP challenge."""
    if not is_flag_enabled("mobile_app_enabled", True):
        return api_error("Mobile app disabled for this tenant", 403, code="app_disabled")

    limited = enforce_rate_limit("auth_phone_login", limit=20, window_seconds=60)
    if limited is not None:
        return limited

    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "phone", "device_id")
    if missing:
        return api_error(missing, 400, code="validation_error")

    phone = normalize_phone(body.get("phone"))
    if not phone:
        return api_error("رقم الهاتف غير صالح", 400, code="invalid_phone")
    device_id = str(body.get("device_id") or "").strip()
    if not device_id:
        return api_error("device_id required", 400, code="validation_error")

    ok, message, tokens = auth_service.login_with_phone(
        phone=phone,
        name=str(body.get("name") or "").strip(),
        email=str(body.get("email") or "").strip() or None,
        tenant_slug=g.tenant,
        device_id=device_id,
        platform=str(body.get("platform") or "unknown"),
        push_token=body.get("push_token"),
        app_version=body.get("app_version"),
    )
    if not ok or tokens is None:
        return api_error(message, 403, code="login_failed")
    return api_ok({"message": message, **tokens})


@mobile_api_v1_bp.post("/auth/request-otp")
def request_otp():
    if not is_flag_enabled("mobile_app_enabled", True):
        return api_error("Mobile app disabled for this tenant", 403, code="app_disabled")

    limited = enforce_rate_limit("auth_request_otp", limit=20, window_seconds=60)
    if limited is not None:
        return limited

    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "phone")
    if missing:
        return api_error(missing, 400, code="validation_error")

    phone = normalize_phone(body.get("phone"))
    if not phone:
        return api_error("Invalid phone number", 400, code="invalid_phone")

    ok, message, payload = otp_service.request_otp(
        phone, request_ip=request.headers.get("X-Forwarded-For") or request.remote_addr
    )
    if not ok:
        code = payload.get("code", "otp_error")
        status = 503 if code == "otp_delivery_failed" else 429
        return api_error(message, status, code=code)
    return api_ok({"message": message, **payload})


@mobile_api_v1_bp.post("/auth/verify-otp")
def verify_otp():
    if not is_flag_enabled("mobile_app_enabled", True):
        return api_error("Mobile app disabled for this tenant", 403, code="app_disabled")

    limited = enforce_rate_limit("auth_verify_otp", limit=30, window_seconds=60)
    if limited is not None:
        return limited

    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "phone", "code", "device_id")
    if missing:
        return api_error(missing, 400, code="validation_error")

    phone = normalize_phone(body.get("phone"))
    if not phone:
        return api_error("Invalid phone number", 400, code="invalid_phone")

    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip() or None
    device_id = str(body.get("device_id") or "").strip()
    if not device_id:
        return api_error("device_id required", 400, code="validation_error")

    ok, message, tokens = auth_service.login_with_otp(
        phone=phone,
        code=str(body.get("code") or ""),
        name=name,
        email=email,
        tenant_slug=g.tenant,
        device_id=device_id,
        platform=str(body.get("platform") or "unknown"),
        push_token=body.get("push_token"),
        app_version=body.get("app_version"),
    )
    if not ok or tokens is None:
        return api_error(message, 401, code="otp_verify_failed")
    return api_ok({"message": message, **tokens})


@mobile_api_v1_bp.post("/auth/refresh")
def refresh():
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "refresh_token")
    if missing:
        return api_error(missing, 400, code="validation_error")

    ok, message, tokens = auth_service.refresh_session(
        refresh_token=str(body.get("refresh_token")),
        tenant_slug=g.tenant,
    )
    if not ok or tokens is None:
        return api_error(message, 401, code="refresh_failed")
    return api_ok({"message": message, **tokens})


@mobile_api_v1_bp.post("/auth/logout")
@require_mobile_auth
def logout():
    body = request.get_json(silent=True) or {}
    refresh_token = body.get("refresh_token")
    if refresh_token:
        auth_service.logout_session(refresh_token=str(refresh_token))
    else:
        auth_service.logout_session(session_id=g.mobile_session.id)
    return api_ok({"message": "تم تسجيل الخروج."})


@mobile_api_v1_bp.post("/auth/logout-all")
@require_mobile_auth
def logout_all():
    count = auth_service.logout_all_sessions(g.mobile_user.id)
    return api_ok({"message": "تم إنهاء جميع الجلسات.", "revoked": count})


@mobile_api_v1_bp.get("/auth/me")
@require_mobile_auth
def me():
    return api_ok({"user": g.mobile_user.to_public_dict(), "tenant": g.tenant})
