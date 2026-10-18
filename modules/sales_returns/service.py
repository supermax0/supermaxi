"""Atomic return posting; HTTP exposure waits for the complete provider matrix."""
import hashlib
import json
import re
from uuid import uuid4
from flask import g
from sqlalchemy import func, update
from extensions import db
from models.branch import Branch
from models.invoice import Invoice
from models.invoice_payment_ledger import InvoicePaymentLedger
from models.shipping_payment import ShippingPayment
from models.customer_credit import CustomerCreditPlan
from models.treasury_account import TreasuryAccount
from modules.finance.common import actor, audit, dumps, FinanceError, get_row, money, policy, require, tenant_key, text, today
from modules.finance.models import FinancePolicy
from modules.finance.schema import ensure_schema as ensure_finance_schema
from utils.financial_period_guard import assert_date_period_open
from utils.inventory_lots import ensure_inventory_lot_schema
from utils.payment_ledger import ensure_invoice_payment_ledger_table
from utils.stock_movement_guard import ensure_stock_movement_schema
from utils.treasury_schema_guard import ensure_treasury_schema
from utils.treasury_calculations import assert_sufficient_balance
from utils.order_status import RETURN_STATUS, RETURN_STATUSES, CANCELED_STATUSES
from utils.branch_scope import is_general_admin
from utils.permission_checks import employee_can_access_order
from .evidence import capture, encoded
from .facts import returned_quantities
from .inventory import restore_line
from .models import SalesReturn, SalesReturnLine, SalesReturnOrigin, SalesReturnFunding
from .preview import quote
from .schema import ensure_schema
from .collections import from_original, read_default_cash_id, reviewed


def serialize(document):
    return {"id": document.id, "invoice_id": document.invoice_id, "credit": document.credit_amount,
        "cost": document.cost_amount, "debt_relief": document.debt_relief,
        "refund": document.refund_amount, "customer_credit": document.customer_credit}


def _invoice(invoice_id):
    row = get_row(Invoice, invoice_id)
    if not employee_can_access_order(actor(), row):
        raise FinanceError("ليست لديك صلاحية عرض هذا البيع", "forbidden", 403)
    return row


def _return_branch(branch_id):
    branch = Branch.query.filter_by(id=money(branch_id), is_active=True).first()
    if branch is None:
        raise FinanceError("فرع استلام المرتجع غير موجود أو غير فعال")
    employee = actor()
    permitted = employee.branch_id if not is_general_admin(employee) else (
        g.branch.id if getattr(g, "branch", None) and not getattr(g, "view_all_branches", False) else None)
    if permitted is not None and branch.id != permitted:
        raise FinanceError("فرع الاستلام خارج الفروع المسموحة", "forbidden", 403)
    return branch


def _prepare():
    ensure_finance_schema()
    ensure_schema()
    ensure_treasury_schema()
    ensure_inventory_lot_schema()
    ensure_invoice_payment_ledger_table()
    ensure_stock_movement_schema()


def _funding(invoice, proposal, mode, original, payload):
    rows = db.session.query(InvoicePaymentLedger.treasury_account_id,
        InvoicePaymentLedger.payment_method, func.sum(InvoicePaymentLedger.amount_delta)).filter_by(
            invoice_id=invoice.id).group_by(InvoicePaymentLedger.treasury_account_id,
                InvoicePaymentLedger.payment_method).all()
    baseline = from_original(original)
    groups = {}
    for account_id, method, amount in rows:
        resolved = None if method == "finance_offset" else account_id or read_default_cash_id(invoice.branch_id)
        key = (resolved, method == "finance_offset")
        groups[key] = groups.get(key, 0) + int(amount or 0)
    if baseline:
        key = (baseline["treasury_account_id"], False)
        groups[key] = groups.get(key, 0) + baseline["amount"]
    if not groups and int(invoice.paid_amount or 0):
        raise FinanceError("رصيد التحصيل القديم لا يملك مصدر رد مؤرخ؛ يلزم مراجعته أولاً", "source_review", 409)
    if sum(groups.values()) != int(invoice.paid_amount or 0):
        raise FinanceError("عداد التحصيل لا يطابق حركاته؛ راجع المصدر قبل الرد", "source_review", 409)
    if any(account_id is None and not offset and amount > 0 for (account_id, offset), amount in groups.items()):
        raise FinanceError("حساب التحصيل القديم غير محدد؛ راجع مصدره أولاً", "source_review", 409)
    was_reviewed = bool(baseline and reviewed(invoice.id))
    acknowledged = payload.get("acknowledge_undated_collection") is True
    if proposal["excess_collection"] and baseline and not (was_reviewed or acknowledged):
        raise FinanceError("أكد مراجعة رصيد التحصيل القديم غير المؤرخ قبل رده أو تحويله لرصيد", "source_review", 409)
    if not proposal["excess_collection"]:
        return [], 0, was_reviewed or acknowledged
    if mode == "credit":
        if not invoice.customer_id:
            raise FinanceError("اختر صاحب الرصيد قبل ترحيله")
        if invoice.shipping_company_id:
            raise FinanceError("تحويل تحصيل شركة النقل لرصيد يحتاج تسوية عهدتها المرتبطة", "provider_pending", 409)
        return [], proposal["excess_collection"], was_reviewed or acknowledged
    remaining, allocations = proposal["excess_collection"], []
    for (account_id, offset), amount in sorted(groups.items(), key=lambda row: (row[0][0] or 0, row[0][1])):
        if offset or amount <= 0:
            continue
        if account_id is None:
            raise FinanceError("حساب التحصيل القديم غير محدد؛ راجع مصدره أولاً", "source_review", 409)
        value = min(remaining, int(amount))
        account = get_row(TreasuryAccount, account_id)
        if not account.is_active:
            raise FinanceError("حساب التحصيل الأصلي غير فعال؛ راجعه قبل رد المال")
        assert_sufficient_balance(account.id, value)
        allocations.append({"id": account.id, "method": "cash" if account.is_cash else "bank", "amount": value})
        remaining -= value
        if not remaining:
            break
    if remaining:
        raise FinanceError("الجزء المتبقي مسدد برصيد غير نقدي؛ يلزم استعادته إلى رصيد الزبون", "source_review", 409)
    return allocations, 0, was_reviewed or acknowledged


def _proposal(invoice, lines):
    origin = SalesReturnOrigin.query.filter_by(tenant_key=tenant_key(), invoice_id=invoice.id).first()
    original = json.loads(origin.snapshot) if origin else capture(invoice)
    from utils.cash_calculations import _effective_paid_amount
    if _effective_paid_amount(invoice) != int(invoice.paid_amount or 0):
        raise FinanceError("عداد التحصيل لا يطابق حالة البيع؛ راجع المصدر قبل الرد", "source_review", 409)
    before = returned_quantities(invoice.id)
    proposal = quote(invoice, lines, original=original, returned_quantities=before)
    proposal["undated_collection"] = from_original(original)
    payments = [(row.id, row.amount_delta, row.treasury_account_id, row.payment_method)
        for row in InvoicePaymentLedger.query.filter_by(invoice_id=invoice.id).order_by(InvoicePaymentLedger.id)]
    proposal["preview_token"] = hashlib.sha256(dumps({"original": proposal["original_hash"],
        "remaining": before, "total": invoice.total, "paid": invoice.paid_amount,
        "status": invoice.status, "payments": payments, "lines": proposal["lines"]}).encode("utf-8")).hexdigest()
    return origin, original, before, proposal


def preview(invoice_id, lines):
    require("return_orders")
    _prepare()
    return _proposal(_invoice(invoice_id), lines)[3]


def _post_locked(payload):
    if not db.session.info.get("sales_return_atomic") or not db.session.info.get("finance_atomic"):
        raise FinanceError("ترحيل المرتجع يجب أن يكون داخل العملية المالية", "atomicity_guard", 409)
    require("return_orders")
    tenant = tenant_key()
    key = text(payload.get("operation_id"), 80, True)
    if not re.fullmatch(r"[A-Za-z0-9_-]{12,80}", key):
        raise FinanceError("مفتاح العملية غير صحيح")
    fingerprint = hashlib.sha256(dumps(payload).encode("utf-8")).hexdigest()
    db.session.execute(update(FinancePolicy).where(FinancePolicy.id == 1).values(revision=FinancePolicy.revision+1))
    previous = SalesReturn.query.filter_by(tenant_key=tenant, operation_key=key).first()
    if previous:
        get_row(Invoice, previous.invoice_id)
        if previous.fingerprint != fingerprint or previous.created_by != actor().id:
            raise FinanceError("المفتاح مستخدم لطلب أو موظف آخر", "idempotency_conflict", 409)
        return serialize(previous), False
    invoice = _invoice(payload.get("invoice_id"))
    if invoice.status in list(RETURN_STATUSES) + list(CANCELED_STATUSES) or invoice.status == "تم الطلب":
        raise FinanceError("اختر بيعاً منفذاً وقائماً للمرتجع")
    if CustomerCreditPlan.query.filter_by(invoice_id=invoice.id).first():
        raise FinanceError("البيع مقسط؛ يلزم تحديث أصل الخطة والتحصيل المرتبط به", "provider_pending", 409)
    assert_date_period_open(today(), "استلام مرتجع بيع")
    origin, original, before, proposal = _proposal(invoice, payload.get("lines"))
    if payload.get("preview_token") != proposal["preview_token"]:
        raise FinanceError("تغير أصل البيع أو التحصيل أو المرتجع السابق؛ أعد المعاينة", "conflict", 409)
    if proposal["credit"] > policy()["approval_limit"]:
        require("finance.approve_large")
    mode = payload.get("refund_mode", "cash")
    if mode not in {"cash", "credit"}:
        raise FinanceError("اختر رد المال أو رصيد الزبون")
    allocations, credit, collection_reviewed = _funding(invoice, proposal, mode, original, payload)
    from .funding import plan as funding_plan
    tenders = funding_plan(invoice, original, allocations, credit)
    branch = _return_branch(payload.get("return_branch_id") or invoice.branch_id)
    reason = text(payload.get("reason"), 1500, True)
    if origin is None:
        value, digest = encoded(original)
        origin = SalesReturnOrigin(tenant_key=tenant, invoice_id=invoice.id, created_by=actor().id,
            snapshot=value, snapshot_hash=digest)
        db.session.add(origin)
        db.session.flush()
    location_id = money(payload["return_location_id"]) if payload.get("return_location_id") is not None else None
    document = SalesReturn(tenant_key=tenant, origin_id=origin.id, invoice_id=invoice.id,
        branch_id=branch.id, return_location_id=location_id, customer_id=invoice.customer_id,
        operation_key=key, fingerprint=fingerprint, kind="return", reason=reason, created_by=actor().id,
        credit_amount=proposal["credit"], cost_amount=proposal["cost"], debt_relief=proposal["debt_relief"],
        excess_collection=proposal["excess_collection"], refund_amount=sum(row["amount"] for row in allocations),
        customer_credit=credit, evidence=dumps({"proposal": proposal, "refunds": allocations,
            "undated_collection_reviewed": collection_reviewed, "funding": tenders}))
    db.session.add(document)
    db.session.flush()
    for tender in tenders:
        db.session.add(SalesReturnFunding(document_id=document.id,
            origin_id=origin.id if tender["source_ledger_id"] is None else None, **tender))
    sources = {row["id"]: row for row in original["lines"]}
    for item in proposal["lines"]:
        line = SalesReturnLine(document_id=document.id, order_item_id=item["id"], quantity=item["quantity"],
            credit_amount=item["credit"], cost_amount=item["cost"], snapshot=dumps(sources[item["id"]]))
        db.session.add(line)
        db.session.flush()
        restore_line(document, line, sources[item["id"]], item)
    invoice.total = proposal["sale_remaining"]
    invoice.paid_amount = proposal["collection_remaining"]
    marker = f"sales_returns:{document.id}"
    for allocation in allocations:
        db.session.add(InvoicePaymentLedger(invoice_id=invoice.id, branch_id=invoice.branch_id,
            treasury_account_id=allocation["id"], payment_method=allocation["method"],
            amount_delta=-allocation["amount"], source_module=marker, note=reason))
        if invoice.shipping_company_id:
            db.session.add(ShippingPayment(invoice_id=invoice.id, shipping_company_id=invoice.shipping_company_id,
                branch_id=invoice.branch_id, treasury_account_id=allocation["id"],
                amount=-allocation["amount"], action="عكس تسديد", note=f"مرتجع جزئي #{document.id}"))
    if credit:
        db.session.add(InvoicePaymentLedger(invoice_id=invoice.id, branch_id=invoice.branch_id,
            amount_delta=-credit, payment_method="finance_offset", source_module=marker, note=reason))
    complete = all(before.get(row["id"], 0) + sum(item["quantity"] for item in proposal["lines"]
        if item["id"] == row["id"]) == row["quantity"] for row in original["lines"] if row["physical"])
    if complete:
        invoice.status = invoice.payment_status = RETURN_STATUS
        invoice.shipping_status = RETURN_STATUS
        invoice.stock_is_deducted = False
        from utils.order_lifecycle import clear_order_barcodes
        clear_order_barcodes(invoice)
    else:
        invoice.payment_status = "مسدد" if invoice.paid_amount == invoice.total else "جزئي" if invoice.paid_amount else "غير مسدد"
    from utils.payroll_service import sync_commission_line_for_invoice
    sync_commission_line_for_invoice(invoice)
    audit("sales_return.post", "sales_return", document, {"invoice_id": invoice.id, "credit": proposal["credit"]})
    return serialize(document), True


def return_remaining(invoice, *, branch_id=None, location_id=None):
    """Post only the remainder; the existing lifecycle caller owns the commit.

    Used only when a saved origin already exists, so no schema preparation or
    source replacement may commit the caller's batch partway through.
    """
    require("return_orders")
    flags = ("finance_atomic", "sales_return_atomic")
    previous = {flag: db.session.info.get(flag) for flag in flags}
    try:
        db.session.info.update(finance_atomic=True, sales_return_atomic=True)
        with db.session.begin_nested():
            db.session.execute(update(FinancePolicy).where(FinancePolicy.id == 1).values(revision=FinancePolicy.revision+1))
            origin = SalesReturnOrigin.query.filter_by(tenant_key=tenant_key(), invoice_id=invoice.id).one()
            original = json.loads(origin.snapshot)
            before = returned_quantities(invoice.id)
            lines = [{"id": row["id"], "quantity": row["quantity"]-before.get(row["id"], 0)}
                for row in original["lines"] if row["physical"] and row["quantity"] > before.get(row["id"], 0)]
            proposal = _proposal(invoice, lines)[3]
            result, _ = _post_locked({"operation_id": uuid4().hex, "invoice_id": invoice.id,
                "lines": lines, "preview_token": proposal["preview_token"],
                "reason": "ترجيع كامل الكمية المتبقية", "return_branch_id": branch_id or invoice.branch_id,
                "return_location_id": location_id, "refund_mode": "cash"})
            invoice.shipping_status = RETURN_STATUS
            db.session.flush()
        return result
    finally:
        for flag, value in previous.items():
            if value is None:
                db.session.info.pop(flag, None)
            else:
                db.session.info[flag] = value


def execute(payload):
    require("return_orders")
    if db.session.info.get("finance_atomic"):
        raise FinanceError("العملية المالية الخارجية يجب أن تملك الحفظ", "atomicity_guard", 409)
    _prepare()
    try:
        db.session.info.update(finance_atomic=True, sales_return_atomic=True)
        result, created = _post_locked(payload)
        if created:
            db.session.info["finance_commit_allowed"] = True
            db.session.commit()
        else:
            db.session.rollback()
        return result
    except Exception:
        db.session.rollback()
        raise
    finally:
        for flag in ("finance_atomic", "finance_commit_allowed", "sales_return_atomic"):
            db.session.info.pop(flag, None)
