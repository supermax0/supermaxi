from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional


class InvoiceSnapshotAdapter:
    """Read-only adapter for Finora Invoice model fields."""

    @staticmethod
    def from_invoice(invoice) -> Dict[str, Any]:
        if invoice is None:
            return {}
        phone = InvoiceSnapshotAdapter.get_customer_phone(invoice)
        return {
            "id": invoice.id,
            "order_number": InvoiceSnapshotAdapter.get_order_number(invoice),
            "customer_name": InvoiceSnapshotAdapter.get_customer_name(invoice),
            "customer_phone": phone,
            "total": InvoiceSnapshotAdapter.get_total_amount(invoice),
            "status": InvoiceSnapshotAdapter.get_status(invoice),
            "payment_status": InvoiceSnapshotAdapter.get_payment_status(invoice),
            "shipping_company_id": getattr(invoice, "shipping_company_id", None),
            "delivery_fee": InvoiceSnapshotAdapter.get_delivery_fee(invoice),
            "created_at": InvoiceSnapshotAdapter.get_created_at(invoice),
            "barcode": getattr(invoice, "barcode", None),
            "shipping_barcode": getattr(invoice, "shipping_barcode", None),
        }

    @staticmethod
    def get_order_number(invoice) -> str:
        if invoice is None:
            return ""
        for attr in ("barcode", "shipping_barcode"):
            val = getattr(invoice, attr, None)
            if val:
                return str(val).strip()
        return str(invoice.id)

    @staticmethod
    def get_customer_name(invoice) -> str:
        if invoice is None:
            return ""
        return (getattr(invoice, "customer_name", None) or "").strip()

    @staticmethod
    def get_customer_phone(invoice) -> Optional[str]:
        if invoice is None:
            return None
        customer = getattr(invoice, "customer", None)
        if customer and getattr(customer, "phone", None):
            return str(customer.phone).strip()
        return None

    @staticmethod
    def get_total_amount(invoice) -> int:
        if invoice is None:
            return 0
        return int(getattr(invoice, "total", 0) or 0)

    @staticmethod
    def get_status(invoice) -> str:
        if invoice is None:
            return ""
        return (getattr(invoice, "status", None) or "").strip()

    @staticmethod
    def get_payment_status(invoice) -> str:
        if invoice is None:
            return ""
        return (getattr(invoice, "payment_status", None) or "").strip()

    @staticmethod
    def get_delivery_fee(invoice) -> Optional[int]:
        from utils.order_shipping import get_shipping_fee_from_invoice

        fee = get_shipping_fee_from_invoice(invoice)
        return fee if fee > 0 else None

    @staticmethod
    def get_created_at(invoice) -> Optional[str]:
        if invoice is None:
            return None
        dt = getattr(invoice, "created_at", None)
        if isinstance(dt, datetime):
            return dt.date().isoformat()
        return None
