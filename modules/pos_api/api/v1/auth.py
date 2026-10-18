"""POS API login."""
from __future__ import annotations

from flask import g, request

from extensions import db
from models.employee import Employee
from models.branch import Branch
from modules.pos_api.api.v1.routes import pos_api_v1_bp, require_pos_auth
from modules.pos_api.schemas import api_error, api_ok, require_json_fields
from modules.pos_api.services import tokens as token_service
from modules.pos_api.services.rate_limit import enforce_rate_limit
from utils.permission_checks import employee_can


def _employee_payload(emp: Employee) -> dict:
    branch = None
    if emp.branch_id:
        branch = db.session.get(Branch, emp.branch_id)
    permissions = [name for name in ("view_pos", "edit_price", "pay_orders", "delete_orders", "return_orders") if employee_can(emp, name)]
    return {
        "id": emp.id,
        "name": emp.name,
        "username": emp.username,
        "role": emp.role,
        "branch_id": emp.branch_id,
        "permissions": permissions,
        "branch": {"id": branch.id, "name": branch.name} if branch else None,
    }


@pos_api_v1_bp.post("/auth/login")
def login():
    limited = enforce_rate_limit("auth_login", limit=20, window_seconds=60)
    if limited is not None:
        return limited
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "username", "password")
    if missing:
        return api_error(missing, 400, code="validation_error")

    from werkzeug.security import check_password_hash

    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    matching = Employee.query.filter(db.func.lower(Employee.username) == username.lower()).all()
    emp = None
    for candidate in matching:
        stored = candidate.password or ""
        try:
            if stored.startswith(("pbkdf2:", "scrypt:", "argon2:")):
                if check_password_hash(stored, password):
                    emp = candidate
                    break
            elif stored == password:
                emp = candidate
                break
        except Exception:
            continue

    if not emp or not emp.is_active:
        return api_error("بيانات الدخول غير صحيحة", 401, code="invalid_credentials")
    if not employee_can(emp, "view_pos"):
        return api_error("ليست لديك صلاحية نقطة البيع", 403, code="forbidden")

    access = token_service.issue_access_token(employee_id=emp.id, tenant_slug=g.tenant)
    payload = _employee_payload(emp)
    data = {
        "access_token": access,
        "expires_in": token_service.ACCESS_TOKEN_MAX_AGE_SECONDS,
        "employee": {
            "id": payload["id"],
            "name": payload["name"],
            "username": emp.username,
            "role": emp.role,
        },
        "branch": payload["branch"],
        "permissions": payload["permissions"],
        "tenant_slug": g.tenant,
    }
    if body.get("issue_api_key"):
        if emp.role != "admin":
            return api_error("إصدار مفتاح API متاح للأدمن فقط", 403, code="forbidden")
        from modules.pos_api.services.api_keys import issue_api_key

        raw_key, _row = issue_api_key(
            employee_id=emp.id,
            tenant_slug=g.tenant,
            name=str(body.get("api_key_name") or "Core Assistant"),
        )
        data["api_key"] = raw_key
        data["api_key_note"] = "مفتاح دائم للمساعد. احفظه الآن؛ لن يظهر كاملاً مرة ثانية."
    return api_ok(data)


def _require_admin_for_keys():
    emp = g.pos_employee
    if emp.role != "admin":
        return api_error("إدارة مفاتيح API متاحة للأدمن فقط", 403, code="forbidden")
    return None


@pos_api_v1_bp.get("/auth/api-keys")
@require_pos_auth
def list_api_keys_route():
    denied = _require_admin_for_keys()
    if denied:
        return denied
    from modules.pos_api.services.api_keys import list_api_keys, serialize_key

    return api_ok({"keys": [serialize_key(row) for row in list_api_keys()]})


@pos_api_v1_bp.post("/auth/api-keys")
@require_pos_auth
def create_api_key():
    denied = _require_admin_for_keys()
    if denied:
        return denied
    from modules.pos_api.services.api_keys import issue_api_key, serialize_key

    emp = g.pos_employee
    body = request.get_json(silent=True) or {}
    raw, row = issue_api_key(
        employee_id=emp.id,
        tenant_slug=g.tenant,
        name=str(body.get("name") or "Core Assistant"),
    )
    return api_ok(
        {
            "api_key": raw,
            "key": serialize_key(row),
            "note": "مفتاح دائم للمساعد. احفظه الآن؛ لن يظهر كاملاً مرة ثانية.",
        }
    )


@pos_api_v1_bp.delete("/auth/api-keys/<int:key_id>")
@require_pos_auth
def revoke_api_key_route(key_id: int):
    denied = _require_admin_for_keys()
    if denied:
        return denied
    from modules.pos_api.services.api_keys import revoke_api_key

    if not revoke_api_key(key_id):
        return api_error("المفتاح غير موجود", 404, code="not_found")
    return api_ok({"revoked": True})
