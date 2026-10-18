"""Tenant/branch authorization and serialized, exactly-once counting commands."""
import hashlib
import json
from datetime import datetime
from uuid import UUID

from flask import g, session
from sqlalchemy import update

from extensions import db
from utils.branch_context import init_branch_context
from utils.branch_scope import allowed_branch_ids, is_general_admin
from utils.permission_checks import employee_can, get_current_employee
from .models import InventoryCountControl, InventoryCountEvent, InventoryCountSession

PERMISSIONS = {
    "inventory.audit.view": "عرض جلسات الجرد وسجلها",
    "inventory.audit.count": "بدء جلسة وإدخال وتعديل العد",
    "inventory.audit.system": "رؤية رصيد النظام وفروقات الجرد",
    "inventory.audit.cost": "رؤية تكلفة وقيمة فروقات الجرد",
    "inventory.audit.investigate": "فحص الأدلة المخزنية للجرد",
    "inventory.audit.review": "مراجعة الفروقات واستبعاد أصناف مع سبب",
    "inventory.audit.approve": "اعتماد نتائج الجرد",
    "inventory.audit.post": "ترحيل تسوية مخزون الجرد",
    "inventory.audit.export": "طباعة وتصدير تقرير الجرد",
}


class AuditError(ValueError):
    def __init__(self, message, code="validation", status=400):
        super().__init__(message)
        self.code, self.status = code, status


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def actor():
    row = get_current_employee()
    if not session.get("user_id") or not row or not row.is_active:
        raise AuditError("انتهت الجلسة، سجّل الدخول من جديد", "unauthenticated", 401)
    if not session.get("tenant_slug") or str(getattr(g, "tenant", "")) != session["tenant_slug"]:
        raise AuditError("تعذر تحديد الشركة", "tenant_required", 403)
    if not getattr(g, "branch_scope_ready", False):
        init_branch_context()
    return row


def can(permission):
    return employee_can(actor(), permission)


def require(permission):
    if not can(permission):
        raise AuditError("ليست لديك صلاحية تنفيذ هذا الإجراء في الجرد", "forbidden", 403)


def visible_branches():
    row = actor()
    # Shared catalog visibility is not permission to count somebody else's branch.
    if is_general_admin(row) and getattr(g, "view_all_branches", False):
        from models.branch import Branch
        return {branch_id for branch_id, in db.session.query(Branch.id).all()}
    if is_general_admin(row):
        return set(allowed_branch_ids())
    from utils.branch_assignments import assigned_branch_ids

    return set(assigned_branch_ids(row))


def integer(value, *, minimum=0, maximum=1_000_000_000):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise AuditError("أدخل عدداً صحيحاً ضمن المجال المسموح")
    return value


def text(value, *, limit=2000, required=False):
    if not isinstance(value, str) or len(value) > limit:
        raise AuditError("النص غير صالح أو أطول من الحد المسموح")
    value = value.strip()
    if required and not value:
        raise AuditError("أدخل سبباً واضحاً قبل الحفظ")
    return value


def get_session(session_id):
    integer(session_id, minimum=1)
    row = db.session.get(InventoryCountSession, session_id)
    if not row or row.tenant_key != session["tenant_slug"]:
        raise AuditError("جلسة الجرد غير موجودة", "not_found", 404)
    branches = {entry["branch_id"] for entry in json.loads(row.locations_json)}
    if not branches <= visible_branches():
        raise AuditError("جلسة الجرد خارج نطاق الفروع المسموحة", "forbidden", 403)
    return row


def check_version(row, value):
    if integer(value, minimum=1) != row.version:
        raise AuditError("تغيّر السجل من موظف آخر؛ حدّث البيانات قبل التعديل", "conflict", 409)


def command(operation, payload, action, *, session_id=None):
    """First DML locks the tenant control row before reading stock or receipts."""
    if not isinstance(payload, dict):
        raise AuditError("بيانات الطلب غير صالحة")
    try:
        key = str(UUID(text(payload.get("idempotency_key"), limit=36, required=True)))
    except (ValueError, TypeError, AttributeError):
        raise AuditError("معرف إعادة المحاولة غير صالح")
    user = actor()
    context = payload.get("audit_context")
    if context is not None:
        from utils.branch_context import current_branch_id
        from utils.branch_migration import get_default_branch
        branch_id = current_branch_id()
        if not branch_id:
            default = get_default_branch()
            branch_id = default.id if default else None
        expected = {"tenant_slug": session["tenant_slug"], "tenant_id": user.tenant_id,
                    "actor_id": user.id, "branch_id": branch_id,
                    "branch_scope": "shared" if not getattr(g, "independent_branches_enabled", True) else
                        "all" if getattr(g, "view_all_branches", False) else "branch"}
        if context != expected:
            raise AuditError("تغيّرت الشركة أو الموظف أو نطاق الفرع؛ افتح الجرد في الجلسة الصحيحة", "context_changed", 403)
    identity = {"operation": operation, "session_id": session_id, "payload": payload}
    digest = fingerprint(identity)
    db.session.execute(update(InventoryCountControl).where(InventoryCountControl.id == 1).values(
        revision=InventoryCountControl.revision + 1))
    previous = InventoryCountEvent.query.filter_by(command_key=key).first()
    if previous:
        get_session(previous.session_id)
        if previous.actor_id != user.id or previous.fingerprint != digest:
            raise AuditError("معرف العملية مستخدم لطلب مختلف", "idempotency_conflict", 409)
        result = json.loads(previous.result_json)
        if operation == "prepare_offline" and result.get("snapshot_permissions") != [
                name for name in ("inventory.audit.system", "inventory.audit.cost") if can(name)]:
            raise AuditError("تغيّرت صلاحيات اللقطة؛ نزّل لقطة جديدة", "snapshot_permissions", 409)
        if operation == "begin_count" and not can("inventory.audit.system"):
            result.pop("expected_quantity", None)
        db.session.rollback()
        return result
    if session_id is not None:
        get_session(session_id)
    result, detail = action()
    event = InventoryCountEvent(session_id=result["session_id"], line_id=result.get("line_id"),
        actor_id=user.id, actor_name=user.name or str(user.id), action=operation, command_key=key, fingerprint=digest,
        detail_json=dumps(detail), result_json=dumps(result), created_at=datetime.utcnow())
    db.session.add(event)
    db.session.commit()
    return result
