"""Customer workspace reads. Original invoices/plans remain the source of truth.

Read requests never clean up plans, change installment status or post money.
Linked installment principal is already in invoice debt and is not added twice.
"""
import hashlib
import json
import re
from datetime import datetime
from uuid import UUID, NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from flask import g, jsonify, render_template, request, session
from sqlalchemy import case, func, literal, or_, union_all
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.customer import Customer
from models.customer_credit import CustomerCreditPlan, CustomerInstallment
from models.invoice import Invoice
from modules.desktop_api.routes import desktop_api_bp, _error
from services.reports_service import ReportFilters, effective_paid_expr, receivable_conditions
from utils.branch_context import init_branch_context
from utils.branch_scope import is_general_admin
from utils.branch_scope import resolve_write_branch_id
from utils.permission_checks import employee_can, get_current_employee
from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES

PROFILE_FIELDS = {"name": 150, "phone": 20, "phone2": 20, "city": 100, "address": 255, "notes": 2000}


def _profile(row):
    return {field: getattr(row, field) or "" for field in PROFILE_FIELDS}


def _revision(row):
    value = {**_profile(row), "branch_id": row.branch_id}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _today():
    return datetime.now(ZoneInfo("Asia/Baghdad")).date()


def _authorize():
    if not session.get("user_id") or not session.get("tenant_slug"):
        return _error("انتهت الجلسة، سجّل الدخول من جديد", 401, "unauthenticated")
    if str(getattr(g, "tenant", "")) != session["tenant_slug"]:
        return _error("تعذر تحديد الشركة", 403, "tenant_required")
    employee = get_current_employee()
    if not employee or not employee.is_active:
        return _error("انتهت الجلسة، سجّل الدخول من جديد", 401, "unauthenticated")
    if not employee_can(employee, "manage_customers"):
        return _error("ليست لديك صلاحية إدارة العملاء", 403, "forbidden")
    if not getattr(g, "branch_scope_ready", False):
        init_branch_context()
    return None


def _scoped(query, model):
    # Explicit criteria also protect app integrations without the ORM listener.
    if not getattr(g, "independent_branches_enabled", True):
        return query
    employee = get_current_employee()
    if not is_general_admin(employee):
        return query.filter(model.branch_id == employee.branch_id) if employee.branch_id else query.filter(False)
    if not getattr(g, "view_all_branches", False):
        branch = getattr(g, "branch", None)
        return query.filter(model.branch_id == branch.id) if branch else query.filter(False)
    return query


def _invoices():
    return _scoped(Invoice.query, Invoice)


def _plans():
    visible_customers = _scoped(db.session.query(Customer.id), Customer)
    # Exclude stale plans for voided invoices without mutating history on GET.
    visible_invoice = _invoices().filter(
        Invoice.id == CustomerCreditPlan.invoice_id,
        Invoice.customer_id == CustomerCreditPlan.customer_id,
        Invoice.status.notin_(list(CANCELED_STATUSES | RETURN_STATUSES)),
        or_(Invoice.payment_status.is_(None), Invoice.payment_status.notin_(list(CANCELED_STATUSES | RETURN_STATUSES))),
    ).exists()
    return CustomerCreditPlan.query.filter(
        CustomerCreditPlan.customer_id.in_(visible_customers),
        or_(CustomerCreditPlan.invoice_id.is_(None), visible_invoice),
    )


def _amount_remaining(total, paid):
    difference = func.coalesce(total, 0) - func.coalesce(paid, 0)
    return case((difference > 0, difference), else_=0)


def _workspace_query(search=""):
    today = _today()
    filters = ReportFilters("all", today, today)
    invoice_debt = _invoices().with_entities(
        Invoice.customer_id.label("customer_id"),
        func.sum(func.coalesce(Invoice.total, 0) - effective_paid_expr()).label("amount"),
    ).filter(*receivable_conditions(filters)).group_by(Invoice.customer_id).subquery()
    standalone = _plans().with_entities(
        CustomerCreditPlan.customer_id.label("customer_id"),
        func.sum(_amount_remaining(CustomerCreditPlan.total_amount, CustomerCreditPlan.paid_amount)).label("amount"),
    ).filter(CustomerCreditPlan.invoice_id.is_(None)).group_by(CustomerCreditPlan.customer_id).subquery()
    overdue = db.session.query(
        CustomerCreditPlan.customer_id.label("customer_id"),
        func.sum(_amount_remaining(CustomerInstallment.amount, CustomerInstallment.paid_amount)).label("amount"),
    ).join(CustomerInstallment, CustomerInstallment.plan_id == CustomerCreditPlan.id).filter(
        CustomerCreditPlan.id.in_(_plans().with_entities(CustomerCreditPlan.id)),
        CustomerInstallment.due_date < today,
    ).group_by(CustomerCreditPlan.customer_id).subquery()
    debt = (func.coalesce(invoice_debt.c.amount, 0) + func.coalesce(standalone.c.amount, 0)).label("debt")
    late = func.coalesce(overdue.c.amount, 0).label("overdue")
    query = _scoped(db.session.query(Customer, debt, late), Customer).outerjoin(
        invoice_debt, invoice_debt.c.customer_id == Customer.id,
    ).outerjoin(standalone, standalone.c.customer_id == Customer.id).outerjoin(overdue, overdue.c.customer_id == Customer.id)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.filter(or_(Customer.name.ilike(pattern, escape="\\"), Customer.phone.ilike(pattern, escape="\\")))
    return query, debt, late


def _customer(row, debt, overdue):
    return {"id": row.id, "name": row.name, "phone": row.phone, "phone2": row.phone2 or "",
            "city": row.city or "", "address": row.address or "", "notes": row.notes or "",
            "branch_id": row.branch_id, "debt": int(debt), "overdue": int(overdue),
            "created_at": row.created_at.isoformat() if row.created_at else None, "revision": _revision(row)}


def _receivables(customer_id):
    """Current open documents, not reconstructed historical transactions.

    Invoice-linked plans only describe a schedule: principal belongs to the
    invoice. This query shares the report/workspace receivable eligibility.
    """
    today = _today()
    invoices = _invoices().filter(Invoice.customer_id == customer_id,
        *receivable_conditions(ReportFilters("all", today, today))).with_entities(
        literal("invoice").label("kind"), Invoice.id.label("id"),
        Invoice.branch_id.label("branch_id"),
        Invoice.id.label("invoice_id"), Invoice.created_at.label("date"),
        literal("فاتورة بيع").label("description"),
        func.coalesce(Invoice.total, 0).label("total"),
        effective_paid_expr().label("paid"),
        (func.coalesce(Invoice.total, 0) - effective_paid_expr()).label("remaining"))
    plans = _plans().join(Customer, Customer.id == CustomerCreditPlan.customer_id).filter(CustomerCreditPlan.customer_id == customer_id,
        CustomerCreditPlan.invoice_id.is_(None),
        _amount_remaining(CustomerCreditPlan.total_amount, CustomerCreditPlan.paid_amount) > 0).with_entities(
        literal("credit_plan").label("kind"), CustomerCreditPlan.id.label("id"),
        Customer.branch_id.label("branch_id"),
        literal(None).label("invoice_id"), CustomerCreditPlan.created_at.label("date"),
        func.coalesce(CustomerCreditPlan.description, "دين مستقل").label("description"),
        func.coalesce(CustomerCreditPlan.total_amount, 0).label("total"),
        func.coalesce(CustomerCreditPlan.paid_amount, 0).label("paid"),
        _amount_remaining(CustomerCreditPlan.total_amount, CustomerCreditPlan.paid_amount).label("remaining"))
    documents = union_all(invoices.statement, plans.statement).subquery()
    return db.session.query(documents), documents


def _pagination():
    try:
        page = int(request.args.get("page", 1))
        size = int(request.args.get("page_size", 25))
        if not 1 <= page <= 1_000_000 or size not in {10, 25, 50, 100}:
            raise ValueError
        return page, size
    except (ValueError, TypeError):
        return None


@desktop_api_bp.get("/customers")
def customer_workspace_list():
    denied = _authorize()
    if denied:
        return denied
    paging = _pagination()
    search = request.args.get("q", "").strip()
    tab = request.args.get("tab", "all")
    if not paging or len(search) > 150 or tab not in {"all", "debt", "overdue", "settled"}:
        return _error("فلاتر العملاء غير صحيحة", 400, "validation")
    page, size = paging
    query, debt, overdue = _workspace_query(search)
    totals = query.with_entities(func.count(Customer.id), func.coalesce(func.sum(debt), 0),
                                 func.coalesce(func.sum(overdue), 0), func.sum(case((debt > 0, 1), else_=0))).one()
    if tab == "debt":
        query = query.filter(debt > 0)
    elif tab == "overdue":
        query = query.filter(overdue > 0)
    elif tab == "settled":
        query = query.filter(debt == 0)
    count = query.count()
    rows = query.order_by(Customer.name, Customer.id).offset((page - 1) * size).limit(size).all()
    return jsonify(success=True, data={"items": [_customer(*row) for row in rows], "total": count,
        "page": page, "page_size": size, "stats": {"customers": int(totals[0]), "debt": int(totals[1]),
        "overdue": int(totals[2]), "debtors": int(totals[3] or 0)}, "as_of": _today().isoformat()})


@desktop_api_bp.get("/customers/<int:customer_id>")
def customer_workspace_detail(customer_id):
    denied = _authorize()
    if denied:
        return denied
    query, _, _ = _workspace_query()
    found = query.filter(Customer.id == customer_id).first()
    if not found:
        return _error("العميل غير موجود أو خارج الفروع المسموحة", 404, "not_found")
    return jsonify(success=True, data=_customer(*found))


@desktop_api_bp.get("/customers/<int:customer_id>/history")
def customer_workspace_history(customer_id):
    denied = _authorize()
    if denied:
        return denied
    if not _scoped(Customer.query, Customer).filter(Customer.id == customer_id).first():
        return _error("العميل غير موجود أو خارج الفروع المسموحة", 404, "not_found")
    paging = _pagination()
    kind = request.args.get("kind", "invoices")
    if not paging or kind not in {"invoices", "installments", "receivables"}:
        return _error("نوع السجل أو الصفحة غير صحيح", 400, "validation")
    page, size = paging
    if kind == "receivables":
        query, documents = _receivables(customer_id)
        totals = query.with_entities(func.count(), func.coalesce(func.sum(documents.c.total), 0),
            func.coalesce(func.sum(documents.c.paid), 0), func.coalesce(func.sum(documents.c.remaining), 0)).one()
        rows = [{**row._asdict(), "date": row.date.isoformat() if row.date else None}
            for row in query.order_by(documents.c.date, documents.c.kind, documents.c.id)
            .offset((page - 1) * size).limit(size)]
        return jsonify(success=True, data={"items": rows, "total": int(totals[0]), "page": page,
            "page_size": size, "as_of": _today().isoformat(), "summary": {
                "total": int(totals[1]), "paid": int(totals[2]), "remaining": int(totals[3])}})
    if kind == "invoices":
        query = _invoices().filter(Invoice.customer_id == customer_id).order_by(Invoice.created_at.desc(), Invoice.id.desc())
        total = query.count()
        rows = [{"id": row.id, "number": str(row.id), "date": row.created_at.isoformat() if row.created_at else None,
                 "status": row.status or "", "payment_status": row.payment_status or "", "total": int(row.total or 0),
                 "paid": int(row.paid_amount or 0)} for row in query.offset((page - 1) * size).limit(size).all()]
    else:
        query = CustomerInstallment.query.filter(CustomerInstallment.plan_id.in_(
            _plans().filter(CustomerCreditPlan.customer_id == customer_id).with_entities(CustomerCreditPlan.id)),
        ).order_by(CustomerInstallment.due_date, CustomerInstallment.id)
        total = query.count()
        rows = [{"id": row.id, "plan_id": row.plan_id, "invoice_id": row.plan.invoice_id, "number": row.sequence,
                 "date": row.due_date.isoformat(), "total": int(row.amount), "paid": int(row.paid_amount or 0),
                 "remaining": row.remaining, "status": "paid" if row.remaining == 0 else "overdue" if row.due_date < _today()
                 else "partial" if row.paid_amount else "pending"} for row in query.offset((page - 1) * size).limit(size).all()]
    return jsonify(success=True, data={"items": rows, "total": total, "page": page, "page_size": size})


@desktop_api_bp.get("/customers/<int:customer_id>/statement/print")
def customer_statement_print(customer_id):
    denied = _authorize()
    if denied:
        return denied
    customer = _scoped(Customer.query, Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return _error("العميل غير موجود أو خارج الفروع المسموحة", 404, "not_found")
    query, documents = _receivables(customer_id)
    # Print the entire statement rather than the selected UI page.
    rows = query.order_by(documents.c.date, documents.c.kind, documents.c.id).all()
    from models.invoice_settings import InvoiceSettings
    settings = InvoiceSettings.query.first()  # Printing must not initialize or change company settings.
    return render_template("customers/statement_print.html", customer=customer, rows=rows,
        settings=settings, as_of=_today().isoformat(),
        total=sum(row.total for row in rows), paid=sum(row.paid for row in rows),
        remaining=sum(row.remaining for row in rows))


@desktop_api_bp.post("/customers/commands")
def customer_profile_command():
    denied = _authorize()
    if denied:
        return denied
    body = request.get_json(silent=True)
    try:
        if not isinstance(body, dict) or set(body) - {"operation", "idempotency_key", "data", "id", "revision", "branch_id"}:
            raise ValueError("بيانات العميل غير صحيحة")
        operation = body.get("operation")
        if operation not in {"create", "update"}:
            raise ValueError("عملية العميل غير صحيحة")
        key = str(UUID(body.get("idempotency_key")))
        values = body.get("data")
        if not isinstance(values, dict) or set(values) != set(PROFILE_FIELDS):
            raise ValueError("أكمل بيانات ملف العميل")
        cleaned = {}
        for field, limit in PROFILE_FIELDS.items():
            if not isinstance(values[field], str) or len(values[field]) > limit:
                raise ValueError("أحد الحقول أطول من الحد المسموح")
            cleaned[field] = values[field].strip()
        if not cleaned["name"]:
            raise ValueError("أدخل اسم العميل")
        if not re.fullmatch(r"[0-9]{7,20}", cleaned["phone"]) or (cleaned["phone2"] and not re.fullmatch(r"[0-9]{7,20}", cleaned["phone2"])):
            raise ValueError("رقم الهاتف يجب أن يحتوي على 7 إلى 20 رقماً")
        if operation == "update" and (type(body.get("id")) is not int or body["id"] <= 0 or not re.fullmatch(r"[a-f0-9]{64}", str(body.get("revision", "")))):
            raise ValueError("حدّث ملف العميل قبل حفظ التعديل")
        if operation == "create" and ({"id", "revision"} & set(body)):
            raise ValueError("بيانات إنشاء العميل غير صحيحة")
        if operation == "update" and "branch_id" in body:
            raise ValueError("لا يمكن نقل فرع العميل أثناء تعديل ملفه")
    except (ValueError, TypeError, AttributeError) as exc:
        return _error(str(exc) if isinstance(exc, ValueError) else "بيانات العميل غير صحيحة", 400, "validation")

    from models.activity_log import ActivityLog
    from modules.desktop_api.sync import DesktopSyncReceipt, _receipt_response
    employee = get_current_employee()
    row = None
    if operation == "update":
        row = _scoped(Customer.query, Customer).filter(Customer.id == body["id"]).first()
        if not row:
            return _error("العميل غير موجود أو خارج الفروع المسموحة", 404, "not_found")
        branch_id = row.branch_id
        if not branch_id:
            return _error("يحتاج سجل العميل مراجعة الفرع قبل التعديل", 409, "branch_required")
    else:
        branch_id = resolve_write_branch_id(body)
    # Reuse the existing atomic replay receipt, with a separate operation namespace.
    namespace = str(uuid5(NAMESPACE_URL, "finora:desktop:customer-profile"))
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    DesktopSyncReceipt.__table__.create(bind=db.session.connection(), checkfirst=True)
    ActivityLog.__table__.create(bind=db.session.connection(), checkfirst=True)
    query = DesktopSyncReceipt.query.filter_by(device_id=namespace, operation_id=key)
    previous = query.first()
    if previous:
        return _receipt_response(previous, employee.id, branch_id, fingerprint)
    receipt = DesktopSyncReceipt(device_id=namespace, operation_id=key, employee_id=employee.id,
                                 branch_id=branch_id, fingerprint=fingerprint)
    db.session.add(receipt)
    try:
        db.session.flush()  # serializes same-key replay before any profile write
    except IntegrityError:
        db.session.rollback()
        previous = query.first()
        return _receipt_response(previous, employee.id, branch_id, fingerprint) if previous else _error("أعد المحاولة بنفس معرّف العملية", 503, "busy")
    try:
        if operation == "update":
            row = _scoped(Customer.query, Customer).filter(Customer.id == body["id"]).populate_existing().with_for_update().first()
            if not row:
                db.session.rollback()
                return _error("العميل غير موجود أو خارج الفروع المسموحة", 404, "not_found")
            if _revision(row) != body["revision"]:
                db.session.rollback()
                return _error("تغيّرت بيانات العميل؛ حدّث الملف قبل حفظ التعديل", 409, "conflict")
            before = _profile(row)
            for field, value in cleaned.items():
                setattr(row, field, value if field in {"name", "phone"} else (value or None))
        else:
            before = None
            row = Customer(branch_id=branch_id, **cleaned)
            db.session.add(row)
        db.session.flush()
        audit = ActivityLog(employee_id=employee.id, employee_name=employee.name, branch_id=branch_id,
                            action="create" if operation == "create" else "update", category="customers",
                            entity_type="customer", entity_id=str(row.id), summary=f"{'إضافة' if operation == 'create' else 'تعديل'} العميل: {row.name}",
                            request_method="POST", request_path=request.path)
        audit.set_payload({"before": before, "after": _profile(row)})
        db.session.add(audit)
        workspace, _, _ = _workspace_query()
        result = workspace.filter(Customer.id == row.id).first()
        response = {"success": True, "data": _customer(*result)}
        receipt.response_json = json.dumps(response, ensure_ascii=False)
        db.session.commit()
        return jsonify(response)
    except Exception:
        db.session.rollback()
        raise
