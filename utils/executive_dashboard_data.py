"""
Executive dashboard data helpers — treasury, credit, alerts.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func

from extensions import db
from models.customer_credit import CustomerInstallment
from models.invoice import Invoice
from utils.accounting_calculations import calculate_accounts_receivable
from utils.cash_calculations import _effective_paid_amount
from utils.customer_credit_service import compute_installment_status
from utils.treasury_calculations import (
    calculate_total_liquidity,
    calculate_treasury_balance,
    list_treasury_accounts,
)
from utils.treasury_helpers import get_default_cash_account
from utils.treasury_schema_guard import ensure_treasury_schema

RETURN_STATUSES = ["مرتجع", "راجع", "راجعة"]
CANCELED_STATUSES = ["ملغي"]


def get_treasury_summary() -> dict:
    """Cash box, bank totals, per-account balances."""
    ensure_treasury_schema()
    accounts = list_treasury_accounts()
    default_cash = get_default_cash_account()
    treasury_accounts = []
    bank_total = 0

    for acc in accounts:
        balance = calculate_treasury_balance(acc.id)
        if not acc.is_cash:
            bank_total += balance
        treasury_accounts.append({
            "id": acc.id,
            "name": acc.name,
            "account_type": acc.account_type or ("cash" if acc.is_cash else "bank"),
            "balance": int(balance),
            "is_default": bool(acc.is_default),
        })

    cash_box_balance = calculate_treasury_balance(default_cash.id) if default_cash else 0
    total_liquidity = calculate_total_liquidity()

    return {
        "total_liquidity": int(total_liquidity),
        "cash_box_balance": int(cash_box_balance),
        "bank_total": int(bank_total),
        "treasury_accounts": treasury_accounts,
    }


def _invoices_for_range(date_from: date, date_to: date):
    return db.session.query(
        Invoice.id,
        Invoice.status,
        Invoice.payment_status,
        Invoice.total,
        Invoice.paid_amount,
    ).filter(
        func.date(Invoice.created_at) >= date_from,
        func.date(Invoice.created_at) <= date_to,
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        Invoice.payment_status.notin_(RETURN_STATUSES),
    ).all()


def _cash_credit_split(invoices) -> tuple[int, int]:
    cash_sales = sum(_effective_paid_amount(inv) for inv in invoices)
    credit_sales = sum(
        max(int(inv.total or 0) - _effective_paid_amount(inv), 0)
        for inv in invoices
    )
    return int(cash_sales), int(credit_sales)


def get_credit_executive_summary(today: date | None = None, collection_rate: int = 0) -> dict:
    """Receivables, cash/credit sales today & month, overdue installments."""
    today = today or date.today()
    month_start = today.replace(day=1)

    receivables = int(calculate_accounts_receivable() or 0)

    today_invoices = _invoices_for_range(today, today)
    month_invoices = _invoices_for_range(month_start, today)
    cash_sales_today, credit_sales_today = _cash_credit_split(today_invoices)
    _, credit_sales_month = _cash_credit_split(month_invoices)

    overdue_count = 0
    overdue_amount = 0
    installments = CustomerInstallment.query.all()
    for inst in installments:
        status = compute_installment_status(inst, today)
        if status == "overdue":
            remaining = max(0, int(inst.amount or 0) - int(inst.paid_amount or 0))
            if remaining > 0:
                overdue_count += 1
                overdue_amount += remaining

    return {
        "receivables": receivables,
        "credit_sales_today": credit_sales_today,
        "credit_sales_month": credit_sales_month,
        "cash_sales_today": cash_sales_today,
        "overdue_installments_count": overdue_count,
        "overdue_installments_amount": int(overdue_amount),
        "collection_rate": int(collection_rate),
    }


def get_executive_alerts(
    overdue_installments_count: int = 0,
    overdue_installments_amount: int = 0,
    overdue_orders_fn=None,
) -> list[dict]:
    """Build executive alert list for sidebar."""
    alerts: list[dict] = []

    if overdue_installments_count > 0:
        alerts.append({
            "type": "credit_overdue",
            "message": f"{overdue_installments_count} قسط متأخر بمبلغ {overdue_installments_amount:,} د.ع",
            "severity": "critical" if overdue_installments_count >= 3 else "warning",
        })

    if overdue_orders_fn:
        try:
            overdue_orders = overdue_orders_fn(min_days=7, limit=5)
            if overdue_orders:
                critical = sum(1 for o in overdue_orders if o.get("severity") == "critical")
                count = len(overdue_orders)
                alerts.append({
                    "type": "orders_overdue",
                    "message": f"{count} طلب متأخر{' (' + str(critical) + ' حرج)' if critical else ''}",
                    "severity": "critical" if critical else "warning",
                })
        except Exception:
            pass

    return alerts
