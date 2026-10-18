"""Revision-checked schedule edits preserve principal, paid slices and source IDs."""
import hashlib
import json
import re
from datetime import date
from uuid import UUID, NAMESPACE_URL, uuid5

from flask import current_app, jsonify, request
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.activity_log import ActivityLog
from models.customer import Customer
from models.customer_credit import CustomerCreditPlan, CustomerInstallment, CustomerCreditPayment
from modules.desktop_api.customers import _authorize, _invoices, _plans, _scoped, _today
from modules.desktop_api.routes import desktop_api_bp, _error
from modules.desktop_api.sync import DesktopSyncReceipt, _receipt_response
from modules.finance.common import FinanceError
from modules.finance.customer_installments import invoice_schedule, standalone_schedule
from utils.customer_credit_service import compute_installment_status
from utils.permission_checks import get_current_employee


def _rows(plan):
    return CustomerInstallment.query.filter_by(plan_id=plan.id).order_by(
        CustomerInstallment.sequence, CustomerInstallment.id).all()


def _snapshot(plan, rows, invoice=None):
    return {"customer_id": plan.customer_id, "invoice_id": plan.invoice_id,
        "total": plan.total_amount, "paid": int(plan.paid_amount or 0),
        "invoice_total": invoice.total if invoice else None,
        "invoice_paid": int(invoice.paid_amount or 0) if invoice else None,
        "payment_links": [{"id": payment.id, "installment_id": payment.installment_id, "amount": payment.amount}
            for payment in CustomerCreditPayment.query.execution_options(skip_branch_scope=True).filter_by(plan_id=plan.id).order_by(CustomerCreditPayment.id)],
        "installments": [{"id": row.id, "number": row.sequence, "date": row.due_date.isoformat(),
            "total": row.amount, "paid": int(row.paid_amount or 0)} for row in sorted(rows, key=lambda item: (item.sequence, item.id))]}


def _revision(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _response(plan, invoice):
    value = _snapshot(plan, _rows(plan), invoice)
    history, count = [], 0
    if inspect(db.session.connection()).has_table(ActivityLog.__tablename__):
        query = ActivityLog.query.filter_by(category="customers", entity_type="customer_credit_schedule", entity_id=str(plan.id))
        # SQLite can reuse a deleted plan's numeric ID. Its older audit belongs
        # to that original plan, not a newly created schedule with the same ID.
        if plan.created_at:
            query = query.filter(ActivityLog.created_at >= plan.created_at)
        count = query.count()
        for row in query.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()).limit(25):
            payload = row.get_payload()
            history.append({"id": row.id, "actor": row.employee_name or "", "date": row.created_at.isoformat() + "Z",
                "reason": payload.get("reason", ""), "before": payload["before"]["installments"],
                "after": payload["after"]["installments"]})
    protected = {row["installment_id"] for row in value["payment_links"]}
    return {**value, "id": plan.id, "revision": _revision(value), "history": history, "history_total": count,
        "protected_ids": [row["id"] for row in value["installments"] if row["paid"] or row["id"] in protected]}


def _source(customer_id, plan_id, *, active=True):
    customer = _scoped(Customer.query, Customer).filter_by(id=customer_id).first()
    plan = (_plans() if active else CustomerCreditPlan.query).filter_by(id=plan_id, customer_id=customer_id).first() if customer else None
    invoice = _invoices().filter_by(id=plan.invoice_id, customer_id=customer_id).first() if plan and plan.invoice_id else None
    if not plan or (plan.invoice_id and not invoice):
        raise FinanceError("الخطة غير موجودة أو خارج الفروع المسموحة", "not_found", 404)
    branch_id = invoice.branch_id if invoice else customer.branch_id
    if not branch_id:
        raise FinanceError("راجع فرع المستند قبل تعديل الجدولة", "branch_required", 409)
    return plan, invoice, branch_id


@desktop_api_bp.get("/customers/<int:customer_id>/plans/<int:plan_id>")
def customer_schedule_detail(customer_id, plan_id):
    denied = _authorize()
    if denied:
        return denied
    try:
        plan, invoice, _ = _source(customer_id, plan_id)
        return jsonify(success=True, data=_response(plan, invoice))
    except FinanceError as exc:
        return _error(str(exc), exc.status, exc.code)


@desktop_api_bp.post("/customers/<int:customer_id>/plans/<int:plan_id>/schedule")
def customer_schedule_update(customer_id, plan_id):
    denied = _authorize()
    if denied:
        return denied
    body = request.get_json(silent=True)
    try:
        if not isinstance(body, dict) or set(body) != {"idempotency_key", "revision", "reason", "installments"}:
            raise ValueError("بيانات إعادة الجدولة غير صحيحة")
        key = str(UUID(body["idempotency_key"]))
        if not isinstance(body["revision"], str) or not re.fullmatch(r"[0-9a-f]{64}", body["revision"]):
            raise ValueError("حدّث الجدول قبل التعديل")
        reason = body["reason"]
        if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 500:
            raise ValueError("اكتب سبب إعادة الجدولة من 3 إلى 500 حرف")
        requested = body["installments"]
        if not isinstance(requested, list) or not 1 <= len(requested) <= 240:
            raise ValueError("الجدولة تدعم من 1 إلى 240 قسطاً")
        changes = {}
        for row in requested:
            if (not isinstance(row, dict) or set(row) != {"id", "date", "total"}
                    or type(row["id"]) is not int or row["id"] <= 0 or row["id"] in changes
                    or type(row["total"]) is not int or row["total"] < 0 or row["total"] > 10**12
                    or not isinstance(row["date"], str) or len(row["date"]) != 10):
                raise ValueError("أرقام الأقساط ومبالغها ومواعيدها غير صحيحة")
            try:
                due = date.fromisoformat(row["date"])
            except ValueError:
                raise ValueError("تاريخ الاستحقاق غير صحيح") from None
            if due.isoformat() != row["date"]:
                raise ValueError("تاريخ الاستحقاق غير صحيح")
            changes[row["id"]] = (due, row["total"])
    except (ValueError, TypeError, AttributeError) as exc:
        return _error(str(exc) if isinstance(exc, ValueError) else "بيانات إعادة الجدولة غير صحيحة", 400, "validation")

    try:
        plan, invoice, branch_id = _source(customer_id, plan_id, active=False)
        employee = get_current_employee()
        namespace = str(uuid5(NAMESPACE_URL, "finora:desktop:customer-schedule"))
        fingerprint = hashlib.sha256(json.dumps({"customer_id": customer_id, "plan_id": plan_id, **body},
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
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
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            previous = query.first()
            return _receipt_response(previous, employee.id, branch_id, fingerprint) if previous else _error("أعد المحاولة بنفس معرّف العملية", 503, "busy")

        # Match the collection lock order: invoice, plan, installments.
        if invoice:
            invoice = _invoices().filter_by(id=invoice.id).populate_existing().with_for_update().first()
        plan = _plans().filter_by(id=plan_id, customer_id=customer_id).populate_existing().with_for_update().first()
        if not plan:
            raise FinanceError("الفاتورة ملغاة أو الخطة لم تعد متاحة؛ حدّث ملف العميل", "conflict", 409)
        if invoice:
            linked, rows = invoice_schedule(invoice)
            if not linked or linked.id != plan.id:
                raise FinanceError("تغير ربط خطة الأقساط", "conflict", 409)
        else:
            rows = standalone_schedule(plan)
        rows.sort(key=lambda row: (row.sequence, row.id))
        before = _snapshot(plan, rows, invoice)
        if _revision(before) != body["revision"]:
            raise FinanceError("تغير الرصيد أو الجدول؛ حدّث البيانات قبل إعادة الجدولة", "conflict", 409)
        if set(changes) != {row.id for row in rows} or sum(amount for _, amount in changes.values()) != plan.total_amount:
            raise FinanceError("يجب حفظ جميع الأقساط وبنفس مجموع أصل الدين")
        protected = {payment["installment_id"] for payment in before["payment_links"]}
        for row in rows:
            due, amount = changes[row.id]
            paid = int(row.paid_amount or 0)
            if amount == 0 and (row.amount != 0 or row.id not in protected):
                raise FinanceError("القسط الصفري مسموح فقط لتاريخ تحصيل محفوظ ومعكوس")
            if amount < paid or (paid == row.amount and (amount != row.amount or due != row.due_date)):
                raise FinanceError("لا تغيّر القسط المسدد ولا تخفض قسطاً دون مدفوعه")
        for row in rows:
            row.due_date, row.amount = changes[row.id]
            row.status = compute_installment_status(row, _today())
        after = _snapshot(plan, rows, invoice)
        if before != after:
            audit = ActivityLog(employee_id=employee.id, employee_name=employee.name, branch_id=branch_id,
                action="update", category="customers", entity_type="customer_credit_schedule", entity_id=str(plan.id),
                summary=f"إعادة جدولة أقساط العميل #{customer_id} — خطة #{plan.id}", request_method="POST", request_path=request.path)
            audit.set_payload({"reason": reason.strip(), "before": before, "after": after})
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
        current_app.logger.exception("Customer schedule update failed")
        return _error("تعذر حفظ الجدولة؛ لم تحفظ تغييراتها. أعد المحاولة بنفس معرّف العملية", 500, "server_error")
