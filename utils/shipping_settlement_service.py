"""Helpers for keeping shipping-order settlement records in sync."""
from __future__ import annotations

from datetime import datetime

from extensions import db
from models.shipping_payment import ShippingPayment


PAID_STATUS = "\u0645\u0633\u062f\u062f"
SHIPPING_SETTLED_STATUS = "\u062a\u0645 \u0627\u0644\u062a\u0633\u062f\u064a\u062f"
SHIPPING_SETTLEMENT_ACTION = "\u062a\u0633\u062f\u064a\u062f"
SHIPPING_RETURN_REVERSAL_ACTION = "عكس تسديد"


def reverse_returned_shipping_settlement(order):
    """Append a signed reversal to each original courier account; keep the collection rows."""
    if order is None:
        return
    from sqlalchemy import func
    rows = db.session.query(
        ShippingPayment.shipping_company_id, ShippingPayment.treasury_account_id,
        ShippingPayment.branch_id, func.sum(ShippingPayment.amount),
    ).execution_options(skip_branch_scope=True).filter(
        ShippingPayment.invoice_id == order.id,
        ShippingPayment.action.in_((SHIPPING_SETTLEMENT_ACTION, SHIPPING_RETURN_REVERSAL_ACTION)),
    ).group_by(ShippingPayment.shipping_company_id, ShippingPayment.treasury_account_id, ShippingPayment.branch_id).all()
    for company_id, account_id, branch_id, amount in rows:
        if int(amount or 0) <= 0:
            continue
        db.session.add(ShippingPayment(
            shipping_company_id=company_id, invoice_id=order.id,
            treasury_account_id=account_id, branch_id=branch_id,
            amount=-int(amount), action=SHIPPING_RETURN_REVERSAL_ACTION,
            note=f"عكس تحصيل شركة النقل لإرجاع الطلب #{order.id}",
        ))


def ensure_paid_shipping_order_settled(
    order,
    treasury_account_id: int | None = None,
    allocations: list[dict] | None = None,
):
    """Create or update the shipping collection row for a paid shipping order."""
    if order is None:
        return None
    if not getattr(order, "shipping_company_id", None):
        return None
    if (getattr(order, "payment_status", None) or "").strip() != PAID_STATUS:
        return None

    amount = int(getattr(order, "paid_amount", 0) or getattr(order, "total", 0) or 0)
    if amount <= 0:
        return None

    existing_rows = (
        ShippingPayment.query.filter_by(
            invoice_id=order.id,
            action=SHIPPING_SETTLEMENT_ACTION,
        )
        .order_by(ShippingPayment.id.asc())
        .all()
    )

    order.shipping_status = SHIPPING_SETTLED_STATUS
    note = f"\u0642\u0628\u0636 \u0645\u0646 \u0634\u0631\u0643\u0629 \u0627\u0644\u0634\u062d\u0646 \u0639\u0646 \u0627\u0644\u0637\u0644\u0628 #{order.id}"

    normalized_allocations = []
    for allocation in allocations or []:
        try:
            account_id = int(allocation.get("treasury_account_id"))
            allocation_amount = int(allocation.get("amount"))
        except (AttributeError, TypeError, ValueError):
            continue
        if account_id > 0 and allocation_amount > 0:
            created_at = allocation.get("created_at")
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    created_at = None
            normalized_allocations.append(
                {
                    "treasury_account_id": account_id,
                    "amount": allocation_amount,
                    "created_at": created_at,
                }
            )

    if normalized_allocations:
        kept_rows = []
        for index, allocation in enumerate(normalized_allocations):
            if index < len(existing_rows):
                payment = existing_rows[index]
            else:
                payment = ShippingPayment(
                    shipping_company_id=order.shipping_company_id,
                    invoice_id=order.id,
                    action=SHIPPING_SETTLEMENT_ACTION,
                )
                db.session.add(payment)
            payment.shipping_company_id = order.shipping_company_id
            payment.amount = allocation["amount"]
            payment.treasury_account_id = allocation["treasury_account_id"]
            payment.note = note
            if allocation.get("created_at") is not None:
                payment.created_at = allocation["created_at"]
            kept_rows.append(payment)

        for extra in existing_rows[len(kept_rows):]:
            db.session.delete(extra)
        return kept_rows[0] if kept_rows else None

    existing = existing_rows[0] if existing_rows else None
    if existing:
        existing.shipping_company_id = order.shipping_company_id
        existing.amount = amount
        if treasury_account_id is not None:
            existing.treasury_account_id = treasury_account_id
        if not existing.note:
            existing.note = note
        return existing

    payment = ShippingPayment(
        shipping_company_id=order.shipping_company_id,
        invoice_id=order.id,
        amount=amount,
        action=SHIPPING_SETTLEMENT_ACTION,
        note=note,
        treasury_account_id=treasury_account_id,
    )
    db.session.add(payment)
    return payment


def resize_paid_shipping_order_settlement(order):
    """Keep split courier collections equal to an edited paid invoice total."""
    if order is None or (getattr(order, "payment_status", None) or "").strip() != PAID_STATUS:
        return None
    rows = (
        ShippingPayment.query.filter_by(
            invoice_id=order.id,
            action=SHIPPING_SETTLEMENT_ACTION,
        )
        .order_by(ShippingPayment.id.asc())
        .all()
    )
    target = max(0, int(getattr(order, "total", 0) or 0))
    if not rows:
        return ensure_paid_shipping_order_settled(order)
    old_total = sum(max(0, int(row.amount or 0)) for row in rows)
    assigned = 0
    for index, row in enumerate(rows):
        if index == len(rows) - 1:
            amount = max(0, target - assigned)
        elif old_total > 0:
            amount = int(round(target * max(0, int(row.amount or 0)) / old_total))
            amount = min(amount, max(0, target - assigned))
        else:
            amount = 0
        assigned += amount
        if amount <= 0:
            db.session.delete(row)
            continue
        row.amount = amount
        row.shipping_company_id = order.shipping_company_id
    order.shipping_status = SHIPPING_SETTLED_STATUS
    return next((row for row in rows if int(row.amount or 0) > 0), None)
