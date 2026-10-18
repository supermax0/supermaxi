"""Allocation preview and FIFO helpers."""
from __future__ import annotations

from modules.receipts.services.helpers import (
    ALLOC_MANUAL,
    ALLOC_OLDEST,
    ALLOC_ON_ACCOUNT,
    ReceiptError,
    invoice_remaining,
    parse_int,
)


def build_fifo_allocations(open_invoices: list, amount: int) -> list[dict]:
    remaining = int(amount or 0)
    rows = []
    for inv in open_invoices:
        if remaining <= 0:
            break
        due = invoice_remaining(inv)
        if due <= 0:
            continue
        use = min(due, remaining)
        paid_after = int(inv.paid_amount or 0) + use
        total = int(inv.total or 0)
        status_after = "مسدد" if paid_after >= total else "جزئي"
        label = getattr(inv, "invoice_no", None) or str(inv.id)
        rows.append(
            {
                "invoice_id": inv.id,
                "reference": label,
                "amount": use,
                "remaining_before": due,
                "status_after": status_after,
            }
        )
        remaining -= use
    return rows


def build_manual_allocations(open_invoices: list, allocations: list, amount: int) -> list[dict]:
    by_id = {inv.id: inv for inv in open_invoices}
    remaining_budget = int(amount or 0)
    rows = []
    for alloc in allocations or []:
        if remaining_budget <= 0:
            break
        inv_id = parse_int(alloc.get("invoice_id") or alloc.get("reference_id"))
        want = parse_int(alloc.get("amount") or alloc.get("allocated_amount"))
        if inv_id <= 0 or want <= 0:
            continue
        inv = by_id.get(inv_id)
        if not inv:
            raise ReceiptError(f"فاتورة/طلب غير صالح للتخصيص: {inv_id}")
        due = invoice_remaining(inv)
        use = min(want, due, remaining_budget)
        if use <= 0:
            continue
        paid_after = int(inv.paid_amount or 0) + use
        total = int(inv.total or 0)
        status_after = "مسدد" if paid_after >= total else "جزئي"
        label = getattr(inv, "invoice_no", None) or str(inv.id)
        rows.append(
            {
                "invoice_id": inv.id,
                "reference": label,
                "amount": use,
                "remaining_before": due,
                "status_after": status_after,
            }
        )
        remaining_budget -= use
    return rows


def preview_allocations(
    *,
    open_invoices: list,
    amount: int,
    allocation_method: str,
    allocations: list | None = None,
    balance_before: int = 0,
) -> dict:
    method = (allocation_method or ALLOC_OLDEST).strip()
    amount = int(amount or 0)
    if amount <= 0:
        raise ReceiptError("مبلغ القبض يجب أن يكون أكبر من صفر")

    if method == ALLOC_ON_ACCOUNT:
        applied = []
    elif method == ALLOC_MANUAL:
        applied = build_manual_allocations(open_invoices, allocations or [], amount)
    else:
        applied = build_fifo_allocations(open_invoices, amount)

    allocated_total = sum(r["amount"] for r in applied)
    unallocated = max(0, amount - allocated_total)
    balance_after = max(0, int(balance_before) - amount)

    # Cap at outstanding: if overpaying, still allow but clamp display after
    outstanding = int(balance_before)
    if amount > outstanding > 0:
        balance_after = 0

    return {
        "balance_before": int(balance_before),
        "amount": amount,
        "balance_after": int(balance_after),
        "allocation_method": method,
        "allocations": applied,
        "allocated_total": allocated_total,
        "unallocated": unallocated,
        "overpay": max(0, amount - outstanding) if outstanding >= 0 else 0,
    }
