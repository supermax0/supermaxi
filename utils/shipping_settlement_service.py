"""Helpers for keeping shipping-order settlement records in sync."""
from __future__ import annotations

from extensions import db
from models.shipping_payment import ShippingPayment


PAID_STATUS = "\u0645\u0633\u062f\u062f"
SHIPPING_SETTLED_STATUS = "\u062a\u0645 \u0627\u0644\u062a\u0633\u062f\u064a\u062f"
SHIPPING_SETTLEMENT_ACTION = "\u062a\u0633\u062f\u064a\u062f"


def ensure_paid_shipping_order_settled(order, treasury_account_id: int | None = None):
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

    existing = (
        ShippingPayment.query.filter_by(
            invoice_id=order.id,
            action=SHIPPING_SETTLEMENT_ACTION,
        )
        .order_by(ShippingPayment.id.asc())
        .first()
    )

    order.shipping_status = SHIPPING_SETTLED_STATUS
    note = f"\u0642\u0628\u0636 \u0645\u0646 \u0634\u0631\u0643\u0629 \u0627\u0644\u0634\u062d\u0646 \u0639\u0646 \u0627\u0644\u0637\u0644\u0628 #{order.id}"

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
