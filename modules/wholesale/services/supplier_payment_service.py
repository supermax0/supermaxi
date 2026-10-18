"""Supplier payments with purchase allocation."""
from __future__ import annotations

from sqlalchemy import or_

from extensions import db
from models.purchase import Purchase
from models.supplier import Supplier
from models.supplier_payment import SupplierPayment
from models.supplier_payment_allocation import SupplierPaymentAllocation
from modules.wholesale.services import journal_hooks, party_ledger_service
from modules.wholesale.services.helpers import (
    WholesaleError,
    normalize_currency,
    parse_date,
    parse_float,
    parse_int,
    resolve_wholesale_treasury_account,
    to_base_amount,
)


def supplier_open_purchases(tenant_id: int | None, supplier_id: int) -> list[Purchase]:
    q = Purchase.query.filter(
        Purchase.supplier_id == supplier_id,
        Purchase.source_module == "wholesale",
        Purchase.deleted_at.is_(None),
        Purchase.status == "confirmed",
    )
    rows = []
    for p in q.order_by(Purchase.purchase_date.asc(), Purchase.id.asc()).all():
        remain = max(0, int(p.grand_total or 0) - int(p.paid_total or 0))
        if remain > 0:
            rows.append(p)
    return rows


def create_payment(tenant_id: int | None, payload: dict, *, employee_id: int | None = None) -> dict:
    supplier_id = parse_int(payload.get("supplier_id"))
    amount = parse_int(payload.get("amount"))
    if supplier_id <= 0:
        raise WholesaleError("اختر المورد")
    if amount <= 0:
        raise WholesaleError("أدخل مبلغ التسديد")

    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        raise WholesaleError("المورد غير موجود")

    currency = normalize_currency(payload.get("currency"))
    exchange_rate = parse_float(payload.get("exchange_rate"), 1.0 if currency == "IQD" else 1500.0)
    entry_date = parse_date(payload.get("date"))
    payment_method = (payload.get("payment_method") or "cash").strip()
    treasury_account = resolve_wholesale_treasury_account(
        payload.get("treasury_account_id"), payment_method
    )
    treasury_account_id = int(treasury_account.id)
    note = (payload.get("note") or payload.get("notes") or "").strip() or None
    allocate_fifo = bool(payload.get("allocate_fifo") or payload.get("auto_allocate"))
    allocations = payload.get("allocations") or []

    balance_before = party_ledger_service.party_balance(tenant_id, "supplier", supplier_id, currency)

    payment = SupplierPayment(
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        amount=amount,
        note=note,
        treasury_account_id=treasury_account_id,
        payment_method=payment_method,
        currency=currency,
        exchange_rate=exchange_rate,
        source_module="wholesale",
        branch_id=treasury_account.branch_id,
    )
    db.session.add(payment)
    db.session.flush()

    remaining = amount
    applied = []

    def _apply(purchase: Purchase, use: int):
        nonlocal remaining
        if use <= 0:
            return
        purchase.paid_total = int(purchase.paid_total or 0) + use
        purchase.remaining_total = max(0, int(purchase.grand_total or 0) - int(purchase.paid_total or 0))
        db.session.add(
            SupplierPaymentAllocation(
                supplier_payment_id=payment.id,
                purchase_id=purchase.id,
                allocation_type="purchase",
                target_key=f"purchase:{purchase.id}",
                amount=use,
            )
        )
        applied.append({"purchase_id": purchase.id, "invoice_no": purchase.invoice_no, "amount": use})
        remaining -= use

    if allocations:
        for alloc in allocations:
            if remaining <= 0:
                break
            pid = parse_int(alloc.get("purchase_id") or alloc.get("invoice_id"))
            alloc_amt = parse_int(alloc.get("amount"))
            purchase = Purchase.query.get(pid)
            if not purchase or purchase.supplier_id != supplier_id or purchase.source_module != "wholesale":
                raise WholesaleError(f"فاتورة شراء غير صالحة: {pid}")
            inv_remain = max(0, int(purchase.grand_total or 0) - int(purchase.paid_total or 0))
            _apply(purchase, min(alloc_amt, inv_remain, remaining))
    elif allocate_fifo:
        for purchase in supplier_open_purchases(tenant_id, supplier_id):
            if remaining <= 0:
                break
            inv_remain = max(0, int(purchase.grand_total or 0) - int(purchase.paid_total or 0))
            _apply(purchase, min(inv_remain, remaining))

    entry = party_ledger_service.add_entry(
        tenant_id,
        party_type="supplier",
        party_id=supplier_id,
        entry_date=entry_date,
        entry_type="payment",
        debit=amount,
        credit=0,
        currency=currency,
        exchange_rate=exchange_rate,
        doc_no=f"PAY-{payment.id}",
        description=note or f"سند تسديد — {supplier.name}",
        reference_type="wholesale_payment",
        reference_id=payment.id,
        created_by=employee_id,
    )

    amount_base = to_base_amount(amount, currency, exchange_rate)
    journal_hooks.post_supplier_payment_journal(
        amount_base=amount_base, reference_id=payment.id, doc_no=entry.doc_no
    )
    db.session.flush()

    balance_after = party_ledger_service.party_balance(tenant_id, "supplier", supplier_id, currency)
    return {
        "id": payment.id,
        "doc_no": entry.doc_no,
        "supplier_id": supplier_id,
        "supplier_name": supplier.name,
        "amount": amount,
        "currency": currency,
        "exchange_rate": exchange_rate,
        "payment_method": payment_method,
        "treasury_account_id": treasury_account_id,
        "allocations": applied,
        "unallocated": remaining,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "note": note,
        "date": entry_date.isoformat(),
    }
