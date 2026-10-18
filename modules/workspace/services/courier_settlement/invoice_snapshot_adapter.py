from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional


class InvoiceSnapshotAdapter:
    """Read-only adapter for Finora Invoice model fields."""

    @staticmethod
    def from_invoice(invoice) -> Dict[str, Any]:
        if invoice is None:
            return {}
        phones = InvoiceSnapshotAdapter.get_customer_phones(invoice)
        phone = phones[0] if phones else None
        total = InvoiceSnapshotAdapter.get_total_amount(invoice)
        paid_amount = InvoiceSnapshotAdapter.get_paid_amount(invoice)
        payment_allocations = InvoiceSnapshotAdapter.get_payment_allocations(invoice)
        shipping_barcodes = InvoiceSnapshotAdapter.get_shipping_barcodes(invoice)
        allocated_paid_amount = sum(
            max(int(item.get("amount") or 0), 0)
            for item in payment_allocations
        )
        return {
            "id": invoice.id,
            "order_number": InvoiceSnapshotAdapter.get_order_number(invoice),
            "customer_name": InvoiceSnapshotAdapter.get_customer_name(invoice),
            "customer_phone": phone,
            "customer_phone2": phones[1] if len(phones) > 1 else None,
            "customer_phones": phones,
            "total": total,
            "paid_amount": paid_amount,
            "remaining_amount": max(total - paid_amount, 0),
            "allocated_paid_amount": allocated_paid_amount,
            "payment_verified_in_accounts": bool(
                paid_amount > 0 and abs(allocated_paid_amount - paid_amount) <= 1000
            ),
            "status": InvoiceSnapshotAdapter.get_status(invoice),
            "payment_status": InvoiceSnapshotAdapter.get_payment_status(invoice),
            "note": (getattr(invoice, "note", None) or "").strip(),
            "agent_note": (getattr(invoice, "agent_note", None) or "").strip(),
            "shipping_company_id": getattr(invoice, "shipping_company_id", None),
            "delivery_fee": InvoiceSnapshotAdapter.get_delivery_fee(invoice),
            "created_at": InvoiceSnapshotAdapter.get_created_at(invoice),
            "barcode": getattr(invoice, "barcode", None),
            "shipping_barcode": shipping_barcodes[0] if shipping_barcodes else None,
            "shipping_barcodes": shipping_barcodes,
            "payment_allocations": payment_allocations,
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
    def get_shipping_barcodes(invoice) -> list[str]:
        if invoice is None:
            return []
        try:
            from utils.shipping_barcodes import get_shipping_barcodes_list

            return get_shipping_barcodes_list(invoice)
        except Exception:
            value = str(getattr(invoice, "shipping_barcode", None) or "").strip()
            return [value] if value else []

    @staticmethod
    def get_order_numbers(invoice) -> list[str]:
        if invoice is None:
            return []
        values = [
            getattr(invoice, "barcode", None),
            *InvoiceSnapshotAdapter.get_shipping_barcodes(invoice),
            getattr(invoice, "id", None),
        ]
        result = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in result:
                result.append(text)
        return result

    @staticmethod
    def get_customer_name(invoice) -> str:
        if invoice is None:
            return ""
        return (getattr(invoice, "customer_name", None) or "").strip()

    @staticmethod
    def get_customer_phone(invoice) -> Optional[str]:
        phones = InvoiceSnapshotAdapter.get_customer_phones(invoice)
        return phones[0] if phones else None

    @staticmethod
    def get_customer_phones(invoice) -> list[str]:
        if invoice is None:
            return []
        customer = getattr(invoice, "customer", None)
        if not customer:
            return []
        phones = []
        for attr in ("phone", "phone2"):
            value = str(getattr(customer, attr, None) or "").strip()
            if value and value not in phones:
                phones.append(value)
        return phones

    @staticmethod
    def get_total_amount(invoice) -> int:
        if invoice is None:
            return 0
        return int(getattr(invoice, "total", 0) or 0)

    @staticmethod
    def get_paid_amount(invoice) -> int:
        if invoice is None:
            return 0
        try:
            from utils.cash_calculations import _effective_paid_amount

            return max(int(_effective_paid_amount(invoice) or 0), 0)
        except Exception:
            total = InvoiceSnapshotAdapter.get_total_amount(invoice)
            paid = max(int(getattr(invoice, "paid_amount", 0) or 0), 0)
            return min(paid, total) if total > 0 else paid

    @staticmethod
    def get_remaining_amount(invoice) -> int:
        total = InvoiceSnapshotAdapter.get_total_amount(invoice)
        return max(total - InvoiceSnapshotAdapter.get_paid_amount(invoice), 0)

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
        for attr in ("delivery_fee", "shipping_fee"):
            value = getattr(invoice, attr, None)
            if value not in (None, ""):
                fee = int(value or 0)
                return fee if fee > 0 else None
        try:
            from flask import has_app_context
            from utils.order_shipping import get_shipping_fee_from_invoice

            if not has_app_context():
                return None
            fee = get_shipping_fee_from_invoice(invoice)
            return fee if fee > 0 else None
        except Exception:
            return None

    @staticmethod
    def get_created_at(invoice) -> Optional[str]:
        if invoice is None:
            return None
        dt = getattr(invoice, "created_at", None)
        if isinstance(dt, datetime):
            return dt.date().isoformat()
        return None

    @staticmethod
    def get_payment_allocations(invoice) -> list[Dict[str, Any]]:
        if invoice is None or not getattr(invoice, "id", None):
            return []
        try:
            from sqlalchemy import func

            from extensions import db
            from models.invoice_payment_ledger import InvoicePaymentLedger
            from models.treasury_account import TreasuryAccount
            from utils.payment_ledger import ensure_invoice_payment_ledger_table
            from utils.treasury_helpers import get_default_cash_account

            ensure_invoice_payment_ledger_table()
            rows = (
                db.session.query(
                    InvoicePaymentLedger.treasury_account_id,
                    func.sum(InvoicePaymentLedger.amount_delta),
                )
                .filter(InvoicePaymentLedger.invoice_id == int(invoice.id))
                .group_by(InvoicePaymentLedger.treasury_account_id)
                .all()
            )
            allocations: list[Dict[str, Any]] = []
            for account_id, amount in rows:
                value = int(amount or 0)
                if value <= 0:
                    continue
                account = (
                    TreasuryAccount.query.get(account_id)
                    if account_id is not None
                    else get_default_cash_account()
                )
                allocations.append({
                    "treasury_account_id": account.id if account else account_id,
                    "account_name": account.name if account else "الصندوق",
                    "account_type": account.account_type if account else "cash",
                    "amount": value,
                })
            return allocations
        except Exception:
            return []
