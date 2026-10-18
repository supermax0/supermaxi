"""Create / cancel / serialize receipts."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import or_

from extensions import db
from models.invoice import Invoice
from models.receipt import Receipt, ReceiptAllocation
from modules.receipts.services import allocation as allocation_svc
from modules.receipts.services import journal as journal_svc
from modules.receipts.services import source_summary as summary_svc
from modules.receipts.services.helpers import (
    ALLOC_ON_ACCOUNT,
    SOURCE_SHIPPING,
    STATUS_ACTIVE,
    STATUS_CANCELLED,
    ReceiptError,
    next_receipt_number,
    parse_date,
    parse_int,
    resolve_treasury_account,
    set_payment_status,
)
from utils.payment_ledger import append_payment_ledger_delta


def create_receipt(tenant_id: int | None, payload: dict, *, employee_id: int | None = None) -> dict:
    source_type = (payload.get("source_type") or "").strip()
    source_id = parse_int(payload.get("source_id"))
    amount = parse_int(payload.get("amount"))
    allocation_method = (payload.get("allocation_method") or "oldest_first").strip()
    payment_method = (payload.get("payment_method") or "cash").strip()
    reference_number = (payload.get("reference_number") or "").strip() or None
    notes = (payload.get("notes") or payload.get("note") or "").strip() or None
    receipt_date = parse_date(payload.get("receipt_date") or payload.get("date"))
    idempotency_key = (payload.get("idempotency_key") or "").strip() or None

    if not source_type or source_id <= 0:
        raise ReceiptError("اختر الجهة")
    if amount <= 0:
        raise ReceiptError("أدخل مبلغ القبض")

    if idempotency_key:
        existing = Receipt.query.filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return receipt_to_dict(existing, include_allocations=True)

    source, source_name, _phone = summary_svc.resolve_source(source_type, source_id)
    opens = summary_svc.open_invoices_for_source(source_type, source_id)
    balance_before = sum(
        max(0, int(i.total or 0) - int(i.paid_amount or 0)) for i in opens
    )

    if balance_before <= 0:
        raise ReceiptError("لا توجد ذمة مستحقة للقبض")
    if amount > balance_before:
        raise ReceiptError(
            f"مبلغ القبض أكبر من الذمة المستحقة ({balance_before:,} د.ع)"
        )
    if allocation_method == ALLOC_ON_ACCOUNT:
        raise ReceiptError(
            "القبض على الحساب غير متاح قبل تفعيل حساب الدفعات المقدمة؛ وزّع المبلغ على فاتورة"
        )

    preview = allocation_svc.preview_allocations(
        open_invoices=opens,
        amount=amount,
        allocation_method=allocation_method,
        allocations=payload.get("allocations") or [],
        balance_before=balance_before,
    )
    if int(preview.get("allocated_total") or 0) != amount:
        raise ReceiptError("يجب توزيع كامل مبلغ القبض على الفواتير المختارة")

    treasury = resolve_treasury_account(payload.get("treasury_account_id"), payment_method)

    receipt = Receipt(
        tenant_id=tenant_id,
        branch_id=getattr(source, "branch_id", None) or getattr(treasury, "branch_id", None),
        receipt_number=f"TMP-{uuid4().hex[:16]}",
        source_type=source_type,
        source_id=source_id,
        source_name=source_name,
        amount=amount,
        payment_method=payment_method,
        treasury_account_id=treasury.id,
        receipt_date=receipt_date,
        reference_number=reference_number,
        notes=notes,
        allocation_method=allocation_method,
        status=STATUS_ACTIVE,
        balance_before=balance_before,
        balance_after=preview["balance_after"],
        created_by=employee_id,
        idempotency_key=idempotency_key,
    )
    db.session.add(receipt)
    db.session.flush()
    receipt.receipt_number = next_receipt_number()

    recorded_at = datetime.combine(receipt_date, datetime.min.time())
    applied = []

    if allocation_method != ALLOC_ON_ACCOUNT:
        for row in preview["allocations"]:
            inv_id = row["invoice_id"]
            use = int(row["amount"])
            inv = (
                db.session.query(Invoice)
                .filter(Invoice.id == inv_id)
                .with_for_update()
                .first()
            )
            if not inv:
                raise ReceiptError(f"الطلب #{inv_id} غير موجود")
            remain = max(0, int(inv.total or 0) - int(inv.paid_amount or 0))
            use = min(use, remain)
            if use <= 0:
                continue
            inv.paid_amount = int(inv.paid_amount or 0) + use
            set_payment_status(inv)
            append_payment_ledger_delta(
                inv.id,
                use,
                treasury.id,
                recorded_at=recorded_at,
                source_module=f"receipts:{receipt.id}",
                payment_method=payment_method,
                note=(
                    f"سند قبض {receipt.receipt_number} — {notes}"
                    if notes
                    else f"سند قبض {receipt.receipt_number}"
                ),
            )
            alloc = ReceiptAllocation(
                tenant_id=tenant_id,
                receipt_id=receipt.id,
                reference_type="invoice",
                reference_id=inv.id,
                reference_label=row.get("reference") or str(inv.id),
                allocated_amount=use,
            )
            db.session.add(alloc)
            applied.append(
                {
                    "invoice_id": inv.id,
                    "reference": alloc.reference_label,
                    "amount": use,
                    "status_after": inv.payment_status,
                }
            )

            if source_type == SOURCE_SHIPPING:
                from models.shipping_payment import ShippingPayment

                db.session.add(
                    ShippingPayment(
                        branch_id=inv.branch_id,
                        shipping_company_id=source_id,
                        invoice_id=inv.id,
                        amount=use,
                        action="تسديد",
                        note=f"سند قبض {receipt.receipt_number}",
                        treasury_account_id=treasury.id,
                        created_at=recorded_at,
                    )
                )
                if (inv.payment_status or "") == "مسدد":
                    inv.shipping_status = "تم التسديد"

    if sum(int(row["amount"]) for row in applied) != amount:
        raise ReceiptError("تغير رصيد إحدى الفواتير أثناء الحفظ؛ أعد المحاولة")

    je = journal_svc.post_receipt_journal(
        amount=amount,
        receipt_id=receipt.id,
        treasury=treasury,
        doc_no=receipt.receipt_number,
        entry_date=recorded_at,
        employee_id=employee_id,
    )
    if je:
        receipt.journal_entry_id = je.id

    db.session.flush()

    opens_after = summary_svc.open_invoices_for_source(source_type, source_id)
    balance_after = sum(
        max(0, int(i.total or 0) - int(i.paid_amount or 0)) for i in opens_after
    )
    receipt.balance_after = balance_after

    try:
        from utils.activity_logger import log_activity

        log_activity(
            "create",
            "receipts",
            f"إنشاء سند قبض {receipt.receipt_number}",
            entity_type="receipt",
            entity_id=receipt.id,
            payload={
                "receipt_number": receipt.receipt_number,
                "source_type": source_type,
                "source_id": source_id,
                "amount": amount,
            },
            commit=False,
        )
    except Exception:
        pass

    return {
        "id": receipt.id,
        "receipt_number": receipt.receipt_number,
        "source_type": source_type,
        "source_id": source_id,
        "source_name": source_name,
        "amount": amount,
        "payment_method": payment_method,
        "treasury_account_id": treasury.id,
        "allocations": applied,
        "unallocated": preview.get("unallocated", 0),
        "balance_before": balance_before,
        "balance_after": balance_after,
        "status": receipt.status,
        "receipt_date": receipt_date.isoformat(),
    }


def cancel_receipt(
    receipt_id: int,
    *,
    employee_id: int | None = None,
    reason: str | None = None,
) -> dict:
    receipt = Receipt.query.get(receipt_id)
    if not receipt:
        raise ReceiptError("سند القبض غير موجود")
    if receipt.status == STATUS_CANCELLED:
        raise ReceiptError("السند ملغى مسبقاً")

    reason = (reason or "").strip()
    if not reason:
        raise ReceiptError("أدخل سبب الإلغاء")

    for alloc in sorted(receipt.allocations, key=lambda a: a.id, reverse=True):
        if alloc.reference_type != "invoice":
            continue
        inv = (
            db.session.query(Invoice)
            .filter(Invoice.id == alloc.reference_id)
            .with_for_update()
            .first()
        )
        if not inv:
            continue
        use = int(alloc.allocated_amount or 0)
        if use <= 0:
            continue
        # A return/cancellation elsewhere may already have reversed the
        # invoice collection. Never drive the invoice ledger below its actual
        # collected amount when this receipt is cancelled afterwards.
        reversible = min(use, max(0, int(inv.paid_amount or 0)))
        inv.paid_amount = max(0, int(inv.paid_amount or 0) - reversible)
        set_payment_status(inv)
        if reversible > 0:
            append_payment_ledger_delta(
                inv.id,
                -reversible,
                receipt.treasury_account_id,
                recorded_at=datetime.utcnow(),
                source_module=f"receipts:{receipt.id}",
                payment_method=receipt.payment_method,
                note=f"إلغاء سند قبض {receipt.receipt_number}",
            )
        if receipt.source_type == SOURCE_SHIPPING:
            from models.shipping_payment import ShippingPayment

            ShippingPayment.query.filter_by(
                invoice_id=inv.id,
                shipping_company_id=receipt.source_id,
                action="تسديد",
                note=f"سند قبض {receipt.receipt_number}",
            ).delete(synchronize_session=False)
            if (inv.payment_status or "") != "مسدد":
                if (inv.shipping_status or "") == "تم التسديد":
                    inv.shipping_status = "قيد الشحن"

    rev = None
    if receipt.journal_entry_id:
        rev = journal_svc.reverse_receipt_journal(
            amount=int(receipt.amount or 0),
            receipt_id=receipt.id,
            treasury=receipt.treasury_account,
            doc_no=receipt.receipt_number,
            employee_id=employee_id,
        )
    if rev:
        receipt.reverse_journal_entry_id = rev.id

    receipt.status = STATUS_CANCELLED
    receipt.cancelled_by = employee_id
    receipt.cancelled_at = datetime.utcnow()
    receipt.cancel_reason = reason
    db.session.flush()

    try:
        from utils.activity_logger import log_activity

        log_activity(
            "cancel",
            "receipts",
            f"إلغاء سند قبض {receipt.receipt_number}",
            entity_type="receipt",
            entity_id=receipt.id,
            payload={"receipt_number": receipt.receipt_number, "reason": reason},
            commit=False,
        )
    except Exception:
        pass

    return receipt_to_dict(receipt, include_allocations=True)


def receipt_to_dict(receipt: Receipt, *, include_allocations: bool = False) -> dict:
    data = {
        "id": receipt.id,
        "receipt_number": receipt.receipt_number,
        "source_type": receipt.source_type,
        "source_id": receipt.source_id,
        "source_name": receipt.source_name,
        "amount": int(receipt.amount or 0),
        "payment_method": receipt.payment_method,
        "treasury_account_id": receipt.treasury_account_id,
        "treasury_account_name": receipt.treasury_account.name
        if receipt.treasury_account
        else None,
        "receipt_date": receipt.receipt_date.isoformat() if receipt.receipt_date else None,
        "reference_number": receipt.reference_number,
        "notes": receipt.notes,
        "allocation_method": receipt.allocation_method,
        "status": receipt.status,
        "balance_before": int(receipt.balance_before or 0),
        "balance_after": int(receipt.balance_after or 0),
        "created_by": receipt.created_by,
        "creator_name": receipt.creator.name if receipt.creator else None,
        "cancelled_by": receipt.cancelled_by,
        "cancelled_at": receipt.cancelled_at.isoformat() if receipt.cancelled_at else None,
        "cancel_reason": receipt.cancel_reason,
        "created_at": receipt.created_at.isoformat() if receipt.created_at else None,
        "journal_entry_id": receipt.journal_entry_id,
    }
    if include_allocations:
        data["allocations"] = [
            {
                "id": a.id,
                "reference_type": a.reference_type,
                "reference_id": a.reference_id,
                "reference": a.reference_label or str(a.reference_id),
                "amount": int(a.allocated_amount or 0),
            }
            for a in receipt.allocations
        ]
    return data


def list_receipts_query(filters: dict | None = None):
    filters = filters or {}
    q = Receipt.query
    status = (filters.get("status") or "").strip()
    if status:
        q = q.filter(Receipt.status == status)
    source_type = (filters.get("source_type") or "").strip()
    if source_type:
        q = q.filter(Receipt.source_type == source_type)
    source_id = parse_int(filters.get("source_id"))
    if source_id > 0:
        q = q.filter(Receipt.source_id == source_id)
    payment_method = (filters.get("payment_method") or "").strip()
    if payment_method:
        q = q.filter(Receipt.payment_method == payment_method)
    created_by = parse_int(filters.get("created_by"))
    if created_by > 0:
        q = q.filter(Receipt.created_by == created_by)
    treasury_id = parse_int(filters.get("treasury_account_id"))
    if treasury_id > 0:
        q = q.filter(Receipt.treasury_account_id == treasury_id)
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    if date_from:
        q = q.filter(Receipt.receipt_date >= parse_date(date_from))
    if date_to:
        q = q.filter(Receipt.receipt_date <= parse_date(date_to))
    search = (filters.get("q") or filters.get("search") or "").strip()
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Receipt.receipt_number.ilike(like),
                Receipt.source_name.ilike(like),
                Receipt.reference_number.ilike(like),
            )
        )
    return q.order_by(Receipt.id.desc())


def dashboard_stats(filters: dict | None = None) -> dict:
    from sqlalchemy import func

    filters = filters or {}
    f2 = dict(filters)
    f2.pop("status", None)
    all_q = list_receipts_query(f2)
    active = all_q.filter(Receipt.status == STATUS_ACTIVE)
    cancelled = all_q.filter(Receipt.status == STATUS_CANCELLED)

    total_amount = active.with_entities(func.coalesce(func.sum(Receipt.amount), 0)).scalar() or 0
    by_type = dict(
        active.with_entities(Receipt.source_type, func.coalesce(func.sum(Receipt.amount), 0))
        .group_by(Receipt.source_type)
        .all()
    )
    return {
        "total_amount": int(total_amount),
        "count": active.count(),
        "cancelled_count": cancelled.count(),
        "customer_amount": int(by_type.get("customer") or 0),
        "courier_amount": int(by_type.get("courier") or 0),
        "shipping_amount": int(by_type.get("shipping_company") or 0),
    }
