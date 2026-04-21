# -*- coding: utf-8 -*-
"""
تسجيل تحصيل الفاتورة بلحظة التسديد، وحساب ربح يوم تقويمي من السجل.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, inspect

from extensions import db


def ensure_invoice_payment_ledger_table():
    """إنشاء الجدول في قاعدة المستأجر الحالية إذا لم يوجد."""
    from models.invoice_payment_ledger import InvoicePaymentLedger

    bind = db.engine
    inspector = inspect(bind)
    tables = inspector.get_table_names()
    if "invoice_payment_ledger" not in tables:
        InvoicePaymentLedger.__table__.create(bind=bind)


def append_payment_ledger_delta(invoice_id: int, delta: int) -> None:
    """تسجيل فرق التحصيل الفعلي بعد تحديث الفاتورة (في نفس جلسة الحفظ)."""
    if delta == 0:
        return
    ensure_invoice_payment_ledger_table()
    from models.invoice_payment_ledger import InvoicePaymentLedger

    db.session.add(
        InvoicePaymentLedger(
            invoice_id=int(invoice_id),
            amount_delta=int(delta),
            recorded_at=datetime.utcnow(),
        )
    )


def invoice_total_cogs(invoice_id: int) -> int:
    from models.order_item import OrderItem

    q = db.session.query(func.sum(OrderItem.cost * OrderItem.quantity)).filter(
        OrderItem.invoice_id == invoice_id
    )
    return int(q.scalar() or 0)


def net_profit_for_collection_calendar_day(day: date) -> int:
    """
    صافي ربح يوم تقويمي (حدود اليوم عند منتصف الليل بتوقيت السيرفر):

    - إن وُجدت حركات في سجل التحصيل ذلك اليوم: الإيراد = مجموع amount_delta؛
      COGS يتناسب مع كل حركة؛ تُطرح مصاريف Expense ذلك اليوم.
    - إن لم توجد أي حركة ذلك اليوم: الإبقاء على منطق إنشاء الطلب (_net_profit_for_range)
      حتى لا تختفي البيانات التاريخية قبل إنشاء السجل.
    """
    from models.expense import Expense
    from models.invoice_payment_ledger import InvoicePaymentLedger

    ensure_invoice_payment_ledger_table()

    entries = (
        InvoicePaymentLedger.query.filter(
            func.date(InvoicePaymentLedger.recorded_at) == day
        ).all()
    )

    expenses_day = db.session.query(func.sum(Expense.amount)).filter(
        Expense.expense_date.isnot(None),
        func.date(Expense.expense_date) == day,
    ).scalar() or 0
    expenses_day = int(expenses_day or 0)

    if not entries:
        from utils.period_net_profit import net_profit_for_range

        return net_profit_for_range(day, day)

    revenue = sum(int(e.amount_delta) for e in entries)
    cogs = 0
    from models.invoice import Invoice

    for e in entries:
        inv = Invoice.query.get(e.invoice_id)
        if not inv:
            continue
        total = int(inv.total or 0)
        if total <= 0:
            continue
        full_cogs = invoice_total_cogs(int(e.invoice_id))
        if full_cogs <= 0:
            continue
        cogs += int(round(float(e.amount_delta) / float(total) * float(full_cogs)))

    return int(revenue - cogs - expenses_day)
