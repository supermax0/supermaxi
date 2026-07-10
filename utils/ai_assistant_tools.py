# -*- coding: utf-8 -*-
"""
أدوات القراءة (Read-only Tools) لمساعد Finora المالي.

كل أداة هنا استعلام قراءة فقط من قاعدة بيانات الشركة الحالية (tenant)،
تُستدعى من حلقة Tool Calling في utils/ai_assistant_service.py عندما
يطلبها GPT، وتُرجع JSON بأرقام حقيقية.

القواعد:
- لا توجد أي كتابة/تعديل على قاعدة البيانات هنا إطلاقاً.
- كل أداة مربوطة بصلاحيات _assistant_read_scope (any-of).
- التواريخ الواردة من GPT تُفسَّر بتوقيت بغداد (Asia/Baghdad) ثم تُحوَّل
  إلى UTC عند مقارنة created_at المخزّن بـ utcnow.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import func, or_

from extensions import db
from models.account_transaction import AccountTransaction
from models.branch import Branch, BranchStock
from models.customer import Customer
from models.customer_credit import CustomerCreditPlan, CustomerInstallment
from models.employee import Employee
from models.expense import Expense
from models.invoice import Invoice
from models.invoice_payment_ledger import InvoicePaymentLedger
from models.order_item import OrderItem
from models.product import Product
from models.purchase import Purchase
from models.shipping import ShippingCompany
from models.supplier import Supplier
from models.supplier_payment import SupplierPayment
from models.treasury_account import TreasuryAccount
from utils.cash_calculations import _effective_paid_amount
from utils.expense_queries import posted_expenses_query, sum_posted_expenses
from utils.order_item_costs import exclude_delivery_fee_items
from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES
from utils.payment_ledger import BUSINESS_TZ_NAME

_EXCLUDED = list(CANCELED_STATUSES) + list(RETURN_STATUSES)

_DATE_DESC = "بصيغة YYYY-MM-DD أو مع وقت YYYY-MM-DDTHH:MM بتوقيت بغداد"


# ══════════════════════════════════════════════
# مساعدات الوقت والتحويل
# ══════════════════════════════════════════════

def _tz():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(BUSINESS_TZ_NAME)
    except Exception:
        try:
            import pytz

            return pytz.timezone(BUSINESS_TZ_NAME)
        except Exception:
            return None


def now_local() -> datetime:
    tz = _tz()
    if tz is None:
        return datetime.now()
    return datetime.now(tz).replace(tzinfo=None)


def today_local() -> date:
    return now_local().date()


def _local_to_utc_naive(dt_local: datetime) -> datetime:
    tz = _tz()
    if tz is None:
        return dt_local
    try:
        aware = dt_local.replace(tzinfo=tz)
    except (TypeError, ValueError):
        aware = tz.localize(dt_local)  # pytz
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


def _utc_to_local_str(dt_utc: datetime | None) -> str:
    if not dt_utc:
        return ""
    tz = _tz()
    if tz is None:
        return dt_utc.strftime("%Y-%m-%d %H:%M")
    aware = dt_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    return aware.strftime("%Y-%m-%d %H:%M")


def _parse_date_arg(value: Any) -> date | None:
    """تاريخ فقط (لأعمدة Date مثل expense_date/purchase_date)."""
    if not value:
        return None
    raw = str(value).strip()[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _parse_dt_local(value: Any, *, end: bool = False) -> datetime | None:
    """يفسّر التاريخ/الوقت كتوقيت محلي (بغداد). end=True يعني حداً أعلى حصرياً."""
    if not value:
        return None
    raw = str(value).strip().replace(" ", "T")
    try:
        if len(raw) <= 10:
            d = date.fromisoformat(raw[:10])
            base = datetime.combine(d, time.min)
            return base + timedelta(days=1) if end else base
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _utc_window(date_from: Any, date_to: Any, *, default_today: bool = True):
    """يرجع (start_utc, end_utc, label) لفلترة created_at المخزّن UTC."""
    start_local = _parse_dt_local(date_from)
    end_local = _parse_dt_local(date_to, end=True)
    if start_local is None and end_local is None and default_today:
        d = today_local()
        start_local = datetime.combine(d, time.min)
        end_local = start_local + timedelta(days=1)
    if start_local is None and end_local is not None:
        start_local = end_local - timedelta(days=365 * 5)
    if end_local is None and start_local is not None:
        end_local = datetime.combine(today_local(), time.min) + timedelta(days=1)
    if start_local is None or end_local is None:
        return None, None, "كل الفترات"
    label = f"من {start_local.strftime('%Y-%m-%d %H:%M')} إلى {end_local.strftime('%Y-%m-%d %H:%M')} (بتوقيت بغداد)"
    return _local_to_utc_naive(start_local), _local_to_utc_naive(end_local), label


def _money(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _clip(text_value: str | None, limit: int = 140) -> str:
    text_value = (text_value or "").strip()
    return text_value[:limit]


def _invoice_base_filter(query):
    return query.filter(
        Invoice.status.notin_(_EXCLUDED),
        or_(Invoice.payment_status.is_(None), Invoice.payment_status.notin_(_EXCLUDED)),
    )


# ══════════════════════════════════════════════
# 1) الصندوق والخزائن
# ══════════════════════════════════════════════

def tool_get_treasury_accounts(args: dict, scope: dict) -> dict:
    from utils.executive_dashboard_data import get_treasury_summary

    summary = get_treasury_summary()
    return {
        "total_liquidity": _money(summary.get("total_liquidity")),
        "cash_box_balance": _money(summary.get("cash_box_balance")),
        "bank_total": _money(summary.get("bank_total")),
        "accounts": summary.get("treasury_accounts") or [],
        "currency": "د.ع",
    }


def tool_get_cash_movements(args: dict, scope: dict) -> dict:
    from utils.treasury_calculations import calculate_treasury_balance, get_treasury_movements
    from utils.treasury_helpers import get_default_cash_account

    account_id = args.get("account_id")
    account = TreasuryAccount.query.get(int(account_id)) if account_id else get_default_cash_account()
    if not account:
        return {"error": "حساب الخزينة غير موجود"}

    date_from = _parse_date_arg(args.get("date_from"))
    date_to = _parse_date_arg(args.get("date_to"))
    if date_from is None and date_to is None:
        date_from = date_to = today_local()
    if date_from is None:
        date_from = date(2000, 1, 1)
    if date_to is None:
        date_to = today_local()

    limit = min(_money(args.get("limit")) or 40, 100)
    movements = get_treasury_movements(account.id)

    opening_balance = 0
    for m in movements:
        if m["date"] < date_from:
            opening_balance = m["balance_after"]
        else:
            break

    in_range = [m for m in movements if date_from <= m["date"] <= date_to]
    total_in = sum(m["amount"] for m in in_range if m["type"] == "cash_in")
    total_out = sum(m["amount"] for m in in_range if m["type"] == "cash_out")
    closing_balance = in_range[-1]["balance_after"] if in_range else opening_balance

    return {
        "account": {"id": account.id, "name": account.name, "type": account.account_type},
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "opening_balance": _money(opening_balance),
        "total_in": _money(total_in),
        "total_out": _money(total_out),
        "net_change": _money(total_in - total_out),
        "closing_balance": _money(closing_balance),
        "current_balance_now": _money(calculate_treasury_balance(account.id)),
        "movements_count_in_period": len(in_range),
        "movements": [
            {
                "date": m["date"].isoformat(),
                "type": m.get("type_ar") or m.get("type"),
                "reason": m.get("reason"),
                "amount": _money(m.get("amount")),
                "balance_after": _money(m.get("balance_after")),
                "description": _clip(m.get("description")),
            }
            for m in in_range[-limit:]
        ],
        "note": "الحركات بدقة اليوم التقويمي (بتوقيت بغداد). الرصيد الافتتاحي = رصيد بداية الفترة.",
        "currency": "د.ع",
    }


# ══════════════════════════════════════════════
# 2) المبيعات والطلبات
# ══════════════════════════════════════════════

def tool_get_sales_summary(args: dict, scope: dict) -> dict:
    start_utc, end_utc, label = _utc_window(args.get("date_from"), args.get("date_to"))
    branch_id = args.get("branch_id")

    query = db.session.query(
        Invoice.id,
        Invoice.status,
        Invoice.payment_status,
        Invoice.total,
        Invoice.paid_amount,
        Invoice.created_at,
        Invoice.branch_id,
        Invoice.employee_name,
        Invoice.page_name,
    ).filter(Invoice.created_at >= start_utc, Invoice.created_at < end_utc)
    if branch_id:
        query = query.filter(Invoice.branch_id == int(branch_id))
    rows = query.all()

    valid = [r for r in rows if (r.status not in _EXCLUDED) and ((r.payment_status or "") not in _EXCLUDED)]
    returned = [r for r in rows if (r.status in RETURN_STATUSES) or ((r.payment_status or "") in RETURN_STATUSES)]
    canceled = [r for r in rows if (r.status in CANCELED_STATUSES) or ((r.payment_status or "") in CANCELED_STATUSES)]

    total_sales = sum(_money(r.total) for r in valid)
    collected = sum(_effective_paid_amount(r) for r in valid)

    result: dict[str, Any] = {
        "period": label,
        "orders_count": len(valid),
        "total_sales": total_sales,
        "collected_cash": collected,
        "remaining_receivable": max(0, total_sales - collected),
        "returned_orders": {"count": len(returned), "total": sum(_money(r.total) for r in returned)},
        "canceled_orders": {"count": len(canceled), "total": sum(_money(r.total) for r in canceled)},
        "currency": "د.ع",
    }

    group_by = (args.get("group_by") or "").strip()
    if group_by in {"day", "branch", "employee", "status", "page"}:
        branch_names = {b.id: b.name for b in Branch.query.all()}
        buckets: dict[str, dict] = {}
        for r in valid:
            if group_by == "day":
                key = _utc_to_local_str(r.created_at)[:10] if r.created_at else "غير محدد"
            elif group_by == "branch":
                key = branch_names.get(r.branch_id, "غير محدد")
            elif group_by == "employee":
                key = r.employee_name or "غير محدد"
            elif group_by == "page":
                key = r.page_name or "غير محدد"
            else:
                key = r.status or "غير محدد"
            bucket = buckets.setdefault(key, {"orders": 0, "total": 0, "collected": 0})
            bucket["orders"] += 1
            bucket["total"] += _money(r.total)
            bucket["collected"] += _effective_paid_amount(r)
        result["breakdown_by"] = group_by
        result["breakdown"] = dict(sorted(buckets.items(), key=lambda kv: -kv[1]["total"])[:31])
    return result


def tool_search_orders(args: dict, scope: dict) -> dict:
    limit = min(_money(args.get("limit")) or 20, 50)
    query = Invoice.query
    if args.get("status"):
        query = query.filter(Invoice.status == str(args["status"]).strip())
    if args.get("payment_status"):
        query = query.filter(Invoice.payment_status == str(args["payment_status"]).strip())
    if args.get("customer"):
        query = query.filter(Invoice.customer_name.ilike(f"%{str(args['customer']).strip()}%"))
    if args.get("branch_id"):
        query = query.filter(Invoice.branch_id == int(args["branch_id"]))
    if args.get("date_from") or args.get("date_to"):
        start_utc, end_utc, _ = _utc_window(args.get("date_from"), args.get("date_to"), default_today=False)
        if start_utc and end_utc:
            query = query.filter(Invoice.created_at >= start_utc, Invoice.created_at < end_utc)

    orders = query.order_by(Invoice.created_at.desc()).limit(limit).all()
    branch_names = {b.id: b.name for b in Branch.query.all()}
    return {
        "count": len(orders),
        "orders": [
            {
                "invoice_id": o.id,
                "customer": o.customer_name,
                "status": o.status,
                "payment_status": o.payment_status,
                "total": _money(o.total),
                "paid": _effective_paid_amount(o),
                "branch": branch_names.get(o.branch_id, ""),
                "employee": o.employee_name or "",
                "created_at": _utc_to_local_str(o.created_at),
            }
            for o in orders
        ],
        "currency": "د.ع",
    }


def tool_get_order_details(args: dict, scope: dict) -> dict:
    invoice_id = _money(args.get("invoice_id"))
    invoice = Invoice.query.get(invoice_id)
    if not invoice:
        return {"error": f"الطلب #{invoice_id} غير موجود"}
    show_cost = bool(scope.get("financial") or scope.get("reports"))
    items = []
    for item in invoice.items:
        row = {
            "product_id": item.product_id,
            "name": item.product_name,
            "quantity": _money(item.quantity),
            "price": _money(item.price),
            "line_total": _money(item.total if getattr(item, "total", None) else _money(item.price) * _money(item.quantity)),
        }
        if show_cost:
            row["cost"] = _money(item.cost)
        items.append(row)
    ledger = (
        InvoicePaymentLedger.query.filter_by(invoice_id=invoice.id)
        .order_by(InvoicePaymentLedger.recorded_at.asc())
        .all()
    )
    branch = Branch.query.get(invoice.branch_id) if invoice.branch_id else None
    return {
        "invoice_id": invoice.id,
        "customer": invoice.customer_name,
        "status": invoice.status,
        "payment_status": invoice.payment_status,
        "total": _money(invoice.total),
        "paid_amount": _money(invoice.paid_amount),
        "effective_paid": _effective_paid_amount(invoice),
        "branch": branch.name if branch else "",
        "employee": invoice.employee_name or "",
        "shipping_company": invoice.shipping_company.name if invoice.shipping_company else "",
        "created_at": _utc_to_local_str(invoice.created_at),
        "note": _clip(invoice.note),
        "items": items,
        "payment_history": [
            {"amount_delta": _money(l.amount_delta), "recorded_at": _utc_to_local_str(l.recorded_at)}
            for l in ledger
        ],
        "currency": "د.ع",
    }


# ══════════════════════════════════════════════
# 3) الأرباح والمصاريف
# ══════════════════════════════════════════════

def tool_get_profit_summary(args: dict, scope: dict) -> dict:
    start_utc, end_utc, label = _utc_window(args.get("date_from"), args.get("date_to"))
    d_from = _parse_date_arg(args.get("date_from")) or today_local()
    d_to = _parse_date_arg(args.get("date_to")) or today_local()

    invoices = db.session.query(
        Invoice.id, Invoice.status, Invoice.payment_status, Invoice.total, Invoice.paid_amount
    ).filter(
        Invoice.created_at >= start_utc,
        Invoice.created_at < end_utc,
        Invoice.status.notin_(_EXCLUDED),
        or_(Invoice.payment_status.is_(None), Invoice.payment_status.notin_(_EXCLUDED)),
    ).all()

    invoice_ids = [int(r.id) for r in invoices]
    sales_total = sum(_money(r.total) for r in invoices)
    collected = sum(_effective_paid_amount(r) for r in invoices)

    cogs = 0
    if invoice_ids:
        cogs = _money(
            db.session.query(func.sum(OrderItem.cost * OrderItem.quantity))
            .filter(OrderItem.invoice_id.in_(invoice_ids), exclude_delivery_fee_items(OrderItem))
            .scalar()
        )

    expenses = sum_posted_expenses(d_from, d_to)

    gross = sales_total - cogs
    return {
        "period": label,
        "orders_count": len(invoices),
        "sales_total": sales_total,
        "collected_cash": collected,
        "cogs": cogs,
        "gross_profit": gross,
        "expenses": expenses,
        "net_profit": gross - expenses,
        "basis_note": "الأرقام على أساس تاريخ إنشاء الطلب (مطابق لبطاقات لوحة التحكم)، مع استبعاد الملغي والراجع.",
        "currency": "د.ع",
    }


def tool_get_expenses(args: dict, scope: dict) -> dict:
    d_from = _parse_date_arg(args.get("date_from"))
    d_to = _parse_date_arg(args.get("date_to"))
    if d_from is None and d_to is None:
        today = today_local()
        d_from = today.replace(day=1)
        d_to = today
    d_from = d_from or date(2000, 1, 1)
    d_to = d_to or today_local()
    limit = min(_money(args.get("limit")) or 20, 50)

    query = posted_expenses_query(d_from, d_to)
    category = (args.get("category") or "").strip()
    if category:
        query = query.filter(
            or_(Expense.category.ilike(f"%{category}%"), Expense.title.ilike(f"%{category}%"))
        )
    expenses = query.order_by(Expense.expense_date.desc(), Expense.id.desc()).all()

    by_category: dict[str, int] = {}
    for e in expenses:
        key = (e.category or "بدون فئة").strip() or "بدون فئة"
        by_category[key] = by_category.get(key, 0) + _money(e.amount)

    return {
        "period": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "total": sum(_money(e.amount) for e in expenses),
        "count": len(expenses),
        "by_category": dict(sorted(by_category.items(), key=lambda kv: -kv[1])),
        "recent": [
            {
                "date": e.expense_date.isoformat() if e.expense_date else "",
                "title": e.title,
                "category": e.category or "",
                "amount": _money(e.amount),
                "note": _clip(e.note, 80),
            }
            for e in expenses[:limit]
        ],
        "currency": "د.ع",
    }


# ══════════════════════════════════════════════
# 4) الموردون والمشتريات
# ══════════════════════════════════════════════

def tool_get_supplier_debts(args: dict, scope: dict) -> dict:
    suppliers = Supplier.query.all()
    rows = []
    for s in suppliers:
        remaining = _money(s.total_debt) - _money(s.total_paid)
        rows.append(
            {
                "supplier_id": s.id,
                "name": s.name,
                "total_debt": _money(s.total_debt),
                "total_paid": _money(s.total_paid),
                "remaining": remaining,
            }
        )
    rows.sort(key=lambda r: -r["remaining"])
    return {
        "total_remaining_debt": sum(r["remaining"] for r in rows),
        "suppliers_count": len(rows),
        "suppliers": rows[:30],
        "note": "ديون الموردين التزامات على الشركة (نحن مدينون للمورد).",
        "currency": "د.ع",
    }


def tool_get_supplier_statement(args: dict, scope: dict) -> dict:
    supplier = None
    if args.get("supplier_id"):
        supplier = Supplier.query.get(int(args["supplier_id"]))
    elif args.get("name"):
        supplier = Supplier.query.filter(Supplier.name.ilike(f"%{str(args['name']).strip()}%")).first()
    if not supplier:
        return {"error": "المورد غير موجود. استخدم get_supplier_debts لرؤية أسماء الموردين."}

    purchases = (
        Purchase.query.filter_by(supplier_id=supplier.id)
        .order_by(Purchase.created_at.desc())
        .limit(10)
        .all()
    )
    payments = (
        SupplierPayment.query.filter_by(supplier_id=supplier.id)
        .order_by(SupplierPayment.created_at.desc())
        .limit(10)
        .all()
    )
    return {
        "supplier": {
            "id": supplier.id,
            "name": supplier.name,
            "phone": supplier.phone or "",
            "opening_balance": _money(supplier.opening_balance),
            "total_debt": _money(supplier.total_debt),
            "total_paid": _money(supplier.total_paid),
            "remaining": _money(supplier.total_debt) - _money(supplier.total_paid),
        },
        "recent_purchases": [
            {
                "purchase_id": p.id,
                "invoice_no": p.invoice_no or "",
                "date": p.purchase_date.isoformat() if p.purchase_date else "",
                "grand_total": _money(p.grand_total) or _money(p.total),
                "paid": _money(p.paid_total),
                "remaining": _money(p.remaining_total),
                "status": p.status or "",
            }
            for p in purchases
        ],
        "recent_payments": [
            {
                "date": _utc_to_local_str(pay.created_at),
                "amount": _money(pay.amount),
                "note": _clip(pay.note, 80),
            }
            for pay in payments
        ],
        "currency": "د.ع",
    }


def tool_get_purchases_summary(args: dict, scope: dict) -> dict:
    d_from = _parse_date_arg(args.get("date_from"))
    d_to = _parse_date_arg(args.get("date_to"))
    if d_from is None and d_to is None:
        today = today_local()
        d_from = today.replace(day=1)
        d_to = today
    d_from = d_from or date(2000, 1, 1)
    d_to = d_to or today_local()

    query = Purchase.query.filter(
        Purchase.purchase_date.isnot(None),
        func.date(Purchase.purchase_date) >= d_from,
        func.date(Purchase.purchase_date) <= d_to,
    )
    if args.get("supplier_id"):
        query = query.filter(Purchase.supplier_id == int(args["supplier_id"]))
    purchases = query.order_by(Purchase.purchase_date.desc()).all()

    supplier_names = {s.id: s.name for s in Supplier.query.all()}

    def _p_total(p) -> int:
        return _money(p.grand_total) or _money(p.total)

    return {
        "period": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "count": len(purchases),
        "grand_total": sum(_p_total(p) for p in purchases),
        "paid_total": sum(_money(p.paid_total) for p in purchases),
        "remaining_total": sum(_money(p.remaining_total) for p in purchases),
        "recent": [
            {
                "purchase_id": p.id,
                "supplier": supplier_names.get(p.supplier_id, ""),
                "invoice_no": p.invoice_no or "",
                "date": p.purchase_date.isoformat() if p.purchase_date else "",
                "total": _p_total(p),
                "paid": _money(p.paid_total),
                "status": p.status or "",
            }
            for p in purchases[:20]
        ],
        "currency": "د.ع",
    }


# ══════════════════════════════════════════════
# 5) العملاء والذمم
# ══════════════════════════════════════════════

def tool_get_customer_summary(args: dict, scope: dict) -> dict:
    customer = None
    if args.get("customer_id"):
        customer = Customer.query.get(int(args["customer_id"]))
    elif args.get("phone"):
        phone = str(args["phone"]).strip()
        customer = Customer.query.filter(
            or_(Customer.phone.ilike(f"%{phone}%"), Customer.phone2.ilike(f"%{phone}%"))
        ).first()
    elif args.get("name"):
        customer = Customer.query.filter(Customer.name.ilike(f"%{str(args['name']).strip()}%")).first()
    if not customer:
        return {"error": "الزبون غير موجود بهذا الاسم/الرقم."}

    invoices = Invoice.query.filter_by(customer_id=customer.id).order_by(Invoice.created_at.desc()).all()
    valid = [i for i in invoices if (i.status not in _EXCLUDED) and ((i.payment_status or "") not in _EXCLUDED)]
    returned_count = sum(
        1 for i in invoices if (i.status in RETURN_STATUSES) or ((i.payment_status or "") in RETURN_STATUSES)
    )
    total = sum(_money(i.total) for i in valid)
    paid = sum(_effective_paid_amount(i) for i in valid)

    today = today_local()
    plans = CustomerCreditPlan.query.filter_by(customer_id=customer.id).all()
    plans_total = sum(_money(p.total_amount) for p in plans)
    plans_paid = sum(_money(p.paid_amount) for p in plans)
    overdue_amount = 0
    overdue_count = 0
    for plan in plans:
        for inst in plan.installments:
            remaining = max(0, _money(inst.amount) - _money(inst.paid_amount))
            if remaining > 0 and inst.due_date and inst.due_date < today:
                overdue_count += 1
                overdue_amount += remaining

    return {
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "city": customer.city or "",
            "is_blacklisted": bool(customer.is_blacklisted),
        },
        "orders": {
            "count": len(valid),
            "total": total,
            "paid": paid,
            "remaining": max(0, total - paid),
            "returned_count": returned_count,
        },
        "credit_plans": {
            "count": len(plans),
            "total": plans_total,
            "paid": plans_paid,
            "remaining": max(0, plans_total - plans_paid),
            "overdue_installments_count": overdue_count,
            "overdue_installments_amount": overdue_amount,
        },
        "recent_orders": [
            {
                "invoice_id": i.id,
                "status": i.status,
                "payment_status": i.payment_status,
                "total": _money(i.total),
                "created_at": _utc_to_local_str(i.created_at),
            }
            for i in invoices[:8]
        ],
        "currency": "د.ع",
    }


def tool_get_customers_receivables(args: dict, scope: dict) -> dict:
    limit = min(_money(args.get("limit")) or 10, 30)
    rows = db.session.query(
        Invoice.customer_id,
        Invoice.customer_name,
        Invoice.status,
        Invoice.payment_status,
        Invoice.total,
        Invoice.paid_amount,
    ).filter(
        Invoice.status.notin_(_EXCLUDED),
        or_(Invoice.payment_status.is_(None), Invoice.payment_status.notin_(_EXCLUDED)),
    ).all()

    per_customer: dict[Any, dict] = {}
    for r in rows:
        remaining = _money(r.total) - _effective_paid_amount(r)
        if remaining <= 0:
            continue
        key = r.customer_id or r.customer_name
        bucket = per_customer.setdefault(key, {"customer": r.customer_name, "remaining": 0, "orders": 0})
        bucket["remaining"] += remaining
        bucket["orders"] += 1

    today = today_local()
    overdue_amount = 0
    overdue_count = 0
    for inst in CustomerInstallment.query.all():
        remaining = max(0, _money(inst.amount) - _money(inst.paid_amount))
        if remaining > 0 and inst.due_date and inst.due_date < today:
            overdue_count += 1
            overdue_amount += remaining

    top = sorted(per_customer.values(), key=lambda b: -b["remaining"])[:limit]
    return {
        "total_receivables": sum(b["remaining"] for b in per_customer.values()),
        "customers_with_debt": len(per_customer),
        "top_debtors": top,
        "overdue_installments": {"count": overdue_count, "amount": overdue_amount},
        "note": "الذمم = المتبقي على طلبات غير ملغية/غير راجعة. الأقساط المتأخرة من خطط التقسيط.",
        "currency": "د.ع",
    }


# ══════════════════════════════════════════════
# 6) المخزون والمنتجات
# ══════════════════════════════════════════════

def _arabic_term_variants(term: str) -> set[str]:
    """اختلافات إملائية شائعة (ة/ه، أ/إ/آ/ا، ى/ي) حتى لا يفشل البحث بسبب الرسم."""
    variants = {term}
    for old, new in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي")):
        variants = {v.replace(old, new) for v in variants} | variants
    variants |= {v.replace("ة", "ه") for v in variants}
    variants |= {v[:-1] + "ة" for v in variants if v.endswith("ه") and len(v) > 2}
    return {v for v in variants if v}


def tool_search_products(args: dict, scope: dict) -> dict:
    term = str(args.get("query") or "").strip()
    if not term:
        return {"error": "حدد اسم/رمز المنتج للبحث"}
    limit = min(_money(args.get("limit")) or 10, 20)

    token_filters = []
    for token in term.split()[:6]:
        ors = []
        for variant in _arabic_term_variants(token):
            like = f"%{variant}%"
            ors.extend([Product.name.ilike(like), Product.sku.ilike(like), Product.barcode.ilike(like)])
        token_filters.append(or_(*ors))
    products = (
        Product.query.filter(*token_filters)
        .order_by(Product.active.desc(), Product.name.asc())
        .limit(limit)
        .all()
    )
    return {
        "count": len(products),
        "products": [
            {
                "product_id": p.id,
                "name": p.name,
                "sku": p.sku or "",
                "total_quantity": _money(p.quantity),
                "buy_price": _money(p.buy_price),
                "sale_price": _money(p.sale_price),
                "active": bool(p.active),
            }
            for p in products
        ],
        "currency": "د.ع",
    }


def tool_get_product_stock(args: dict, scope: dict) -> dict:
    product_id = _money(args.get("product_id"))
    product = Product.query.get(product_id)
    if not product:
        return {"error": f"المنتج #{product_id} غير موجود. استخدم search_products أولاً."}

    reserved_rows = (
        db.session.query(
            func.coalesce(OrderItem.fulfillment_branch_id, Invoice.branch_id).label("branch_id"),
            func.coalesce(func.sum(OrderItem.quantity), 0).label("qty"),
        )
        .join(Invoice, Invoice.id == OrderItem.invoice_id)
        .filter(
            OrderItem.product_id == product.id,
            Invoice.status.in_(["تم الطلب", "جاري الشحن"]),
            exclude_delivery_fee_items(OrderItem),
        )
        .group_by(func.coalesce(OrderItem.fulfillment_branch_id, Invoice.branch_id))
        .all()
    )
    reserved = {int(r.branch_id or 0): _money(r.qty) for r in reserved_rows}

    stocks = BranchStock.query.filter_by(product_id=product.id).all()
    branch_names = {b.id: b.name for b in Branch.query.all()}
    branch_stock = []
    for s in stocks:
        r = reserved.get(s.branch_id, 0)
        branch_stock.append(
            {
                "branch": branch_names.get(s.branch_id, f"فرع #{s.branch_id}"),
                "system_qty": _money(s.quantity),
                "reserved_ordered_or_shipping": r,
                "salable_qty": _money(s.quantity) - r,
            }
        )
    return {
        "product": {
            "id": product.id,
            "name": product.name,
            "sku": product.sku or "",
            "total_quantity": _money(product.quantity),
            "buy_price": _money(product.buy_price),
            "sale_price": _money(product.sale_price),
        },
        "branch_stock": branch_stock,
        "note": "القابل للبيع = كمية النظام - المحجوز (تم الطلب + جاري الشحن).",
        "currency": "د.ع",
    }


def tool_get_product_movements(args: dict, scope: dict) -> dict:
    from utils.inventory_movements import get_product_inventory_movements

    product_id = _money(args.get("product_id"))
    product = Product.query.get(product_id)
    if not product:
        return {"error": f"المنتج #{product_id} غير موجود. استخدم search_products أولاً."}
    branch_id = int(args["branch_id"]) if args.get("branch_id") else None
    limit = min(_money(args.get("limit")) or 15, 30)
    try:
        movements = get_product_inventory_movements(product_id, branch_id=branch_id) or []
    except Exception as exc:
        return {"error": f"تعذر جلب الحركات: {exc}"}
    return {
        "product": {"id": product.id, "name": product.name},
        "branch_id": branch_id,
        "movements_count": len(movements),
        "movements": movements[-limit:],
    }


def tool_get_low_stock(args: dict, scope: dict) -> dict:
    limit = min(_money(args.get("limit")) or 20, 40)
    query = (
        db.session.query(BranchStock, Product, Branch)
        .join(Product, Product.id == BranchStock.product_id)
        .join(Branch, Branch.id == BranchStock.branch_id)
        .filter(Product.active.is_(True))
        .filter(BranchStock.quantity <= func.coalesce(BranchStock.low_stock_threshold, 5))
    )
    if args.get("branch_id"):
        query = query.filter(BranchStock.branch_id == int(args["branch_id"]))
    rows = query.order_by(BranchStock.quantity.asc()).limit(limit).all()
    return {
        "count": len(rows),
        "low_stock": [
            {
                "product_id": p.id,
                "product": p.name,
                "branch": b.name,
                "qty": _money(s.quantity),
                "threshold": _money(s.low_stock_threshold),
            }
            for s, p, b in rows
        ],
    }


def tool_get_top_products(args: dict, scope: dict) -> dict:
    start_utc, end_utc, label = _utc_window(args.get("date_from"), args.get("date_to"))
    by = (args.get("by") or "revenue").strip()
    limit = min(_money(args.get("limit")) or 10, 20)

    rows = (
        db.session.query(
            OrderItem.product_name,
            func.coalesce(func.sum(OrderItem.quantity), 0).label("qty"),
            func.coalesce(func.sum(OrderItem.price * OrderItem.quantity), 0).label("revenue"),
            func.coalesce(func.sum((OrderItem.price - OrderItem.cost) * OrderItem.quantity), 0).label("profit"),
        )
        .join(Invoice, Invoice.id == OrderItem.invoice_id)
        .filter(
            Invoice.created_at >= start_utc,
            Invoice.created_at < end_utc,
            Invoice.status.notin_(_EXCLUDED),
            or_(Invoice.payment_status.is_(None), Invoice.payment_status.notin_(_EXCLUDED)),
            exclude_delivery_fee_items(OrderItem),
        )
        .group_by(OrderItem.product_name)
        .all()
    )
    key = {"quantity": "qty", "revenue": "revenue", "profit": "profit"}.get(by, "revenue")
    items = sorted(
        (
            {
                "product": r.product_name,
                "quantity_sold": _money(r.qty),
                "revenue": _money(r.revenue),
                "profit": _money(r.profit),
            }
            for r in rows
        ),
        key=lambda item: -item[{"qty": "quantity_sold", "revenue": "revenue", "profit": "profit"}[key]],
    )[:limit]
    return {"period": label, "sorted_by": by, "top_products": items, "currency": "د.ع"}


def tool_get_employees_performance(args: dict, scope: dict) -> dict:
    """أداء الموظفين لفترة، يشمل الموظفين الذين لم يسجلوا أي طلب."""
    start_utc, end_utc, label = _utc_window(args.get("date_from"), args.get("date_to"))

    invoices = db.session.query(
        Invoice.id,
        Invoice.employee_id,
        Invoice.employee_name,
        Invoice.status,
        Invoice.payment_status,
        Invoice.total,
        Invoice.paid_amount,
    ).filter(Invoice.created_at >= start_utc, Invoice.created_at < end_utc).all()

    stats: dict[Any, dict] = {}
    for r in invoices:
        key = r.employee_id if r.employee_id is not None else f"name:{r.employee_name or 'غير محدد'}"
        bucket = stats.setdefault(
            key,
            {"name": r.employee_name or "غير محدد", "orders": 0, "total_sales": 0, "collected": 0, "returned": 0, "canceled": 0},
        )
        if (r.status in CANCELED_STATUSES) or ((r.payment_status or "") in CANCELED_STATUSES):
            bucket["canceled"] += 1
            continue
        if (r.status in RETURN_STATUSES) or ((r.payment_status or "") in RETURN_STATUSES):
            bucket["returned"] += 1
            continue
        bucket["orders"] += 1
        bucket["total_sales"] += _money(r.total)
        bucket["collected"] += _effective_paid_amount(r)

    branch_names = {b.id: b.name for b in Branch.query.all()}
    employees = Employee.query.all()
    performance = []
    zero_order_employees = []
    for emp in employees:
        bucket = stats.pop(emp.id, None) or {
            "name": emp.name,
            "orders": 0,
            "total_sales": 0,
            "collected": 0,
            "returned": 0,
            "canceled": 0,
        }
        row = {
            "employee_id": emp.id,
            "name": emp.name,
            "role": emp.role or "",
            "branch": branch_names.get(emp.branch_id, ""),
            "is_active": bool(getattr(emp, "is_active", True)),
            **{k: v for k, v in bucket.items() if k != "name"},
        }
        performance.append(row)
        if row["orders"] == 0 and row["returned"] == 0 and row["canceled"] == 0 and row["is_active"]:
            zero_order_employees.append({"employee_id": emp.id, "name": emp.name, "role": row["role"], "branch": row["branch"]})

    # فواتير باسم موظف غير موجود في جدول الموظفين (اسم قديم مثلاً)
    for key, bucket in stats.items():
        performance.append({"employee_id": None, "name": bucket["name"], "role": "", "branch": "", "is_active": None,
                            **{k: v for k, v in bucket.items() if k != "name"}})

    performance.sort(key=lambda r: -r["total_sales"])
    return {
        "period": label,
        "employees_count": len(employees),
        "performance": performance[:40],
        "zero_order_employees": zero_order_employees[:40],
        "note": "zero_order_employees = موظفون نشطون بدون أي طلب ضمن الفترة.",
        "currency": "د.ع",
    }


# ══════════════════════════════════════════════
# 7) الشحن والنظرة العامة والتدقيق
# ══════════════════════════════════════════════

def tool_get_shipping_companies_dues(args: dict, scope: dict) -> dict:
    companies = ShippingCompany.query.all()
    result = []
    for c in companies:
        orders = db.session.query(
            Invoice.id, Invoice.status, Invoice.payment_status, Invoice.total, Invoice.paid_amount
        ).filter(
            Invoice.shipping_company_id == c.id,
            Invoice.status.notin_(_EXCLUDED),
            or_(Invoice.payment_status.is_(None), Invoice.payment_status.notin_(_EXCLUDED)),
        ).all()
        orders_due = sum(max(0, _money(o.total) - _effective_paid_amount(o)) for o in orders)
        result.append(
            {
                "company_id": c.id,
                "name": c.name,
                "opening_balance": _money(c.opening_balance),
                "orders_due": orders_due,
                "total_due": _money(c.opening_balance) + orders_due,
                "active_orders": len(orders),
            }
        )
    result.sort(key=lambda r: -r["total_due"])
    return {
        "total_shipping_receivables": sum(r["total_due"] for r in result),
        "companies": result,
        "note": "هذه ذمم مدينة لصالح الشركة (إلنا عند شركات النقل)، وليست ديناً علينا.",
        "currency": "د.ع",
    }


def tool_get_financial_overview(args: dict, scope: dict) -> dict:
    from utils.accounting_calculations import (
        calculate_accounts_receivable,
        calculate_inventory_value,
        calculate_shipping_due,
        calculate_supplier_debts,
    )
    from utils.executive_dashboard_data import get_treasury_summary

    overview: dict[str, Any] = {"currency": "د.ع"}
    try:
        treasury = get_treasury_summary()
        overview["treasury"] = {
            "total_liquidity": _money(treasury.get("total_liquidity")),
            "cash_box_balance": _money(treasury.get("cash_box_balance")),
            "bank_total": _money(treasury.get("bank_total")),
        }
    except Exception as exc:
        overview["treasury"] = {"error": str(exc)}
    try:
        overview["inventory_value"] = _money(calculate_inventory_value())
    except Exception:
        overview["inventory_value"] = None
    try:
        overview["accounts_receivable"] = _money(calculate_accounts_receivable())
    except Exception:
        overview["accounts_receivable"] = None
    try:
        overview["supplier_debts"] = _money(calculate_supplier_debts())
    except Exception:
        overview["supplier_debts"] = None
    try:
        overview["shipping_receivables"] = _money(calculate_shipping_due())
    except Exception:
        overview["shipping_receivables"] = None

    if args.get("date_from") or args.get("date_to"):
        overview["period_profit"] = tool_get_profit_summary(args, scope)
    return overview


def tool_run_accounting_audit(args: dict, scope: dict) -> dict:
    from utils.audit_accounting_integrity import audit_accounting_integrity

    audit = audit_accounting_integrity(limit=120)
    return {
        "summary": audit.get("summary", {}),
        "samples": {
            "stock_imbalances": (audit.get("stock_imbalances") or [])[:3],
            "invoice_total_mismatches": (audit.get("invoice_total_mismatches") or [])[:3],
            "negative_margin_items": (audit.get("negative_margin_items") or [])[:3],
            "status_inconsistencies": (audit.get("status_inconsistencies") or [])[:3],
        },
    }


# ══════════════════════════════════════════════
# سجل الأدوات + تعريفات OpenAI
# ══════════════════════════════════════════════

def _params(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


_DATE_PROPS = {
    "date_from": {"type": "string", "description": f"بداية الفترة {_DATE_DESC}. اتركه فارغاً لليوم الحالي."},
    "date_to": {"type": "string", "description": f"نهاية الفترة {_DATE_DESC}."},
}

TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "get_treasury_accounts": {
        "handler": tool_get_treasury_accounts,
        "scopes": ["financial"],
        "description": "أرصدة كل الخزائن والحسابات (الصندوق النقدي + البنوك) والسيولة الكلية الآن.",
        "parameters": _params({}),
    },
    "get_cash_movements": {
        "handler": tool_get_cash_movements,
        "scopes": ["financial"],
        "description": (
            "حركات الصندوق/الخزينة لفترة محددة: رصيد بداية الفترة، الداخل، الخارج، رصيد النهاية، "
            "وقائمة الحركات مع أسبابها. استخدمها لأي سؤال عن حساب الصندوق اليوم أو بفترة معينة."
        ),
        "parameters": _params(
            {
                "date_from": {"type": "string", "description": "بداية الفترة YYYY-MM-DD. فارغ = اليوم."},
                "date_to": {"type": "string", "description": "نهاية الفترة YYYY-MM-DD. فارغ = اليوم."},
                "account_id": {"type": "integer", "description": "معرف حساب الخزينة. فارغ = الصندوق الافتراضي."},
                "limit": {"type": "integer", "description": "أقصى عدد حركات (افتراضي 40)."},
            }
        ),
    },
    "get_sales_summary": {
        "handler": tool_get_sales_summary,
        "scopes": ["reports", "financial"],
        "description": (
            "ملخص المبيعات لفترة: عدد الطلبات، إجمالي المبيعات، المحصّل نقداً، المتبقي، الراجع والملغي. "
            "يدعم التجميع حسب اليوم/الفرع/الموظف/الحالة/البيج."
        ),
        "parameters": _params(
            {
                **_DATE_PROPS,
                "branch_id": {"type": "integer", "description": "حصر النتائج بفرع محدد."},
                "group_by": {
                    "type": "string",
                    "enum": ["day", "branch", "employee", "status", "page"],
                    "description": "تجميع اختياري للنتائج.",
                },
            }
        ),
    },
    "search_orders": {
        "handler": tool_search_orders,
        "scopes": ["orders"],
        "description": "البحث عن طلبات/فواتير حسب الحالة أو اسم الزبون أو الفرع أو الفترة.",
        "parameters": _params(
            {
                "status": {"type": "string", "description": "حالة الطلب مثل: تم الطلب، جاري الشحن، تم التوصيل، راجع، ملغي."},
                "payment_status": {"type": "string", "description": "حالة الدفع مثل: مسدد، جزئي، غير مسدد."},
                "customer": {"type": "string", "description": "جزء من اسم الزبون."},
                "branch_id": {"type": "integer"},
                **_DATE_PROPS,
                "limit": {"type": "integer", "description": "أقصى عدد نتائج (افتراضي 20)."},
            }
        ),
    },
    "get_order_details": {
        "handler": tool_get_order_details,
        "scopes": ["orders"],
        "description": "تفاصيل طلب/فاتورة واحدة: الأصناف، المبالغ، سجل التحصيل، الفرع وشركة النقل.",
        "parameters": _params({"invoice_id": {"type": "integer", "description": "رقم الفاتورة/الطلب."}}, ["invoice_id"]),
    },
    "get_profit_summary": {
        "handler": tool_get_profit_summary,
        "scopes": ["financial", "reports"],
        "description": "الأرباح لفترة: المبيعات، تكلفة البضاعة المباعة، مجمل الربح، المصاريف، صافي الربح.",
        "parameters": _params(_DATE_PROPS),
    },
    "get_expenses": {
        "handler": tool_get_expenses,
        "scopes": ["financial"],
        "description": "المصاريف لفترة: الإجمالي، التوزيع حسب الفئة، وآخر المصاريف. فارغ = الشهر الحالي.",
        "parameters": _params(
            {
                **_DATE_PROPS,
                "category": {"type": "string", "description": "فلترة بفئة أو عنوان المصروف (بحث جزئي)."},
                "limit": {"type": "integer"},
            }
        ),
    },
    "get_supplier_debts": {
        "handler": tool_get_supplier_debts,
        "scopes": ["suppliers", "financial"],
        "description": "ديون كل الموردين: الدين، المسدد، المتبقي لكل مورد والإجمالي.",
        "parameters": _params({}),
    },
    "get_supplier_statement": {
        "handler": tool_get_supplier_statement,
        "scopes": ["suppliers"],
        "description": "كشف حساب مورد واحد: رصيده وآخر مشترياته ودفعاته.",
        "parameters": _params(
            {
                "supplier_id": {"type": "integer"},
                "name": {"type": "string", "description": "جزء من اسم المورد."},
            }
        ),
    },
    "get_purchases_summary": {
        "handler": tool_get_purchases_summary,
        "scopes": ["suppliers", "financial"],
        "description": "ملخص المشتريات لفترة: العدد، الإجمالي، المدفوع، المتبقي، وآخر الفواتير. فارغ = الشهر الحالي.",
        "parameters": _params({**_DATE_PROPS, "supplier_id": {"type": "integer"}}),
    },
    "get_employees_performance": {
        "handler": tool_get_employees_performance,
        "scopes": ["reports", "orders"],
        "description": (
            "أداء الموظفين/الكاشيرية لفترة: عدد الطلبات والمبيعات والمحصّل والراجع لكل موظف، "
            "مع قائمة الموظفين الذين لم يسجلوا أي طلب. استخدمها لأي سؤال عن موظف أو مقارنة موظفين."
        ),
        "parameters": _params(_DATE_PROPS),
    },
    "get_customer_summary": {
        "handler": tool_get_customer_summary,
        "scopes": ["orders"],
        "description": "ملخص زبون: طلباته، المسدد والمتبقي عليه، خطط الأقساط والأقساط المتأخرة، وآخر طلباته.",
        "parameters": _params(
            {
                "customer_id": {"type": "integer"},
                "name": {"type": "string", "description": "جزء من اسم الزبون."},
                "phone": {"type": "string", "description": "جزء من رقم الهاتف."},
            }
        ),
    },
    "get_customers_receivables": {
        "handler": tool_get_customers_receivables,
        "scopes": ["financial", "reports"],
        "description": "ذمم الزبائن (ديون العملاء): الإجمالي، أكثر الزبائن مديونية، والأقساط المتأخرة.",
        "parameters": _params({"limit": {"type": "integer", "description": "عدد أعلى المدينين (افتراضي 10)."}}),
    },
    "search_products": {
        "handler": tool_search_products,
        "scopes": ["inventory"],
        "description": "البحث عن منتجات بالاسم أو SKU أو الباركود.",
        "parameters": _params({"query": {"type": "string"}, "limit": {"type": "integer"}}, ["query"]),
    },
    "get_product_stock": {
        "handler": tool_get_product_stock,
        "scopes": ["inventory"],
        "description": "مخزون منتج واحد بكل فرع: كمية النظام، المحجوز (تم الطلب/جاري الشحن)، القابل للبيع.",
        "parameters": _params({"product_id": {"type": "integer"}}, ["product_id"]),
    },
    "get_product_movements": {
        "handler": tool_get_product_movements,
        "scopes": ["inventory"],
        "description": "سجل حركات مخزون منتج (شراء، بيع، مرتجع، تحويل، تسوية) مع الرصيد بعد كل حركة.",
        "parameters": _params(
            {
                "product_id": {"type": "integer"},
                "branch_id": {"type": "integer"},
                "limit": {"type": "integer", "description": "آخر N حركة (افتراضي 15)."},
            },
            ["product_id"],
        ),
    },
    "get_low_stock": {
        "handler": tool_get_low_stock,
        "scopes": ["inventory"],
        "description": "المنتجات التي وصلت حد التنبيه (مخزون منخفض) لكل فرع.",
        "parameters": _params({"branch_id": {"type": "integer"}, "limit": {"type": "integer"}}),
    },
    "get_top_products": {
        "handler": tool_get_top_products,
        "scopes": ["reports", "financial"],
        "description": "أفضل المنتجات مبيعاً لفترة، مرتبة حسب الكمية أو الإيراد أو الربح.",
        "parameters": _params(
            {
                **_DATE_PROPS,
                "by": {"type": "string", "enum": ["quantity", "revenue", "profit"], "description": "أساس الترتيب."},
                "limit": {"type": "integer"},
            }
        ),
    },
    "get_shipping_companies_dues": {
        "handler": tool_get_shipping_companies_dues,
        "scopes": ["shipping", "financial"],
        "description": "مستحقاتنا عند شركات النقل: الرصيد الافتتاحي + المتبقي من الطلبات لكل شركة.",
        "parameters": _params({}),
    },
    "get_financial_overview": {
        "handler": tool_get_financial_overview,
        "scopes": ["financial"],
        "description": (
            "نظرة مالية شاملة الآن: السيولة والخزائن، قيمة المخزون، ذمم الزبائن، ديون الموردين، "
            "ذمم شركات النقل. مع فترة اختيارية لإضافة ملخص أرباح الفترة."
        ),
        "parameters": _params(_DATE_PROPS),
    },
    "run_accounting_audit": {
        "handler": tool_run_accounting_audit,
        "scopes": ["financial", "reports"],
        "description": "تدقيق سلامة محاسبية: فروقات مخزون، فواتير غير متطابقة، هوامش سالبة، حالات متناقضة.",
        "parameters": _params({}),
    },
}


def get_tool_definitions(scope: dict) -> list[dict]:
    """تعريفات OpenAI tools المسموحة حسب صلاحيات المستخدم."""
    definitions = []
    for name, spec in TOOL_REGISTRY.items():
        if not any(scope.get(s) for s in spec["scopes"]):
            continue
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": spec["description"],
                    "parameters": spec["parameters"],
                },
            }
        )
    return definitions


def _ensure_schemas() -> None:
    """حراس المخطط نفسها التي تستخدمها بقية الشاشات (قواعد قديمة بدون migrations)."""
    try:
        from utils.order_item_schema_guard import ensure_order_item_schema

        ensure_order_item_schema()
    except Exception:
        pass


def execute_tool(name: str, arguments: dict | None, scope: dict) -> dict:
    """تنفيذ أداة قراءة مع فرض الصلاحيات. يرجع dict قابلاً للتحويل JSON دائماً."""
    spec = TOOL_REGISTRY.get(name)
    if not spec:
        return {"error": f"أداة غير معروفة: {name}"}
    if not any(scope.get(s) for s in spec["scopes"]):
        return {"restricted": True, "message": "هذه البيانات تحتاج صلاحية إضافية غير متاحة لحسابك."}
    _ensure_schemas()
    handler: Callable[[dict, dict], dict] = spec["handler"]
    try:
        return handler(arguments or {}, scope)
    except Exception as exc:
        db.session.rollback()
        return {"error": f"فشل تنفيذ الأداة {name}: {exc}"}
