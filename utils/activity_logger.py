"""Central activity logging service."""
from __future__ import annotations

import json
import re
from typing import Any

from flask import current_app, has_request_context, request, session

from extensions import db
from models.activity_log import ActivityLog

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "authorization",
        "csrf_token",
        "credit_card",
        "cvv",
    }
)
_MAX_PAYLOAD_BYTES = 64 * 1024


def _is_sensitive_key(key: str) -> bool:
    key_lower = (key or "").lower()
    if key_lower in _SENSITIVE_KEYS:
        return True
    return any(part in key_lower for part in ("password", "token", "secret"))


def sanitize_payload(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "[truncated]"
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if _is_sensitive_key(str(k)):
                out[k] = "[redacted]"
            else:
                out[k] = sanitize_payload(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [sanitize_payload(v, depth + 1) for v in value[:200]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 8000:
            return value[:8000] + "…"
        return value
    try:
        return str(value)[:2000]
    except Exception:
        return "[unserializable]"


def _truncate_payload(payload: dict) -> dict:
    try:
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw.encode("utf-8")) <= _MAX_PAYLOAD_BYTES:
            return payload
        return {
            "_truncated": True,
            "preview": raw[: _MAX_PAYLOAD_BYTES // 2],
        }
    except Exception:
        return {"_truncated": True, "preview": str(payload)[:4000]}


def _resolve_employee(employee=None):
    if employee is not None:
        return employee
    if not has_request_context():
        return None
    if "user_id" not in session:
        return None
    try:
        from models.employee import Employee

        return Employee.query.get(session["user_id"])
    except Exception:
        return None


def _request_meta() -> dict:
    if not has_request_context():
        return {}
    return {
        "method": request.method,
        "path": request.path,
        "query": sanitize_payload(dict(request.args)),
        "ip": (request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:64],
        "user_agent": (request.headers.get("User-Agent") or "")[:500],
    }


def log_activity(
    action: str,
    category: str,
    summary: str,
    *,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    payload: dict | None = None,
    employee=None,
    request_meta: bool = True,
    status_code: int | None = None,
    commit: bool = True,
) -> ActivityLog | None:
    try:
        emp = _resolve_employee(employee)
        meta = _request_meta() if request_meta else {}

        merged = dict(payload or {})
        if request_meta and meta:
            merged.setdefault("request", meta)

        clean = _truncate_payload(sanitize_payload(merged))

        branch_id = None
        if has_request_context():
            try:
                from flask import g

                branch = getattr(g, "branch", None)
                if branch:
                    branch_id = branch.id
                elif session.get("branch_id"):
                    branch_id = session.get("branch_id")
            except Exception:
                pass

        entry = ActivityLog(
            employee_id=getattr(emp, "id", None),
            employee_name=getattr(emp, "name", None) or session.get("name") if has_request_context() else None,
            branch_id=branch_id,
            action=(action or "unknown")[:30],
            category=(category or "system")[:50],
            entity_type=(entity_type or "")[:50] or None,
            entity_id=str(entity_id) if entity_id is not None else None,
            summary=(summary or "")[:2000],
            request_method=meta.get("method"),
            request_path=meta.get("path"),
            status_code=status_code,
            ip_address=meta.get("ip"),
            user_agent=meta.get("user_agent"),
        )
        entry.set_payload(clean)
        db.session.add(entry)
        if commit:
            db.session.commit()
        return entry
    except Exception as exc:
        try:
            db.session.rollback()
        except Exception:
            pass
        if current_app:
            current_app.logger.warning("activity_logger failed: %s", exc)
        return None


def log_view(path: str, category: str, summary: str, **kwargs) -> ActivityLog | None:
    return log_activity("view", category, summary, payload={"path": path, **kwargs.pop("payload", {})}, **kwargs)


def log_mutation(
    action: str,
    category: str,
    entity_type: str,
    entity_id: str | int | None,
    before: Any,
    after: Any,
    summary: str,
    **kwargs,
) -> ActivityLog | None:
    payload = {"before": before, "after": after}
    extra = kwargs.pop("payload", None)
    if extra:
        payload["extra"] = extra
    return log_activity(
        action,
        category,
        summary,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
        **kwargs,
    )


def log_auth(action: str, employee=None, *, success: bool = True, extra: dict | None = None) -> ActivityLog | None:
    name = getattr(employee, "name", None) or (session.get("name") if has_request_context() else None) or "—"
    summary_map = {
        "login": f"تسجيل دخول: {name}",
        "logout": f"تسجيل خروج: {name}",
        "login_failed": "محاولة دخول فاشلة",
    }
    summary = summary_map.get(action, f"مصادقة: {action}")
    if not success:
        summary = f"{summary} (فشل)"
    payload = {"success": success, **(extra or {})}
    return log_activity(action, "auth", summary, employee=employee, payload=payload)


def capture_request_body() -> dict:
    if not has_request_context():
        return {}
    try:
        if request.is_json:
            data = request.get_json(silent=True) or {}
            return sanitize_payload(data if isinstance(data, dict) else {"data": data})
        if request.form:
            return sanitize_payload(request.form.to_dict(flat=True))
    except Exception:
        pass
    return {}


_PATH_CATEGORY_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^/orders"), "orders"),
    (re.compile(r"^/pos"), "pos"),
    (re.compile(r"^/inventory"), "inventory"),
    (re.compile(r"^/purchases"), "purchases"),
    (re.compile(r"^/expenses"), "finance"),
    (re.compile(r"^/accounts"), "finance"),
    (re.compile(r"^/cash"), "finance"),
    (re.compile(r"^/reports"), "reports"),
    (re.compile(r"^/employees"), "employees"),
    (re.compile(r"^/customers"), "customers"),
    (re.compile(r"^/shipping"), "shipping"),
    (re.compile(r"^/agents"), "shipping"),
    (re.compile(r"^/delivery"), "shipping"),
    (re.compile(r"^/settings"), "settings"),
    (re.compile(r"^/admin/permissions"), "settings"),
    (re.compile(r"^/messages"), "messages"),
    (re.compile(r"^/pages"), "pages"),
    (re.compile(r"^/suppliers"), "suppliers"),
    (re.compile(r"^/beauty"), "beauty"),
    (re.compile(r"^/publisher"), "publisher"),
    (re.compile(r"^/workspace"), "workspace"),
    (re.compile(r"^/social-ai"), "social"),
    (re.compile(r"^/activity"), "system"),
    (re.compile(r"^/login"), "auth"),
]


def infer_category_from_path(path: str) -> str:
    for pattern, category in _PATH_CATEGORY_RULES:
        if pattern.search(path or ""):
            return category
    return "system"


INVOICE_SNAPSHOT_FIELDS = ("id", "status", "payment_status", "paid_amount", "total", "customer_id", "shipping_company_id", "delivery_agent_id")
PRODUCT_SNAPSHOT_FIELDS = ("id", "name", "quantity", "price", "cost", "active", "barcode")
EMPLOYEE_SNAPSHOT_FIELDS = ("id", "name", "username", "role", "is_active")
CUSTOMER_SNAPSHOT_FIELDS = ("id", "name", "phone", "address", "city")


def snapshot_attrs(obj, *fields: str) -> dict:
    if obj is None:
        return {}
    out = {}
    for field in fields:
        val = getattr(obj, field, None)
        if hasattr(val, "isoformat"):
            try:
                val = val.isoformat()
            except Exception:
                pass
        out[field] = val
    return out


def method_to_action(method: str) -> str:
    m = (method or "GET").upper()
    if m == "GET":
        return "view"
    if m == "POST":
        return "create"
    if m in ("PUT", "PATCH"):
        return "update"
    if m == "DELETE":
        return "delete"
    return m.lower()[:30]
