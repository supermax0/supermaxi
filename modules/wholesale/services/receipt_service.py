"""Customer receipts with invoice allocation / FIFO."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_

from extensions import db
from models.account_transaction import AccountTransaction
from models.customer import Customer
from models.invoice import Invoice
from models.invoice_payment_ledger import InvoicePaymentLedger
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


def customer_open_invoices(tenant_id: int | None, customer_id: int) -> list[Invoice]:
    q = Invoice.query.filter(
        Invoice.customer_id == customer_id,
        Invoice.source_module == "wholesale",
        Invoice.deleted_at.is_(None),
        or_(Invoice.is_draft.is_(False), Invoice.is_draft.is_(None)),
    )
    if tenant_id is not None:
        q = q.filter(or_(Invoice.tenant_id == tenant_id, Invoice.tenant_id.is_(None)))
    rows = []
    for inv in q.order_by(Invoice.created_at.asc(), Invoice.id.asc()).all():
        remaining = max(0, int(inv.total or 0) - int(inv.paid_amount or 0))
        if remaining > 0:
            rows.append(inv)
    return rows


def create_receipt(tenant_id: int | None, payload: dict, *, employee_id: int | None = None) -> dict:
    customer_id = parse_int(payload.get("customer_id"))
    amount = parse_int(payload.get("amount"))
    if customer_id <= 0:
        raise WholesaleError("اختر العميل")
    if amount <= 0:
        raise WholesaleError("أدخل مبلغ القبض")

    customer = Customer.query.get(customer_id)
    if not customer:
        raise WholesaleError("العميل غير موجود")

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

    balance_before = party_ledger_service.party_balance(tenant_id, "customer", customer_id, currency)

    remaining_to_allocate = amount
    applied = []

    if allocations:
        for alloc in allocations:
            if remaining_to_allocate <= 0:
                break
            inv_id = parse_int(alloc.get("invoice_id"))
            alloc_amt = parse_int(alloc.get("amount"))
            if inv_id <= 0 or alloc_amt <= 0:
                continue
            inv = Invoice.query.get(inv_id)
            if not inv or inv.customer_id != customer_id or inv.source_module != "wholesale":
                raise WholesaleError(f"فاتورة غير صالحة للتخصيص: {inv_id}")
            inv_remain = max(0, int(inv.total or 0) - int(inv.paid_amount or 0))
            use = min(alloc_amt, inv_remain, remaining_to_allocate)
            if use <= 0:
                continue
            inv.paid_amount = int(inv.paid_amount or 0) + use
            if inv.paid_amount >= int(inv.total or 0):
                inv.payment_status = "مسدد"
            else:
                inv.payment_status = "جزئي"
            ledger = InvoicePaymentLedger(
                tenant_id=tenant_id,
                invoice_id=inv.id,
                treasury_account_id=treasury_account_id,
                amount_delta=use,
                currency=currency,
                exchange_rate=exchange_rate,
                source_module="wholesale",
                note=note,
                payment_method=payment_method,
                recorded_at=datetime.combine(entry_date, datetime.min.time()),
            )
            db.session.add(ledger)
            applied.append({"invoice_id": inv.id, "invoice_no": inv.invoice_no, "amount": use})
            remaining_to_allocate -= use
    elif allocate_fifo:
        for inv in customer_open_invoices(tenant_id, customer_id):
            if remaining_to_allocate <= 0:
                break
            inv_remain = max(0, int(inv.total or 0) - int(inv.paid_amount or 0))
            use = min(inv_remain, remaining_to_allocate)
            if use <= 0:
                continue
            inv.paid_amount = int(inv.paid_amount or 0) + use
            inv.payment_status = "مسدد" if inv.paid_amount >= int(inv.total or 0) else "جزئي"
            ledger = InvoicePaymentLedger(
                tenant_id=tenant_id,
                invoice_id=inv.id,
                treasury_account_id=treasury_account_id,
                amount_delta=use,
                currency=currency,
                exchange_rate=exchange_rate,
                source_module="wholesale",
                note=note,
                payment_method=payment_method,
                recorded_at=datetime.combine(entry_date, datetime.min.time()),
            )
            db.session.add(ledger)
            applied.append({"invoice_id": inv.id, "invoice_no": inv.invoice_no, "amount": use})
            remaining_to_allocate -= use

    # Unallocated remainder still reduces AR via party ledger
    entry = party_ledger_service.add_entry(
        tenant_id,
        party_type="customer",
        party_id=customer_id,
        entry_date=entry_date,
        entry_type="receipt",
        debit=0,
        credit=amount,
        currency=currency,
        exchange_rate=exchange_rate,
        doc_no=f"RCP-{entry_date.strftime('%Y%m%d')}-{customer_id}",
        description=note or f"سند قبض — {customer.name}",
        reference_type="wholesale_receipt",
        reference_id=None,
        created_by=employee_id,
    )
    db.session.flush()
    entry.reference_id = entry.id
    entry.doc_no = f"RCP-{entry.id}"

    # Allocated amounts are already represented by invoice payment-ledger rows.
    # Record only the customer advance/unallocated remainder as a standalone
    # treasury deposit so the same receipt can never be counted twice.
    if remaining_to_allocate > 0:
        db.session.add(
            AccountTransaction(
                branch_id=treasury_account.branch_id,
                type="deposit",
                amount=int(remaining_to_allocate),
                note=f"قبض جملة غير مخصص - سند {entry.doc_no} - {customer.name}",
                treasury_account_id=treasury_account_id,
            )
        )

    amount_base = to_base_amount(amount, currency, exchange_rate)
    journal_hooks.post_receipt_journal(amount_base=amount_base, reference_id=entry.id, doc_no=entry.doc_no)
    db.session.flush()

    balance_after = party_ledger_service.party_balance(tenant_id, "customer", customer_id, currency)
    return {
        "id": entry.id,
        "doc_no": entry.doc_no,
        "customer_id": customer_id,
        "customer_name": customer.name,
        "amount": amount,
        "currency": currency,
        "exchange_rate": exchange_rate,
        "payment_method": payment_method,
        "treasury_account_id": treasury_account_id,
        "allocations": applied,
        "unallocated": remaining_to_allocate,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "note": note,
        "date": entry_date.isoformat(),
    }
