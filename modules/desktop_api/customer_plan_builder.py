"""Build schedules without changing debt, money or any historical payment slice."""
import calendar
import hashlib
import json
import re
from datetime import date, timedelta
from uuid import UUID, NAMESPACE_URL, uuid5

from flask import current_app, jsonify, request
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.activity_log import ActivityLog
from models.customer import Customer
from models.customer_credit import CustomerCreditPlan, CustomerInstallment, CustomerCreditPayment
from models.customer_schedule_payment_link import CustomerSchedulePaymentLink
from models.invoice_payment_ledger import InvoicePaymentLedger
from modules.desktop_api.customers import _authorize, _invoices, _scoped, _today
from modules.desktop_api.customer_schedules import _source, _snapshot, _revision, _response
from modules.desktop_api.customer_schedule_history import inspect_history, preserve_history
from modules.desktop_api.routes import desktop_api_bp, _error
from modules.desktop_api.sync import DesktopSyncReceipt, _receipt_response
from modules.finance.common import FinanceError
from modules.finance.customer_installments import invoice_schedule, standalone_schedule
from modules.finance.models import FinancePolicy
from utils.customer_credit_service import compute_installment_status, split_installment_amounts
from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES
from utils.permission_checks import get_current_employee


def _invoice_source(customer_id, invoice_id, *, lock=False):
    customer = _scoped(Customer.query, Customer).filter_by(id=customer_id).first()
    query = _invoices().filter_by(id=invoice_id, customer_id=customer_id)
    invoice = query.populate_existing().with_for_update().first() if lock else query.first()
    if not customer or not invoice:
        raise FinanceError("الفاتورة غير موجودة أو خارج الفروع المسموحة", "not_found", 404)
    if not invoice.branch_id:
        raise FinanceError("حدد فرع الفاتورة قبل إنشاء الجدول", "branch_required", 409)
    return invoice


def _payment_history(invoice, *, lock=False):
    """Read existing columns only; a preview must never migrate a legacy ledger."""
    inspector = inspect(db.session.connection())
    if not inspector.has_table(InvoicePaymentLedger.__tablename__):
        return [], True
    columns = {column["name"] for column in inspector.get_columns(InvoicePaymentLedger.__tablename__)}
    names = [name for name in ("id", "amount_delta", "recorded_at", "source_module", "payment_method", "treasury_account_id") if name in columns]
    query = db.session.query(*(getattr(InvoicePaymentLedger, name) for name in names)).execution_options(
        skip_branch_scope=True).filter(InvoicePaymentLedger.invoice_id == invoice.id).order_by(InvoicePaymentLedger.id)
    if lock:
        query = query.populate_existing().with_for_update()
    return [dict(zip(names, row)) for row in query], {"source_module", "recorded_at"} <= columns


def _draft(invoice, *, lock=False):
    linked = CustomerCreditPlan.query.filter_by(invoice_id=invoice.id).order_by(CustomerCreditPlan.id).all()
    ledger, traceable = _payment_history(invoice, lock=lock)
    financial = inspect_history(invoice, ledger)
    paid = int(invoice.paid_amount or 0)
    reason = ""
    dead = CANCELED_STATUSES | RETURN_STATUSES
    if linked:
        reason = "الفاتورة مرتبطة بجدول أقساط؛ افتح جدولها الحالي"
    elif invoice.status in dead or invoice.payment_status in dead or invoice.is_stock_locked or invoice.shipping_company_id:
        reason = "هذه الفاتورة غير متاحة للجدولة؛ راجع حالتها أو جهة التحصيل"
    elif invoice.total <= 0 or not 0 <= paid < invoice.total:
        reason = "الفاتورة مسددة بالكامل أو رصيدها غير صحيح؛ لا يوجد مبلغ متبقٍ للجدولة"
    elif financial["blocked"]:
        reason = financial["blocked"]
    elif ledger and (sum(row["amount_delta"] for row in ledger) != paid
            or any(row["amount_delta"] for row in ledger) and (
                not traceable or paid == 0 and not financial["sources"] or any(not row.get("recorded_at") for row in ledger))):
        reason = "سجل التحصيل لا يكفي لتوثيق الرصيد السابق؛ راجع مصدر الدفعات قبل الجدولة"
    elif (paid or financial["sources"]) and not invoice.created_at:
        reason = "تاريخ الفاتورة مفقود؛ راجع المصدر قبل حفظ ملخص التحصيل السابق"
    historical = {"date": invoice.created_at.date().isoformat(), "paid": paid,
        "payment_count": sum(row["amount_delta"] != 0 for row in ledger),
        "vouchers": financial["vouchers"]} if (paid or financial["sources"]) and invoice.created_at else None
    snapshot = {"id": invoice.id, "customer_id": invoice.customer_id, "branch_id": invoice.branch_id,
        "total": invoice.total, "paid": int(invoice.paid_amount or 0), "status": invoice.status,
        "payment_status": invoice.payment_status, "stock_locked": invoice.is_stock_locked,
        "shipping_company_id": invoice.shipping_company_id, "plans": [p.id for p in linked],
        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
        "ledger": [{**row, "recorded_at": row["recorded_at"].isoformat() if row.get("recorded_at") else None} for row in ledger],
        "allocations": financial["snapshot"]}
    return {"customer_id": invoice.customer_id, "invoice_id": invoice.id, "total": invoice.total,
        "paid": int(invoice.paid_amount or 0), "revision": _revision(snapshot),
        "plan_id": linked[0].id if len(linked) == 1 else None, "eligible": not reason, "blocked_reason": reason,
        "historical": historical}


def _preserve_direct_payments(plan, invoice, employee_id):
    """Copy installment attribution, never create cash, a receipt, or a ledger delta."""
    paid = int(invoice.paid_amount or 0)
    history, _ = _payment_history(invoice, lock=True)
    financial = inspect_history(invoice, history)
    if financial["blocked"]:
        raise FinanceError(financial["blocked"], "conflict", 409)
    if not paid and not financial["sources"]:
        return []
    row = CustomerInstallment(plan_id=plan.id, sequence=1, due_date=invoice.created_at.date(),
        amount=paid, paid_amount=paid, status="paid")
    db.session.add(row)
    db.session.flush()
    preserve_history(plan, row, history, financial, employee_id)
    if not history:
        db.session.add(CustomerCreditPayment(customer_id=plan.customer_id, plan_id=plan.id,
            installment_id=row.id, amount=paid, created_at=invoice.created_at,
            note=f"[IP:{invoice.id}] رصيد تحصيل سابق غير مفصل؛ ليس قبضاً جديداً"))
    return [row]


def _validate(body):
    if not isinstance(body, dict) or set(body) != {"idempotency_key", "revision", "reason", "count", "first_due_date", "interval"}:
        raise ValueError("بيانات تقسيم الأقساط غير صحيحة")
    key = str(UUID(body["idempotency_key"]))
    if not isinstance(body["revision"], str) or not re.fullmatch(r"[0-9a-f]{64}", body["revision"]):
        raise ValueError("حدّث مصدر الدين قبل الجدولة")
    if not isinstance(body["reason"], str) or not 3 <= len(body["reason"].strip()) <= 500:
        raise ValueError("اكتب سبب الجدولة من 3 إلى 500 حرف")
    if type(body["count"]) is not int or not 1 <= body["count"] <= 240:
        raise ValueError("عدد الأقساط الجديدة من 1 إلى 240")
    if body["interval"] not in ("monthly", "weekly"):
        raise ValueError("اختر استحقاقاً شهرياً أو أسبوعياً")
    if not isinstance(body["first_due_date"], str) or len(body["first_due_date"]) != 10:
        raise ValueError("تاريخ أول استحقاق غير صحيح")
    due = date.fromisoformat(body["first_due_date"])
    if due.isoformat() != body["first_due_date"]:
        raise ValueError("تاريخ أول استحقاق غير صحيح")
    return key, due


def _dates(first, interval, count):
    for step in range(count):
        if interval == "weekly":
            yield first + timedelta(weeks=step)
        else:
            month = first.year * 12 + first.month - 1 + step
            year, index = divmod(month, 12)
            yield date(year, index + 1, min(first.day, calendar.monthrange(year, index + 1)[1]))


@desktop_api_bp.get("/customers/<int:customer_id>/invoices/<int:invoice_id>/schedule")
def invoice_schedule_preview(customer_id, invoice_id):
    denied = _authorize()
    if denied: return denied
    try:
        return jsonify(success=True, data=_draft(_invoice_source(customer_id, invoice_id)))
    except FinanceError as exc:
        return _error(str(exc), exc.status, exc.code)


def _build(customer_id, source_id, create):
    denied = _authorize()
    if denied: return denied
    body = request.get_json(silent=True)
    try:
        key, first = _validate(body)
        dates = list(_dates(first, body["interval"], body["count"]))
    except (ValueError, TypeError, AttributeError, OverflowError):
        return _error("راجع العدد والتاريخ والسبب وبيانات الجدولة", 400, "validation")
    try:
        if create:
            invoice = _invoice_source(customer_id, source_id)
            plan, branch_id = None, invoice.branch_id
        else:
            plan, invoice, branch_id = _source(customer_id, source_id, active=False)
        employee = get_current_employee()
        namespace = str(uuid5(NAMESPACE_URL, "finora:desktop:plan-builder"))
        fingerprint = hashlib.sha256(json.dumps({"create": create, "customer_id": customer_id,
            "source_id": source_id, **body}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        DesktopSyncReceipt.__table__.create(bind=db.session.connection(), checkfirst=True)
        ActivityLog.__table__.create(bind=db.session.connection(), checkfirst=True)
        query = DesktopSyncReceipt.query.filter_by(device_id=namespace, operation_id=key)
        previous = query.first()
        if previous:
            return _receipt_response(previous, employee.id, branch_id, fingerprint)
        receipt = DesktopSyncReceipt(device_id=namespace, operation_id=key, employee_id=employee.id,
            branch_id=branch_id, fingerprint=fingerprint)
        db.session.add(receipt)
        if create:
            # A second UUID cannot create another plan concurrently for the same invoice,
            # including SQLite where FOR UPDATE alone does not serialize writers.
            guard_namespace = str(uuid5(NAMESPACE_URL, "finora:desktop:invoice-plan-source"))
            guard_key = str(uuid5(NAMESPACE_URL, f"finora:invoice-plan:{source_id}"))
            with db.session.no_autoflush:
                guarded = DesktopSyncReceipt.query.filter_by(device_id=guard_namespace, operation_id=guard_key).first()
            if guarded:
                raise FinanceError("أنشئ جدول لهذه الفاتورة؛ حدّث ملف العميل", "conflict", 409)
            db.session.add(DesktopSyncReceipt(device_id=guard_namespace, operation_id=guard_key,
                employee_id=employee.id, branch_id=branch_id, fingerprint=fingerprint))
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            previous = query.first()
            return _receipt_response(previous, employee.id, branch_id, fingerprint) if previous else _error(
                "تغيرت الجدولة أو يوجد حفظ متزامن؛ حدّث المصدر", 409, "conflict")

        # Treasury commands lock policy before vouchers/invoices. Use that same
        # order, including the automatic posting hook at commit, to avoid a cycle.
        if inspect(db.session.connection()).has_table(FinancePolicy.__tablename__):
            db.session.query(FinancePolicy.id).filter_by(id=1).with_for_update().first()
        if invoice:
            invoice = _invoice_source(customer_id, invoice.id, lock=True)
        if create:
            context = _draft(invoice, lock=True)
            if not context["eligible"] or context["revision"] != body["revision"]:
                raise FinanceError(context["blocked_reason"] or "تغيرت الفاتورة؛ حدّث المصدر", "conflict", 409)
            plan = CustomerCreditPlan(customer_id=customer_id, invoice_id=invoice.id, entry_type="products",
                description=f"جدولة فاتورة #{invoice.id}", total_amount=invoice.total, paid_amount=int(invoice.paid_amount or 0),
                employee_id=employee.id, installments_count=body["count"])
            db.session.add(plan)
            db.session.flush()
            CustomerSchedulePaymentLink.__table__.create(bind=db.session.connection(), checkfirst=True)
            rows = protected = _preserve_direct_payments(plan, invoice, employee.id)
            before = {"installments": [], "total": invoice.total, "paid": int(invoice.paid_amount or 0)}
        else:
            plan, invoice, _ = _source(customer_id, source_id)
            plan = CustomerCreditPlan.query.filter_by(id=plan.id).populate_existing().with_for_update().one()
            if invoice:
                linked, rows = invoice_schedule(invoice)
                if linked.id != plan.id:
                    raise FinanceError("تغير مصدر الجدولة", "conflict", 409)
            else:
                rows = standalone_schedule(plan)
            before = _snapshot(plan, rows, invoice)
            if _revision(before) != body["revision"]:
                raise FinanceError("تغير الرصيد أو الجدول؛ حدّث المصدر", "conflict", 409)
            links = {p["installment_id"] for p in before["payment_links"]}
            protected = [row for row in rows if int(row.paid_amount or 0) or row.id in links]
        free = plan.total_amount - sum(row.amount for row in protected)
        if free < body["count"] or body["count"] + len(protected) > 240:
            raise FinanceError("المبلغ القابل للتقسيم لا يكفي أو تجاوز الجدول 240 قسطاً")
        unused = sorted([row for row in rows if row not in protected], key=lambda row: (row.sequence, row.id))
        amounts = split_installment_amounts(free, body["count"])
        last = max((row.sequence for row in protected), default=0)
        for index, (due, amount) in enumerate(zip(dates, amounts)):
            row = unused[index] if index < len(unused) else CustomerInstallment(plan_id=plan.id, paid_amount=0)
            row.sequence, row.due_date, row.amount = last + index + 1, due, amount
            row.status = compute_installment_status(row, _today())
            db.session.add(row)
        for row in unused[body["count"]:]:
            db.session.delete(row)
        plan.installments_count = len(protected) + body["count"]
        db.session.flush()
        after = _snapshot(plan, sorted(CustomerInstallment.query.filter_by(plan_id=plan.id).all(), key=lambda r: r.sequence), invoice)
        audit = ActivityLog(employee_id=employee.id, employee_name=employee.name, branch_id=branch_id,
            action="create" if create else "update", category="customers", entity_type="customer_credit_schedule",
            entity_id=str(plan.id), summary=f"{'إنشاء' if create else 'تقسيم'} جدول العميل #{customer_id}",
            request_method="POST", request_path=request.path)
        audit.set_payload({"reason": body["reason"].strip(), "before": before, "after": after})
        db.session.add(audit)
        db.session.flush()
        response = {"success": True, "data": _response(plan, invoice)}
        receipt.response_json = json.dumps(response, ensure_ascii=False)
        db.session.commit()
        return jsonify(response)
    except FinanceError as exc:
        db.session.rollback()
        return _error(str(exc), exc.status, exc.code)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Customer plan builder failed")
        return _error("تعذر حفظ الجدول؛ أعد المحاولة بنفس معرّف العملية", 500, "server_error")


@desktop_api_bp.post("/customers/<int:customer_id>/invoices/<int:invoice_id>/schedule")
def invoice_schedule_create(customer_id, invoice_id):
    return _build(customer_id, invoice_id, True)


@desktop_api_bp.post("/customers/<int:customer_id>/plans/<int:plan_id>/repartition")
def customer_schedule_repartition(customer_id, plan_id):
    return _build(customer_id, plan_id, False)
