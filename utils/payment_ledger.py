# -*- coding: utf-8 -*-
"""
تسجيل تحصيل الفاتورة بلحظة التسديد، وحساب ربح يوم تقويمي من السجل.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, inspect, or_

from extensions import db

# يوم العمل المحاسبي بتوقيت العراق (يتوافق مع عمل الشركات على finora.company)
BUSINESS_TZ_NAME = "Asia/Baghdad"


def business_today() -> date:
    """تاريخ اليوم التقويمي بتوقيت بغداد."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(BUSINESS_TZ_NAME)).date()
    except Exception:
        try:
            import pytz

            return datetime.now(pytz.timezone(BUSINESS_TZ_NAME)).date()
        except Exception:
            return date.today()


def calendar_day_bounds_utc(day: date):
    """حدود اليوم [start, end) كـ datetime ساذج بـ UTC لمقارنة recorded_at المخزّن بـ utcnow."""
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(BUSINESS_TZ_NAME)
        start_local = datetime(day.year, day.month, day.day, tzinfo=tz)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
        return start_utc, end_utc
    except Exception:
        try:
            import pytz

            tz = pytz.timezone(BUSINESS_TZ_NAME)
            start_local = tz.localize(datetime(day.year, day.month, day.day))
            end_local = start_local + timedelta(days=1)
            start_utc = start_local.astimezone(pytz.UTC).replace(tzinfo=None)
            end_utc = end_local.astimezone(pytz.UTC).replace(tzinfo=None)
            return start_utc, end_utc
        except Exception:
            start = datetime(day.year, day.month, day.day)
            return start, start + timedelta(days=1)


def _ledger_engine():
    """
    محرك قاعدة البيانات الفعلية لجدول الفواتير (مهم مع المستأجرين: كل شركة لها SQLite منفصل).
    يطابق utils/product_schema_guard.py حتى لا يُنشَأ الجدول على Core بينما الاستعلام على المستأجر.
    """
    try:
        from flask import g

        tenant_slug = getattr(g, "tenant", None)
        if tenant_slug:
            from extensions_tenant import get_tenant_engine

            return get_tenant_engine(tenant_slug)
    except Exception:
        pass
    try:
        b = db.session.get_bind()
        if b is not None:
            return b
    except Exception:
        pass
    return db.engine


def ensure_invoice_payment_ledger_table():
    """إنشاء الجدول في قاعدة المستأجر الحالية إذا لم يوجد."""
    from models.invoice_payment_ledger import InvoicePaymentLedger

    bind = _ledger_engine()
    inspector = inspect(bind)
    tables = inspector.get_table_names()
    if "invoice_payment_ledger" not in tables:
        InvoicePaymentLedger.__table__.create(bind=bind, checkfirst=True)


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
    from utils.order_item_costs import exclude_delivery_fee_items

    q = db.session.query(func.sum(OrderItem.cost * OrderItem.quantity)).filter(
        OrderItem.invoice_id == invoice_id,
        exclude_delivery_fee_items(OrderItem),
    )
    return int(q.scalar() or 0)


def _proportional_cogs(invoice_id: int, amount_delta: int, invoice_total: int) -> int:
    if invoice_total <= 0 or amount_delta == 0:
        return 0
    full_cogs = invoice_total_cogs(int(invoice_id))
    if full_cogs <= 0:
        return 0
    return int(round(float(amount_delta) / float(invoice_total) * float(full_cogs)))


def net_profit_for_collection_calendar_day(day: date) -> int:
    """
    صافي ربح يوم تقويمي (حدود اليوم بتوقيت بغداد):

    1) حركات سجل التحصيل خلال اليوم (لحظة التسديد).
    2) فواتير مُحصَّلة أُنشئت ذلك اليوم وليس لها أي حركة في السجل
       (بيانات قديمة أو مسارات لم تسجّل الدفتر — مثل «تم التوصيل» فقط).
    3) تُطرح مصاريف Expense لذلك اليوم.
    """
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from utils.cash_calculations import _effective_paid_amount
    from utils.expense_queries import sum_posted_expenses

    ensure_invoice_payment_ledger_table()
    start_utc, end_utc = calendar_day_bounds_utc(day)

    entries = (
        InvoicePaymentLedger.query.filter(
            InvoicePaymentLedger.recorded_at >= start_utc,
            InvoicePaymentLedger.recorded_at < end_utc,
        ).all()
    )

    expenses_day = sum_posted_expenses(day, day)

    revenue = 0
    cogs = 0
    counted_invoice_ids = set()

    for e in entries:
        delta = int(e.amount_delta)
        revenue += delta
        counted_invoice_ids.add(int(e.invoice_id))
        inv = Invoice.query.get(e.invoice_id)
        if not inv:
            continue
        total = int(inv.total or 0)
        cogs += _proportional_cogs(int(e.invoice_id), delta, total)

    # فواتير مُحصَّلة بتاريخ إنشائها اليوم بدون سجل تحصيل (توافق مع المبيعات الظاهرة)
    RETURN_STATUSES = ["مرتجع", "راجع", "راجعة"]
    CANCELED_STATUSES = ["ملغي"]
    day_invoices = db.session.query(
        Invoice.id,
        Invoice.status,
        Invoice.payment_status,
        Invoice.total,
        Invoice.paid_amount,
    ).filter(
        func.date(Invoice.created_at) == day,
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        or_(
            Invoice.payment_status.is_(None),
            Invoice.payment_status.notin_(RETURN_STATUSES + CANCELED_STATUSES),
        ),
    ).all()

    invoices_with_ledger = set()
    if day_invoices:
        inv_ids = [int(r.id) for r in day_invoices]
        if inv_ids:
            rows = (
                db.session.query(InvoicePaymentLedger.invoice_id)
                .filter(InvoicePaymentLedger.invoice_id.in_(inv_ids))
                .distinct()
                .all()
            )
            invoices_with_ledger = {int(r[0]) for r in rows}

    for inv in day_invoices:
        inv_id = int(inv.id)
        if inv_id in invoices_with_ledger or inv_id in counted_invoice_ids:
            continue
        paid = _effective_paid_amount(inv)
        if paid <= 0:
            continue
        revenue += paid
        cogs += _proportional_cogs(inv_id, paid, int(inv.total or 0))
        counted_invoice_ids.add(inv_id)

    if revenue == 0 and cogs == 0 and not entries:
        # لا بيانات لهذا اليوم
        return int(0 - expenses_day)

    return int(revenue - cogs - expenses_day)
