"""Staff auth for Finora Phone."""

from __future__ import annotations

from datetime import datetime

from flask import g, request

from extensions import db
from models.employee import Employee
from modules.phone_app.api.v1.routes import phone_api_v1_bp, require_phone_auth
from modules.phone_app.models import PhoneAuditLog, PhoneRefreshToken
from modules.phone_app.schemas import api_error, api_ok, require_json_fields
from modules.phone_app.services import tokens as token_service


def _employee_payload(emp: Employee) -> dict:
    return {
        "id": emp.id,
        "name": emp.name,
        "username": emp.username,
        "role": emp.role,
        "branch_id": emp.branch_id,
        "permissions": {
            "phone.view": True,
            "phone.call_log": True,
            "phone.create_order": bool(
                emp.role == "admin" or getattr(emp, "can_manage_customers", True)
            ),
            "phone.create_customer": bool(
                emp.role == "admin" or getattr(emp, "can_manage_customers", True)
            ),
            "phone.manage_tasks": True,
        },
    }


def _issue_pair(emp: Employee, device_id: str) -> dict:
    raw, token_hash, expires = token_service.issue_refresh_token()
    row = PhoneRefreshToken(
        employee_id=emp.id,
        token_hash=token_hash,
        device_id=device_id,
        expires_at=expires,
    )
    db.session.add(row)
    db.session.flush()
    access = token_service.issue_access_token(
        employee_id=emp.id,
        tenant_slug=g.tenant,
        session_id=row.id,
    )
    db.session.add(
        PhoneAuditLog(employee_id=emp.id, action="login", detail=f"device={device_id}")
    )
    db.session.commit()
    return {
        "access_token": access,
        "refresh_token": raw,
        "expires_in": token_service.ACCESS_TOKEN_MAX_AGE_SECONDS,
        "employee": _employee_payload(emp),
        "tenant_slug": g.tenant,
    }


from modules.phone_app.services.rate_limit import enforce_rate_limit


@phone_api_v1_bp.post("/auth/login")
def login():
    limited = enforce_rate_limit("auth_login", limit=20, window_seconds=60)
    if limited is not None:
        return limited
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "username", "password", "device_id")
    if missing:
        return api_error(missing, 400, code="validation_error")

    from werkzeug.security import check_password_hash

    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    device_id = str(body.get("device_id") or "").strip()
    if not device_id:
        return api_error("device_id required", 400, code="validation_error")

    # Match web login: case-insensitive username + hashed password check.
    matching = Employee.query.filter(
        db.func.lower(Employee.username) == username.lower()
    ).all()
    emp = None
    for candidate in matching:
        stored = candidate.password or ""
        try:
            if stored.startswith(("pbkdf2:", "scrypt:", "argon2:")):
                if check_password_hash(stored, password):
                    emp = candidate
                    break
            elif stored == password:
                # Legacy plain-text rows (rare)
                emp = candidate
                break
        except Exception:
            continue

    if not emp or not emp.is_active:
        db.session.add(
            PhoneAuditLog(
                action="login_failed", detail=f"user={username}", device_id=device_id
            )
        )
        db.session.commit()
        if emp is not None and not emp.is_active:
            return api_error(
                "هذا الحساب معطل، يرجى التواصل مع الإدارة",
                403,
                code="user_inactive",
            )
        return api_error("بيانات الدخول غير صحيحة", 401, code="invalid_credentials")

    # Block revoked devices even at login.
    from modules.phone_app.models import PhoneAppDevice

    existing_device = PhoneAppDevice.query.filter_by(
        employee_id=emp.id, device_uuid=device_id
    ).first()
    if existing_device is not None and (
        existing_device.revoked_at is not None or not existing_device.is_active
    ):
        return api_error("Device revoked", 403, code="device_revoked")

    # Auto-register device on successful login (Phase 1.5 field readiness).
    from modules.phone_app.models import PhoneAppDevice as _Pad

    device_row = existing_device
    if device_row is None:
        device_row = _Pad(employee_id=emp.id, device_uuid=device_id, is_active=True)
        db.session.add(device_row)
    device_row.last_seen_at = datetime.utcnow()
    device_row.is_active = True
    if body.get("device_name"):
        device_row.device_name = str(body.get("device_name"))[:120]
    if body.get("app_version"):
        device_row.app_version = str(body.get("app_version"))[:40]
    if body.get("manufacturer"):
        device_row.manufacturer = str(body.get("manufacturer"))[:80]
    if body.get("model"):
        device_row.model = str(body.get("model"))[:120]
    if body.get("android_version"):
        device_row.android_version = str(body.get("android_version"))[:40]
    try:
        if body.get("sim_slots_count") is not None:
            device_row.sim_slots_count = int(body.get("sim_slots_count"))
    except (TypeError, ValueError):
        pass

    return api_ok(_issue_pair(emp, device_id))


@phone_api_v1_bp.post("/auth/refresh")
def refresh():
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "refresh_token", "device_id")
    if missing:
        return api_error(missing, 400, code="validation_error")

    raw = str(body.get("refresh_token") or "")
    device_id = str(body.get("device_id") or "").strip()
    token_hash = token_service.hash_token(raw)
    row = PhoneRefreshToken.query.filter_by(token_hash=token_hash).first()
    if (
        row is None
        or row.revoked_at is not None
        or row.expires_at < datetime.utcnow()
        or row.device_id != device_id
    ):
        return api_error("Refresh token invalid", 401, code="refresh_invalid")

    emp = db.session.get(Employee, row.employee_id)
    if emp is None or not emp.is_active:
        return api_error("Employee inactive", 403, code="user_inactive")

    # Rotate refresh token
    row.revoked_at = datetime.utcnow()
    db.session.flush()
    return api_ok(_issue_pair(emp, device_id))


@phone_api_v1_bp.post("/auth/logout")
@require_phone_auth
def logout():
    session_row: PhoneRefreshToken = g.phone_session
    session_row.revoked_at = datetime.utcnow()
    db.session.add(
        PhoneAuditLog(
            employee_id=g.phone_employee.id,
            action="logout",
            detail=None,
        )
    )
    db.session.commit()
    return api_ok({"message": "logged_out"})


@phone_api_v1_bp.get("/auth/me")
@require_phone_auth
def me():
    return api_ok(
        {
            "employee": _employee_payload(g.phone_employee),
            "tenant_slug": g.tenant,
        }
    )
