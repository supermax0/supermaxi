"""Device registration / revoke for Finora Phone."""

from __future__ import annotations

from datetime import datetime

from flask import g, request

from extensions import db
from modules.phone_app.api.v1.routes import phone_api_v1_bp, require_phone_auth
from modules.phone_app.models import PhoneAppDevice, PhoneAuditLog, PhoneRefreshToken
from modules.phone_app.schemas import api_error, api_ok, require_json_fields
from modules.phone_app.services.rate_limit import enforce_rate_limit


def _serialize(d: PhoneAppDevice) -> dict:
    return {
        "id": d.id,
        "device_uuid": d.device_uuid,
        "device_name": d.device_name,
        "manufacturer": d.manufacturer,
        "model": d.model,
        "android_version": d.android_version,
        "app_version": d.app_version,
        "sim_slots_count": d.sim_slots_count,
        "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
        "registered_at": d.registered_at.isoformat() if d.registered_at else None,
        "revoked_at": d.revoked_at.isoformat() if d.revoked_at else None,
        "is_active": bool(d.is_active and d.revoked_at is None),
        "server_time": datetime.utcnow().isoformat(),
    }


@phone_api_v1_bp.post("/devices/register")
@require_phone_auth
def devices_register():
    limited = enforce_rate_limit("device_register", limit=30, window_seconds=60)
    if limited is not None:
        return limited

    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "device_uuid")
    if missing:
        return api_error(missing, 400, code="validation_error")

    uuid = str(body.get("device_uuid") or "").strip()
    emp = g.phone_employee
    row = PhoneAppDevice.query.filter_by(employee_id=emp.id, device_uuid=uuid).first()
    if row and row.revoked_at is not None:
        return api_error("Device revoked", 403, code="device_revoked")

    if row is None:
        row = PhoneAppDevice(employee_id=emp.id, device_uuid=uuid)
        db.session.add(row)

    row.device_name = (str(body.get("device_name") or "")[:120] or None)
    row.manufacturer = (str(body.get("manufacturer") or "")[:80] or None)
    row.model = (str(body.get("model") or "")[:120] or None)
    row.android_version = (str(body.get("android_version") or "")[:40] or None)
    row.app_version = (str(body.get("app_version") or "")[:40] or None)
    row.push_token = (str(body.get("push_token") or "")[:512] or None)
    try:
        row.sim_slots_count = int(body["sim_slots_count"]) if body.get("sim_slots_count") is not None else row.sim_slots_count
    except (TypeError, ValueError):
        pass
    row.last_seen_at = datetime.utcnow()
    row.is_active = True
    db.session.add(
        PhoneAuditLog(
            employee_id=emp.id,
            device_id=uuid,
            action="device_register",
            detail=row.model,
        )
    )
    db.session.commit()
    return api_ok({"device": _serialize(row)})


@phone_api_v1_bp.get("/devices")
@require_phone_auth
def devices_list():
    emp = g.phone_employee
    q = PhoneAppDevice.query.filter_by(employee_id=emp.id)
    if emp.role != "admin":
        rows = q.order_by(PhoneAppDevice.last_seen_at.desc()).limit(50).all()
    else:
        # Admins see all devices for tenant employees (same DB).
        rows = PhoneAppDevice.query.order_by(PhoneAppDevice.last_seen_at.desc()).limit(200).all()
    return api_ok({"devices": [_serialize(d) for d in rows], "server_time": datetime.utcnow().isoformat()})


@phone_api_v1_bp.post("/devices/<int:device_id>/revoke")
@require_phone_auth
def devices_revoke(device_id: int):
    emp = g.phone_employee
    if emp.role != "admin":
        return api_error("Admin only", 403, code="forbidden")

    row = db.session.get(PhoneAppDevice, device_id)
    if not row:
        return api_error("Device not found", 404, code="not_found")

    row.revoked_at = datetime.utcnow()
    row.is_active = False
    # Revoke all refresh tokens for this device uuid.
    tokens = PhoneRefreshToken.query.filter_by(
        employee_id=row.employee_id, device_id=row.device_uuid
    ).all()
    for t in tokens:
        if t.revoked_at is None:
            t.revoked_at = datetime.utcnow()
    db.session.add(
        PhoneAuditLog(
            employee_id=emp.id,
            device_id=row.device_uuid,
            action="device_revoke",
            detail=f"target_employee={row.employee_id}",
        )
    )
    db.session.commit()
    return api_ok({"device": _serialize(row), "server_time": datetime.utcnow().isoformat()})
