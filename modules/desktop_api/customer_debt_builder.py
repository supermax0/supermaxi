"""Documented opening receivables: one source, no sale or historical cash replay."""
import json
import re
from uuid import NAMESPACE_URL, uuid5

from flask import current_app, jsonify, request
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, OperationalError

from extensions import db
from models.activity_log import ActivityLog
from models.customer import Customer
from models.customer_credit import CustomerCreditPlan, CustomerInstallment
from modules.desktop_api.customers import _authorize, _scoped, _revision as profile_revision, _today
from modules.desktop_api.customer_plan_builder import _validate, _dates
from modules.desktop_api.customer_schedules import _revision, _response
from modules.desktop_api.routes import desktop_api_bp, _error
from modules.desktop_api.sync import DesktopSyncReceipt
from modules.finance.common import FinanceError, command, require
from modules.finance.models import FinancePolicy, FinanceVoucher
from modules.finance.source_sync import synchronize
from utils.customer_credit_service import compute_installment_status, split_installment_amounts
from utils.financial_period_guard import PeriodClosedError
from utils.permission_checks import get_current_employee


def _customer(customer_id, *, lock=False):
    query = _scoped(Customer.query, Customer).filter_by(id=customer_id)
    row = query.populate_existing().with_for_update().first() if lock else query.first()
    if not row:
        raise FinanceError("العميل غير موجود أو خارج الفروع المسموحة", "not_found", 404)
    return row


def _draft(customer):
    # A preview must not bootstrap finance, migrate balances or create tables.
    record = None
    if inspect(db.session.connection()).has_table(FinancePolicy.__tablename__):
        record = FinancePolicy.query.populate_existing().filter_by(id=1).first()
    settings = json.loads(record.settings) if record else {}
    blocked = ""
    if not customer.branch_id:
        blocked = "اربط العميل بفرع قبل تسجيل الدين"
    elif not all(settings.get(key) for key in ("ledger_live", "opening_migration_complete", "standalone_debts_reviewed")):
        blocked = "اعتمد مراجعة الأرصدة الافتتاحية وفعّل الربط المحاسبي من إعدادات الحسابات أولاً"
    return {"customer_id": customer.id, "total": 0, "paid": 0,
        "revision": _revision({"profile": profile_revision(customer), "settings": settings}),
        "eligible": not blocked, "blocked_reason": blocked}


def _allowed():
    denied = _authorize()
    if denied:
        return denied
    require("finance.view")
    require("finance.settings")


@desktop_api_bp.route("/customers/<int:customer_id>/debts", methods=["GET", "POST"])
def customer_debt_create(customer_id):
    try:
        denied = _allowed()
        if denied:
            return denied
        customer = _customer(customer_id)
        if request.method == "GET":
            return jsonify(success=True, data=_draft(customer))
        body = request.get_json(silent=True)
        extra = {"source_type", "source_reference", "amount"}
        if not isinstance(body, dict) or not extra <= set(body):
            raise FinanceError("بيانات مصدر الدين غير مكتملة")
        base = {key: value for key, value in body.items() if key not in extra}
        _, first = _validate(base)
        dates = list(_dates(first, body["interval"], body["count"]))
        if body["source_type"] != "opening":
            raise FinanceError("المصدر المتاح هنا دين افتتاحي خارج فواتير FINORA")
        amount, reference, reason = body["amount"], body["source_reference"], body["reason"]
        if type(amount) is not int or not body["count"] <= amount <= 2_147_483_647:
            raise FinanceError("أدخل مبلغاً صحيحاً حتى 2,147,483,647 دينار، لا يقل عن عدد الأقساط")
        if not isinstance(reference, str) or not 3 <= len(reference.strip()) <= 80 or re.search(r"[\x00-\x1f\x7f]", reference):
            raise FinanceError("اكتب مرجع المصدر من 3 إلى 80 حرفاً")
        if len(reason.strip()) > 120:
            raise FinanceError("اكتب وصف الدين من 3 إلى 120 حرفاً")
        draft = _draft(customer)
        if not draft["eligible"]:
            raise FinanceError(draft["blocked_reason"], "opening_review", 409)
        # Finance commands serialize on the tenant policy and save their result
        # in the same transaction as the receivable, schedule, journal and audit.
        def create():
            customer = _customer(customer_id, lock=True)
            current = _draft(customer)
            if not current["eligible"]:
                raise FinanceError(current["blocked_reason"], "opening_review", 409)
            if current["revision"] != body["revision"]:
                raise FinanceError("تغيّر العميل أو إعداد الحسابات؛ حمّل المصدر الأحدث", "conflict", 409)
            DesktopSyncReceipt.__table__.create(bind=db.session.connection(), checkfirst=True)
            ActivityLog.__table__.create(bind=db.session.connection(), checkfirst=True)
            namespace = str(uuid5(NAMESPACE_URL, "finora:desktop:opening-debt-source"))
            normalized = " ".join(reference.split()).casefold()
            source_key = str(uuid5(NAMESPACE_URL, f"customer:{customer_id}:source:{normalized}"))
            if DesktopSyncReceipt.query.filter_by(device_id=namespace, operation_id=source_key).first():
                raise FinanceError("هذا المرجع مسجل لهذا العميل؛ راجع كشفه قبل إضافة دين آخر", "duplicate_source", 409)
            employee = get_current_employee()
            db.session.add(DesktopSyncReceipt(device_id=namespace, operation_id=source_key,
                branch_id=customer.branch_id, employee_id=employee.id, fingerprint=_revision(body)))
            plan = CustomerCreditPlan(customer_id=customer_id, entry_type="opening", total_amount=amount,
                paid_amount=0, installments_count=body["count"], employee_id=employee.id,
                description=f"دين افتتاحي · {reference.strip()} · {reason.strip()}")
            db.session.add(plan)
            db.session.flush()
            for index, (value, due) in enumerate(zip(split_installment_amounts(amount, body["count"]), dates), 1):
                row = CustomerInstallment(plan_id=plan.id, sequence=index, due_date=due, amount=value, paid_amount=0)
                row.status = compute_installment_status(row, _today())
                db.session.add(row)
            db.session.flush()
            # Reuse the existing source journal/cursor. Its commit hook will
            # observe the same snapshot, so it cannot post the principal twice.
            synchronize("customer_debt", plan.id)
            voucher = FinanceVoucher.query.filter_by(source_type="customer_debt_auto", source_id=plan.id).order_by(FinanceVoucher.id.desc()).first()
            if not voucher:
                raise FinanceError("راجع ربط حساب الذمم وتسوية الأرصدة الافتتاحية؛ تعذر تكوين قيد مستقل", "opening_review", 409)
            voucher.notes = plan.description
            voucher.payload = json.dumps({**json.loads(voucher.payload), "source_reference": reference.strip(), "opening_source": True}, ensure_ascii=False)
            log = ActivityLog(employee_id=employee.id, employee_name=employee.name, branch_id=customer.branch_id,
                action="create", category="customers", entity_type="customer_credit_schedule", entity_id=str(plan.id),
                summary=f"تسجيل دين افتتاحي للعميل #{customer_id}")
            result = _response(plan, None)
            log.set_payload({"reason": f"{reference.strip()} — {reason.strip()}",
                "source_type": "opening", "source_reference": reference.strip(), "source_voucher_id": voucher.id,
                "before": {"installments": []}, "after": result})
            db.session.add(log)
            db.session.flush()
            return _response(plan, None)
        result = command("customer.debt.create", {"customer_id": customer_id, "branch_id": customer.branch_id, **body}, create)
        return jsonify(success=True, data=result)
    except (ValueError, TypeError, AttributeError, OverflowError) as exc:
        db.session.rollback()
        if isinstance(exc, FinanceError):
            return _error(str(exc), exc.status, exc.code)
        return _error("راجع المبلغ والعدد والتاريخ ووصف الدين ومرجع المصدر", 400, "validation")
    except PeriodClosedError as exc:
        db.session.rollback()
        return _error(str(exc), 409, "period_closed")
    except (IntegrityError, OperationalError):
        db.session.rollback()
        return _error("تعذر تأكيد الحفظ؛ أعد المحاولة بنفس الطلب", 500, "server_error")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Customer opening debt command failed")
        return _error("تعذر تأكيد تسجيل الدين؛ أعد المحاولة بنفس الطلب", 500, "server_error")
