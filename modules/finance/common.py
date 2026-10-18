"""Strict validation, tenant/branch access, and database-serialized retry-safe commands."""
import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from flask import abort, g, request, has_request_context
from sqlalchemy import update
from extensions import db
from utils.branch_scope import is_general_admin, resolve_write_branch_id
from utils.permission_checks import employee_can, get_current_employee
from .models import FinanceAudit, FinanceCommand, FinanceMapping, FinancePolicy

PERMISSIONS = {
    "finance.view": "رؤية القبض والصرف والسلف والقروض",
    "finance.create": "إنشاء مسودات مالية",
    "finance.approve": "اعتماد وترحيل السندات",
    "finance.approve_large": "اعتماد المبالغ فوق الحد",
    "finance.reverse": "عكس السندات المرحلة",
    "finance.print": "طباعة وتصدير السندات",
    "finance.loans": "إدارة عقود السلف والقروض",
    "finance.reconcile": "مطابقة الحسابات المصرفية",
    "finance.ledger": "رؤية القيود والتقارير المحاسبية",
    "finance.settings": "إدارة السياسات وربط الحسابات والإقفال",
}
DEFAULT_POLICY = {"allow_negative": False, "separate_approval": False,
                  "approval_limit": 5_000_000, "sensitive_threshold": 1_000_000,
                  "low_balance": 100_000, "due_warning_days": 7}
# Defaults seed the existing Account table; every operational lookup uses FinanceMapping.
DEFAULT_ACCOUNTS = {
    "receivable": ("1201", "الذمم المدينة", "asset"),
    "inventory": ("1101", "المخزون", "asset"),
    "inventory_loss": ("5302", "عجز المخزون المعتمد", "expense"),
    "inventory_surplus": ("4202", "زيادة المخزون المعتمدة", "revenue"),
    "employee_advance": ("1202", "سلف الموظفين", "asset"),
    "loan_receivable": ("1203", "القروض الممنوحة للغير", "asset"),
    "supplier_advance": ("1204", "دفعات مقدمة للموردين", "asset"),
    "fixed_asset": ("1301", "الأصول الثابتة", "asset"),
    "accumulated_depreciation": ("1391", "مجمع إهلاك الأصول", "asset"),
    "payable": ("2001", "ديون الموردين", "liability"),
    "loan_payable": ("2201", "القروض المستحقة", "liability"),
    "interest_payable": ("2202", "فوائد ورسوم مستحقة", "liability"),
    "salary_payable": ("2102", "مستحقات الموظفين", "liability"),
    "salary_expense": ("5102", "مصروف رواتب وعمولات الموظفين", "expense"),
    "customer_advance": ("2301", "دفعات مقدمة من العملاء", "liability"),
    "expense_payable": ("2302", "مصاريف مستحقة", "liability"),
    "capital": ("3001", "رأس المال", "equity"),
    "owner_draw": ("3002", "سحوبات المالك", "equity"),
    "opening_equity": ("3901", "تسوية الأرصدة الافتتاحية", "equity"),
    "revenue": ("4001", "إيراد المبيعات", "revenue"),
    "other_revenue": ("4201", "إيرادات أخرى", "revenue"),
    "expense": ("5101", "المصاريف التشغيلية", "expense"),
    "cogs": ("5001", "تكلفة البضاعة المباعة", "expense"),
    "interest_expense": ("5201", "مصروف فوائد القروض", "expense"),
    "depreciation": ("5301", "مصروف إهلاك الأصول", "expense"),
}


class FinanceError(ValueError):
    def __init__(self, message, code="validation", status=400):
        super().__init__(message)
        self.code, self.status = code, status


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def money(value, *, minimum=1):
    if isinstance(value, bool):
        raise FinanceError("أدخل مبلغاً صحيحاً")
    try:
        result = Decimal(str(value).replace(",", ""))
        if not result.is_finite() or result != result.to_integral_value() or not minimum <= result <= 9_000_000_000_000_000:
            raise InvalidOperation
        return int(result)
    except (InvalidOperation, ValueError, TypeError):
        raise FinanceError("المبلغ بالدينار يجب أن يكون صحيحاً وضمن الحد المسموح")


def text(value, limit=500, required=False):
    result = str(value or "").strip()
    if len(result) > limit or (required and not result):
        raise FinanceError("أكمل الحقل المطلوب ضمن الطول المسموح")
    return result


def today():
    return datetime.now(ZoneInfo("Asia/Baghdad")).date()


def day(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise FinanceError("اختر تاريخاً صحيحاً")


def actor():
    employee = get_current_employee()
    if not employee or not employee.is_active:
        abort(401)
    return employee


def can(permission):
    return employee_can(actor(), permission)


def require(permission):
    if not can(permission):
        raise FinanceError("ليست لديك صلاحية هذه العملية", "forbidden", 403)


def tenant_key():
    slug = getattr(g, "tenant", None)
    if not slug:
        raise FinanceError("يجب اختيار الشركة قبل العملية المالية", "tenant_required", 403)
    return str(slug)


def scope(query, model):
    # Explicit branch filtering also protects direct service calls/tests.
    if not is_general_admin(actor()):
        query = query.filter(model.branch_id == actor().branch_id)
    elif getattr(g, "branch", None) and not getattr(g, "view_all_branches", False):
        query = query.filter(model.branch_id == g.branch.id)
    return query


def get_row(model, row_id):
    row = scope(model.query, model).filter(model.id == money(row_id)).with_for_update().first()
    if not row or (hasattr(row, "tenant_key") and row.tenant_key != tenant_key()):
        raise FinanceError("السجل غير موجود أو خارج الفروع المسموحة", "not_found", 404)
    return row


def write_branch(payload):
    return resolve_write_branch_id(payload, required=True)


def policy():
    return {**DEFAULT_POLICY, **json.loads(db.session.get(FinancePolicy, 1).settings)}


def version(row, payload):
    if money(payload.get("version")) != row.version:
        raise FinanceError("تغيّر السجل؛ حدّث البيانات وأعد المحاولة", "conflict", 409)


def audit(action, source_type, row, detail=None, *, created_by=None):
    if hasattr(row,"id") and row.id is None:
        db.session.flush()
    db.session.add(FinanceAudit(tenant_key=tenant_key(), branch_id=getattr(row, "branch_id", None),
        source_type=source_type, source_id=getattr(row, "id", 1), action=action,
        created_by=created_by if created_by is not None else actor().id, details=dumps(detail or {}),
        device=text((request.headers.get("X-Finora-Device") or request.user_agent.string) if has_request_context() else "FINORA background", 250)))


def command(operation, payload, action):
    require("finance.view")
    tenant_key()
    key = text(payload.get("idempotency_key"), 80, True)
    if not re.fullmatch(r"[A-Za-z0-9_-]{12,80}", key):
        raise FinanceError("معرّف إعادة المحاولة غير صالح")
    fingerprint = hashlib.sha256(dumps({"operation": operation, "payload": payload}).encode()).hexdigest()
    # First DML obtains SQLite's database write reservation across processes;
    # PostgreSQL locks the same tenant policy row until the whole transaction commits.
    db.session.execute(update(FinancePolicy).where(FinancePolicy.id == 1).values(revision=FinancePolicy.revision + 1))
    previous = db.session.get(FinanceCommand, key)
    if previous:
        if previous.created_by != actor().id or previous.fingerprint != fingerprint:
            raise FinanceError("معرّف العملية مستخدم لطلب مختلف", "idempotency_conflict", 409)
        db.session.rollback()
        return json.loads(previous.result)
    previous_operation = getattr(g, "finance_operation", False)
    g.finance_operation = True
    db.session.info["finance_atomic"] = True
    try:
        result = action()
        db.session.add(FinanceCommand(key=key, fingerprint=fingerprint, created_by=actor().id, result=dumps(result)))
        db.session.info["finance_commit_allowed"] = True
        db.session.commit()
    finally:
        db.session.info.pop("finance_atomic",None)
        db.session.info.pop("finance_commit_allowed",None)
        g.finance_operation = previous_operation
    return result
