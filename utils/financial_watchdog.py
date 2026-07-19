# utils/financial_watchdog.py
"""
مراقب مالي / تشغيلي تلقائي (قواعد آمنة):
- تنبيهات فورية للوحة التحكم (بدون تعديل بيانات).
- مركز مراقبة موحّد (/reports/monitors).
- حفظ اختياري في system_alert للمتابعة من واجهات أخرى (مع منع التكرار الزمني).
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, or_
from sqlalchemy.orm import joinedload

from extensions import db
from models.expense import Expense
from models.invoice import Invoice
from models.order_item import OrderItem
from models.shipping import ShippingCompany
from models.system_alert import SystemAlert
from utils.cash_calculations import _effective_paid_amount
from utils.expense_queries import posted_expense_filter
from utils.monitor_settings import MONITORS_HUB_URL, get_monitor_settings
from utils.order_item_costs import exclude_delivery_fee_items
from utils.order_status import CANCELED_STATUSES as ORDER_CANCELED
from utils.order_status import RETURN_STATUSES as ORDER_RETURN

RETURN_STATUSES = tuple(ORDER_RETURN)
CANCELED_STATUSES = tuple(ORDER_CANCELED)
DELIVERED_STATUSES = ("تم التوصيل", "مسدد", "واصل", "واصلة")

FINANCIAL_MONITOR_URL = f"{MONITORS_HUB_URL}?tab=financial"
OPERATIONAL_MONITOR_URL = f"{MONITORS_HUB_URL}?tab=operational"
OVERVIEW_MONITOR_URL = f"{MONITORS_HUB_URL}?tab=overview"

_WATCHDOG_PERSIST_COOLDOWN_SEC = 4 * 3600
_last_persist_ts: dict[str, float] = {}


def _tenant_key() -> str:
    try:
        from flask import g, session

        return (getattr(g, "tenant", None) or session.get("tenant_slug") or "default").strip()
    except Exception:
        return "default"


def _fmt_money(value) -> str:
    return f"{int(value or 0):,} د.ع"


def _valid_invoice_filter():
    return (
        Invoice.status.notin_(list(CANCELED_STATUSES) + list(RETURN_STATUSES)),
        or_(Invoice.payment_status.is_(None), Invoice.payment_status.notin_(list(RETURN_STATUSES) + list(CANCELED_STATUSES))),
    )


def _apply_monitor_filters(query, filters: dict | None):
    if not filters:
        return query
    if filters.get("branch_id"):
        query = query.filter(Invoice.branch_id == filters["branch_id"])
    if filters.get("page_id"):
        query = query.filter(Invoice.page_id == filters["page_id"])
    if filters.get("employee_id"):
        query = query.filter(Invoice.employee_id == filters["employee_id"])
    return query


def _delta_pct(current: int, previous: int) -> float | None:
    if previous == 0:
        return None if current == 0 else 100.0
    return round((current - previous) / abs(previous) * 100, 1)


def _previous_period(date_from: datetime, date_to: datetime) -> tuple[datetime, datetime]:
    span_days = max(1, (date_to.date() - date_from.date()).days + 1)
    prev_end = date_from - timedelta(seconds=1)
    prev_start = prev_end - timedelta(days=span_days - 1)
    return prev_start.replace(hour=0, minute=0, second=0, microsecond=0), prev_end.replace(
        hour=23, minute=59, second=59, microsecond=999999
    )


def _period_financial_metrics(date_from: datetime, date_to: datetime, *, filters: dict | None = None) -> dict[str, int]:
    d_from, d_to = date_from.date(), date_to.date()
    status_ok, pay_ok = _valid_invoice_filter()
    try:
        invoices = (
            _apply_monitor_filters(
                Invoice.query.filter(
                    func.date(Invoice.created_at) >= d_from,
                    func.date(Invoice.created_at) <= d_to,
                    status_ok,
                    pay_ok,
                ),
                filters,
            ).all()
        )
        revenue = sum(int(inv.total or 0) for inv in invoices)
        paid_sales = sum(_effective_paid_amount(inv) for inv in invoices)
        invoice_ids = [int(inv.id) for inv in invoices]
        cogs = 0
        if invoice_ids:
            cogs = int(
                db.session.query(func.coalesce(func.sum(OrderItem.cost * OrderItem.quantity), 0))
                .filter(OrderItem.invoice_id.in_(invoice_ids), exclude_delivery_fee_items(OrderItem))
                .scalar()
                or 0
            )
        expenses = int(
            db.session.query(func.coalesce(func.sum(Expense.amount), 0))
            .filter(posted_expense_filter(), func.date(Expense.expense_date) >= d_from, func.date(Expense.expense_date) <= d_to)
            .scalar()
            or 0
        )
        gross_profit = revenue - cogs
        net_profit = revenue - cogs - expenses
        return {
            "revenue": revenue,
            "paid_sales": paid_sales,
            "expenses": expenses,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "net_profit": net_profit,
        }
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return {"revenue": 0, "paid_sales": 0, "expenses": 0, "cogs": 0, "gross_profit": 0, "net_profit": 0}


def _top_expense_categories(date_from: datetime, date_to: datetime, limit: int = 5) -> list[dict[str, Any]]:
    d_from, d_to = date_from.date(), date_to.date()
    try:
        rows = (
            db.session.query(Expense.category, func.sum(Expense.amount).label("total"))
            .filter(posted_expense_filter(), func.date(Expense.expense_date) >= d_from, func.date(Expense.expense_date) <= d_to)
            .group_by(Expense.category)
            .order_by(func.sum(Expense.amount).desc())
            .limit(limit)
            .all()
        )
        return [
            {"category": (cat or "أخرى"), "amount": int(total or 0), "amount_display": _fmt_money(total)}
            for cat, total in rows
        ]
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return []


def _daily_chart_series(date_from: datetime, date_to: datetime, *, filters: dict | None = None) -> dict[str, list]:
    labels: list[str] = []
    revenue_series: list[int] = []
    expense_series: list[int] = []
    cur = date_from.date()
    end = date_to.date()
    status_ok, pay_ok = _valid_invoice_filter()
    while cur <= end:
        labels.append(cur.strftime("%m/%d"))
        try:
            rev = int(
                _apply_monitor_filters(
                    db.session.query(func.coalesce(func.sum(Invoice.total), 0)).filter(
                        func.date(Invoice.created_at) == cur, status_ok, pay_ok
                    ),
                    filters,
                ).scalar()
                or 0
            )
            exp = int(
                db.session.query(func.coalesce(func.sum(Expense.amount), 0))
                .filter(posted_expense_filter(), func.date(Expense.expense_date) == cur)
                .scalar()
                or 0
            )
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            rev, exp = 0, 0
        revenue_series.append(rev)
        expense_series.append(exp)
        cur += timedelta(days=1)
        if len(labels) > 62:
            break
    return {"labels": labels, "revenue": revenue_series, "expenses": expense_series}


def _operational_daily_chart(date_from: datetime, date_to: datetime, *, filters: dict | None = None) -> dict[str, list]:
    labels: list[str] = []
    new_orders: list[int] = []
    delivered: list[int] = []
    cur = date_from.date()
    end = date_to.date()
    delivered_cond = or_(Invoice.status.in_(DELIVERED_STATUSES), Invoice.payment_status.in_(("مسدد", "تم التوصيل")))
    while cur <= end:
        labels.append(cur.strftime("%m/%d"))
        try:
            new_count = int(
                _apply_monitor_filters(
                    db.session.query(func.count(Invoice.id)).filter(func.date(Invoice.created_at) == cur),
                    filters,
                ).scalar()
                or 0
            )
            del_count = int(
                _apply_monitor_filters(
                    db.session.query(func.count(Invoice.id)).filter(
                        func.date(Invoice.created_at) == cur, delivered_cond
                    ),
                    filters,
                ).scalar()
                or 0
            )
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            new_count, del_count = 0, 0
        new_orders.append(new_count)
        delivered.append(del_count)
        cur += timedelta(days=1)
        if len(labels) > 62:
            break
    return {"labels": labels, "new_orders": new_orders, "delivered": delivered}


def _financial_health_score(summary: dict, alerts: list) -> int:
    score = 100
    score -= int(summary.get("critical_count") or 0) * 8
    score -= int(summary.get("warning_count") or 0) * 4
    for alert in alerts:
        if alert.get("type") == "danger":
            score -= 12
        elif alert.get("type") == "warning":
            score -= 6
        elif alert.get("type") == "info":
            score -= 2
    if float(summary.get("expense_ratio") or 0) >= 80:
        score -= 10
    if int(summary.get("net_profit") or 0) < 0:
        score -= 15
    return max(0, min(100, score))


def _operational_health_score(summary: dict, alerts: list, delivered_rate: float) -> int:
    score = 100
    score -= min(30, int(summary.get("pending_count") or 0))
    score -= min(25, int(summary.get("shipping_stuck_count") or 0) * 4)
    for alert in alerts:
        if alert.get("type") == "warning":
            score -= 8
        elif alert.get("type") == "info":
            score -= 4
    if delivered_rate < 40:
        score -= 10
    return max(0, min(100, score))


def _recent_system_alert(alert_type: str, *, hours: float = 6) -> bool:
    since = datetime.utcnow() - timedelta(hours=hours)
    row = (
        SystemAlert.query.filter(
            SystemAlert.alert_type == alert_type,
            SystemAlert.created_at >= since,
            SystemAlert.is_dismissed.is_(False),
        )
        .first()
    )
    return row is not None


def _nav_decisions(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"label": label, "href": href, "kind": "navigate"} for label, href in pairs if label and href]


def _overdue_snapshot(*, min_days: int = 7, limit: int = 50) -> dict:
    try:
        from ai.ai_utils import _snapshot_overdue_orders

        return _snapshot_overdue_orders(min_days=min_days, limit=limit)
    except Exception:
        return {"orders": [], "listed_count": 0, "critical_count": 0, "warning_only_count": 0}


def _enrich_overdue_rows(snap: dict, settings: dict) -> list[dict[str, Any]]:
    crit_days = int(settings.get("overdue_critical_days") or 10)
    warn_days = int(settings.get("overdue_warning_days") or 7)
    rows = []
    for item in snap.get("orders") or []:
        days = int(item.get("days_overdue") or 0)
        if days >= crit_days:
            sev, label, cls = "critical", "حرج", "danger"
        elif days >= warn_days:
            sev, label, cls = "warning", "تحذير", "warning"
        else:
            sev, label, cls = "info", "متابعة", "success"
        rows.append(
            {
                "id": item.get("id"),
                "customer": item.get("customer") or "—",
                "phone": item.get("phone") or "—",
                "status": item.get("status") or "—",
                "days_overdue": days,
                "severity": sev,
                "severity_label": label,
                "severity_class": cls,
                "order_url": f"/orders/{item.get('id')}" if item.get("id") else "/orders/",
            }
        )
    return rows


def _build_financial_alerts(
    *,
    crit: int,
    warn_only: int,
    listed: int,
    paid: int,
    cash_profit: int,
    booked_profit: int,
    gross_profit: int,
    total_expenses: int,
    net_profit: int,
    booked_sales: int,
    settings: dict,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    loss_threshold = int(settings.get("paid_sales_loss_threshold") or 500_000)
    crit_days = int(settings.get("overdue_critical_days") or 10)

    if crit > 0:
        alerts.append(
            {
                "type": "danger",
                "icon": "🔴",
                "title": "طلبات حرجة",
                "message": f"{crit} طلب(ات) متأخرة {crit_days}+ أيام — عيّنة: {listed}.",
                "action": "/orders/",
                "source": "watchdog_overdue",
            }
        )
    elif warn_only > 0:
        alerts.append(
            {
                "type": "warning",
                "icon": "🟠",
                "title": "طلبات متأخرة",
                "message": f"{warn_only} طلب(ات) متأخرة — راجع التسليم.",
                "action": "/orders/",
                "source": "watchdog_overdue",
            }
        )

    if paid > loss_threshold and cash_profit < 0 and booked_profit < 0:
        alerts.append(
            {
                "type": "danger",
                "icon": "📉",
                "title": "خسارة نقدية ومحاسبية",
                "message": "الربح النقدي والمحاسبي سالبان — راجع التكاليف والمصاريف فوراً.",
                "action": "/accounts",
                "source": "watchdog_negative_operating",
            }
        )
    elif paid > loss_threshold and cash_profit < 0:
        alerts.append(
            {
                "type": "info",
                "icon": "💡",
                "title": "تحذير نقدي",
                "message": (
                    f"التحصيل المسدد لا يغطي المصاريف ({_fmt_money(cash_profit)})، "
                    f"لكن ربح الفترة موجب ({_fmt_money(booked_profit)})."
                ),
                "action": "/accounts",
                "source": "watchdog_cash_basis_profit",
            }
        )

    if net_profit < 0:
        alerts.append(
            {
                "type": "danger",
                "icon": "🚨",
                "title": "خسارة محاسبية",
                "message": f"مصاريف الفترة ({_fmt_money(total_expenses)}) أعلى من الربح الإجمالي ({_fmt_money(gross_profit)}).",
                "action": "/accounts",
                "source": "watchdog_net_loss",
            }
        )
    elif gross_profit > 0:
        expense_ratio = (total_expenses / gross_profit * 100) if gross_profit > 0 else 0
        if expense_ratio >= 80:
            alerts.append(
                {
                    "type": "warning",
                    "icon": "⚠️",
                    "title": "مصاريف مرتفعة",
                    "message": f"المصاريف تمثل {expense_ratio:.1f}% من الربح الإجمالي.",
                    "action": "/accounts",
                    "source": "watchdog_expense_ratio",
                }
            )
        elif booked_sales > 0:
            profit_ratio = (net_profit / booked_sales * 100) if booked_sales > 0 else 0
            if profit_ratio < 20:
                alerts.append(
                    {
                        "type": "info",
                        "icon": "💡",
                        "title": "ربح منخفض",
                        "message": f"الربح الصافي يمثل {profit_ratio:.1f}% فقط من المبيعات.",
                        "action": "/accounts",
                        "source": "watchdog_low_profit_ratio",
                    }
                )
    return alerts


def _build_operational_counts(*, stuck_days: int = 5, filters: dict | None = None) -> dict[str, int]:
    now = datetime.utcnow()
    stuck_cutoff = now - timedelta(days=stuck_days)
    try:
        pending = _apply_monitor_filters(Invoice.query.filter(Invoice.status == "تم الطلب"), filters).count()
        shipping = _apply_monitor_filters(
            Invoice.query.filter(Invoice.status == "جاري الشحن"), filters
        ).count()
        shipping_stuck = _apply_monitor_filters(
            Invoice.query.filter(Invoice.status == "جاري الشحن", Invoice.created_at <= stuck_cutoff),
            filters,
        ).count()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        pending, shipping, shipping_stuck = 0, 0, 0
    return {
        "pending_count": int(pending or 0),
        "shipping_count": int(shipping or 0),
        "shipping_stuck_count": int(shipping_stuck or 0),
    }


def _build_operational_alerts(counts: dict[str, int], settings: dict) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    pending = counts.get("pending_count", 0)
    shipping_stuck = counts.get("shipping_stuck_count", 0)
    stuck_min = int(settings.get("shipping_stuck_alert_min") or 3)
    pending_min = int(settings.get("pending_backlog_alert_min") or 18)
    stuck_days = int(settings.get("shipping_stuck_days") or 5)

    if shipping_stuck >= stuck_min:
        alerts.append(
            {
                "type": "warning",
                "icon": "🚚",
                "title": "شحن عالق",
                "message": f"{shipping_stuck} طلب «جاري الشحن» منذ {stuck_days}+ أيام.",
                "action": "/orders/shipping",
                "source": "watchdog_shipping_stuck",
            }
        )
    if pending >= pending_min:
        alerts.append(
            {
                "type": "info",
                "icon": "📋",
                "title": "تراكم طلبات",
                "message": f"{pending} طلب بحالة «تم الطلب».",
                "action": "/orders/ordered",
                "source": "watchdog_pending_backlog",
            }
        )
    return alerts


def build_financial_monitor_data(
    date_from: datetime,
    date_to: datetime,
    *,
    overdue_min_days: int = 7,
    settings: dict | None = None,
    filters: dict | None = None,
) -> dict[str, Any]:
    settings = settings or get_monitor_settings()
    snap = _overdue_snapshot(min_days=overdue_min_days, limit=50)
    overdue_rows = _enrich_overdue_rows(snap, settings)
    if filters:
        try:
            allowed_ids = {
                inv_id
                for (inv_id,) in _apply_monitor_filters(
                    db.session.query(Invoice.id),
                    filters,
                ).all()
            }
            overdue_rows = [row for row in overdue_rows if row.get("id") in allowed_ids]
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
    crit = sum(1 for row in overdue_rows if row.get("severity") == "critical")
    warn_only = sum(1 for row in overdue_rows if row.get("severity") == "warning")
    listed = len(overdue_rows)

    current = _period_financial_metrics(date_from, date_to, filters=filters)
    prev_from, prev_to = _previous_period(date_from, date_to)
    previous = _period_financial_metrics(prev_from, prev_to, filters=filters)

    revenue = current["revenue"]
    paid = current["paid_sales"]
    expenses = current["expenses"]
    gross_profit = current["gross_profit"]
    net_profit = current["net_profit"]
    expense_ratio = (expenses / gross_profit * 100) if gross_profit > 0 else 0.0
    profit_ratio = (net_profit / revenue * 100) if revenue > 0 else 0.0

    receivables = supplier_debts = shipping_due = 0
    try:
        from utils.accounting_calculations import (
            calculate_accounts_receivable,
            calculate_supplier_debts,
            calculate_shipping_due,
        )

        receivables = int(calculate_accounts_receivable() or 0)
        supplier_debts = int(calculate_supplier_debts() or 0)
        shipping_due = int(calculate_shipping_due() or 0)
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

    alerts = _build_financial_alerts(
        crit=crit,
        warn_only=warn_only,
        listed=listed,
        paid=paid,
        cash_profit=net_profit,
        booked_profit=net_profit,
        gross_profit=gross_profit,
        total_expenses=expenses,
        net_profit=net_profit,
        booked_sales=revenue,
        settings=settings,
    )

    summary = {
        "paid_sales": paid,
        "paid_sales_display": _fmt_money(paid),
        "revenue": revenue,
        "revenue_display": _fmt_money(revenue),
        "expenses": expenses,
        "expenses_display": _fmt_money(expenses),
        "gross_profit": gross_profit,
        "gross_profit_display": _fmt_money(gross_profit),
        "cash_profit": net_profit,
        "cash_profit_display": _fmt_money(net_profit),
        "booked_profit": net_profit,
        "booked_profit_display": _fmt_money(net_profit),
        "expense_ratio": round(expense_ratio, 1),
        "profit_ratio": round(profit_ratio, 1),
        "critical_count": crit,
        "warning_count": warn_only,
        "overdue_listed": listed,
        "receivables": receivables,
        "receivables_display": _fmt_money(receivables),
        "supplier_debts": supplier_debts,
        "supplier_debts_display": _fmt_money(supplier_debts),
        "shipping_due": shipping_due,
        "shipping_due_display": _fmt_money(shipping_due),
        "delta_revenue_pct": _delta_pct(revenue, previous["revenue"]),
        "delta_profit_pct": _delta_pct(net_profit, previous["net_profit"]),
        "delta_expenses_pct": _delta_pct(expenses, previous["expenses"]),
        "prev_revenue_display": _fmt_money(previous["revenue"]),
        "prev_profit_display": _fmt_money(previous["net_profit"]),
    }
    health_score = _financial_health_score(summary, alerts)
    summary["health_score"] = health_score

    return {
        "date_from": date_from,
        "date_to": date_to,
        "overdue_min_days": overdue_min_days,
        "summary": summary,
        "overdue_orders": overdue_rows,
        "top_expenses": _top_expense_categories(date_from, date_to),
        "alerts": alerts,
        "health_score": health_score,
        "chart": _daily_chart_series(date_from, date_to, filters=filters),
    }


def build_operational_monitor_data(
    date_from: datetime,
    date_to: datetime,
    *,
    stuck_days: int = 5,
    table_limit: int = 40,
    settings: dict | None = None,
    filters: dict | None = None,
) -> dict[str, Any]:
    settings = settings or get_monitor_settings()
    now = datetime.utcnow()
    stuck_cutoff = now - timedelta(days=stuck_days)
    counts = _build_operational_counts(stuck_days=stuck_days, filters=filters)

    shipping_due = 0
    try:
        from utils.accounting_calculations import calculate_shipping_due

        shipping_due = int(calculate_shipping_due() or 0)
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

    shipping_companies: dict[int, str] = {}
    try:
        shipping_companies = {c.id: c.name for c in ShippingCompany.query.all()}
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

    stuck_rows: list[dict[str, Any]] = []
    pending_rows: list[dict[str, Any]] = []
    try:
        stuck_invoices = (
            _apply_monitor_filters(
                Invoice.query.options(joinedload(Invoice.customer), joinedload(Invoice.employee)).filter(
                    Invoice.status == "جاري الشحن", Invoice.created_at <= stuck_cutoff
                ),
                filters,
            )
            .order_by(Invoice.created_at.asc())
            .limit(table_limit)
            .all()
        )
        for inv in stuck_invoices:
            ref = inv.scheduled_date or inv.created_at or now
            days_in_status = max(0, (now - ref).days)
            stuck_rows.append(
                {
                    "id": inv.id,
                    "customer": (inv.customer_name or "—").strip(),
                    "employee": (inv.employee_name or "—").strip(),
                    "total_display": _fmt_money(inv.total),
                    "shipping_company": shipping_companies.get(inv.shipping_company_id, "غير محدد"),
                    "created_display": (inv.created_at or now).strftime("%Y-%m-%d %H:%M"),
                    "last_update_display": ref.strftime("%Y-%m-%d %H:%M") if ref else "—",
                    "days_in_status": days_in_status,
                    "status_class": "danger" if days_in_status >= 10 else "warning",
                    "order_url": f"/orders/{inv.id}",
                }
            )

        pending_invoices = (
            _apply_monitor_filters(
                Invoice.query.options(joinedload(Invoice.customer), joinedload(Invoice.employee)).filter(
                    Invoice.status == "تم الطلب"
                ),
                filters,
            )
            .order_by(Invoice.created_at.asc())
            .limit(table_limit)
            .all()
        )
        for inv in pending_invoices:
            ref = inv.created_at or now
            age_days = max(0, (now - ref).days)
            pending_rows.append(
                {
                    "id": inv.id,
                    "customer": (inv.customer_name or "—").strip(),
                    "employee": (inv.employee_name or "—").strip(),
                    "total_display": _fmt_money(inv.total),
                    "created_display": ref.strftime("%Y-%m-%d %H:%M"),
                    "age_days": age_days,
                    "status_class": "danger" if age_days >= 7 else ("warning" if age_days >= 3 else "success"),
                    "order_url": f"/orders/{inv.id}",
                }
            )
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

    status_distribution: list[dict[str, Any]] = []
    funnel = {"ordered": 0, "shipping": 0, "delivered": 0, "returned": 0}
    delivered_rate = 0.0
    try:
        dist_rows = (
            _apply_monitor_filters(
                db.session.query(Invoice.status, func.count(Invoice.id)).filter(
                    Invoice.created_at >= date_from, Invoice.created_at <= date_to
                ),
                filters,
            )
            .group_by(Invoice.status)
            .all()
        )
        total_in_period = sum(int(c or 0) for _, c in dist_rows) or 1
        delivered_cond = or_(Invoice.status.in_(DELIVERED_STATUSES), Invoice.payment_status.in_(("مسدد", "تم التوصيل")))
        for status, cnt in sorted(dist_rows, key=lambda x: -int(x[1] or 0)):
            count = int(cnt or 0)
            status_distribution.append({"status": status or "غير محدد", "count": count, "pct": round(count / total_in_period * 100, 1)})
            if status == "تم الطلب":
                funnel["ordered"] = count
            elif status == "جاري الشحن":
                funnel["shipping"] = count
            elif status in DELIVERED_STATUSES or status == "مسدد":
                funnel["delivered"] += count
            elif status in RETURN_STATUSES or status in CANCELED_STATUSES:
                funnel["returned"] += count

        delivered_count = int(
            _apply_monitor_filters(
                db.session.query(func.count(Invoice.id)).filter(
                    Invoice.created_at >= date_from, Invoice.created_at <= date_to, delivered_cond
                ),
                filters,
            ).scalar()
            or 0
        )
        delivered_rate = round(delivered_count / total_in_period * 100, 1) if total_in_period else 0.0
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

    shipping_breakdown: list[dict[str, Any]] = []
    try:
        rows = (
            _apply_monitor_filters(
                db.session.query(
                    Invoice.shipping_company_id,
                    func.count(Invoice.id).label("shipping_count"),
                    func.coalesce(
                        func.sum(case((Invoice.status == "جاري الشحن", 1), else_=0)),
                        0,
                    ).label("active_shipping"),
                ).filter(Invoice.shipping_company_id.isnot(None), Invoice.status.in_(("تم الطلب", "جاري الشحن"))),
                filters,
            )
            .group_by(Invoice.shipping_company_id)
            .all()
        )
        for company_id, total_ship, active in rows:
            stuck_n = _apply_monitor_filters(
                Invoice.query.filter(
                    Invoice.shipping_company_id == company_id,
                    Invoice.status == "جاري الشحن",
                    Invoice.created_at <= stuck_cutoff,
                ),
                filters,
            ).count()
            shipping_breakdown.append(
                {
                    "name": shipping_companies.get(company_id, f"شركة #{company_id}"),
                    "active_shipping": int(active or 0),
                    "total_open": int(total_ship or 0),
                    "stuck_count": int(stuck_n or 0),
                }
            )
        shipping_breakdown.sort(key=lambda x: (-x["stuck_count"], -x["active_shipping"]))
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

    employee_breakdown: list[dict[str, Any]] = []
    try:
        from models.employee import Employee

        emp_map = {e.id: e.name for e in Employee.query.filter(Employee.is_active.is_(True)).all()}
        if filters and filters.get("employee_id"):
            emp_map = {k: v for k, v in emp_map.items() if k == filters["employee_id"]}
        rows = (
            _apply_monitor_filters(
                db.session.query(
                    Invoice.employee_id,
                    func.coalesce(func.sum(case((Invoice.status == "تم الطلب", 1), else_=0)), 0).label("pending_n"),
                    func.coalesce(func.sum(case((Invoice.status == "جاري الشحن", 1), else_=0)), 0).label("shipping_n"),
                    func.min(case((Invoice.status == "تم الطلب", Invoice.created_at), else_=None)).label("oldest_pending"),
                ).filter(Invoice.employee_id.isnot(None), Invoice.status.in_(("تم الطلب", "جاري الشحن"))),
                filters,
            )
            .group_by(Invoice.employee_id)
            .all()
        )
        for emp_id, pending_n, shipping_n, oldest in rows:
            age = 0
            if oldest:
                age = max(0, (now - oldest).days)
            employee_breakdown.append(
                {
                    "name": emp_map.get(emp_id, f"موظف #{emp_id}"),
                    "pending_count": int(pending_n or 0),
                    "shipping_count": int(shipping_n or 0),
                    "oldest_pending_days": age,
                }
            )
        employee_breakdown.sort(key=lambda x: (-x["oldest_pending_days"], -x["pending_count"]))
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

    alerts = _build_operational_alerts(counts, settings)
    summary = {
        "pending_count": counts["pending_count"],
        "shipping_count": counts["shipping_count"],
        "shipping_stuck_count": counts["shipping_stuck_count"],
        "shipping_due": shipping_due,
        "shipping_due_display": _fmt_money(shipping_due),
        "delivered_rate": delivered_rate,
    }
    health_score = _operational_health_score(summary, alerts, delivered_rate)
    summary["health_score"] = health_score

    return {
        "date_from": date_from,
        "date_to": date_to,
        "stuck_days": stuck_days,
        "summary": summary,
        "stuck_shipping": stuck_rows,
        "pending_orders": pending_rows,
        "status_distribution": status_distribution,
        "shipping_breakdown": shipping_breakdown,
        "employee_breakdown": employee_breakdown,
        "funnel": funnel,
        "alerts": alerts,
        "health_score": health_score,
        "chart": _operational_daily_chart(date_from, date_to, filters=filters),
    }


def _ephemeral_from_financial(data: dict[str, Any]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    summary = data.get("summary") or {}
    crit = int(summary.get("critical_count") or 0)
    warn_only = int(summary.get("warning_count") or 0)
    listed = int(summary.get("overdue_listed") or 0)

    for item in data.get("alerts") or []:
        source = item.get("source") or ""
        entry = {
            "type": item.get("type") or "info",
            "icon": item.get("icon") or "ℹ️",
            "message": f"مراقب مالي: {item.get('message') or ''}",
            "action": item.get("action") or FINANCIAL_MONITOR_URL,
            "source": source,
            "decisions": _nav_decisions(("فتح مركز المراقبة", FINANCIAL_MONITOR_URL), ("عرض الطلبات", "/orders/")),
        }
        if source == "watchdog_overdue":
            entry["decisions"] = _nav_decisions(
                ("فتح مركز المراقبة", FINANCIAL_MONITOR_URL),
                ("عرض الطلبات", "/orders/"),
                ("مساعد مالي", "/assistant/chat"),
            )
            if crit > 0:
                entry["message"] = f"مراقب مالي: {crit} طلب(ات) حرجة — عيّنة: {listed}."
            elif warn_only > 0:
                entry["message"] = f"مراقب مالي: {warn_only} طلب(ات) متأخرة."
        elif source in ("watchdog_negative_operating", "watchdog_cash_basis_profit"):
            entry["decisions"] = _nav_decisions(
                ("فتح مركز المراقبة", FINANCIAL_MONITOR_URL),
                ("الحسابات", "/accounts"),
                ("المصاريف", "/expenses"),
            )
        elif source in ("watchdog_net_loss", "watchdog_expense_ratio", "watchdog_low_profit_ratio"):
            entry["decisions"] = _nav_decisions(("فتح مركز المراقبة", FINANCIAL_MONITOR_URL), ("الحسابات", "/accounts"))
        alerts.append(entry)
    return alerts


def _ephemeral_from_operational(data: dict[str, Any]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for item in data.get("alerts") or []:
        source = item.get("source") or ""
        entry = {
            "type": item.get("type") or "info",
            "icon": item.get("icon") or "ℹ️",
            "message": f"مراقب تشغيلي: {item.get('message') or ''}",
            "action": item.get("action") or OPERATIONAL_MONITOR_URL,
            "source": source,
            "decisions": _nav_decisions(("فتح مركز المراقبة", OPERATIONAL_MONITOR_URL)),
        }
        if source == "watchdog_shipping_stuck":
            entry["decisions"] = _nav_decisions(
                ("فتح مركز المراقبة", OPERATIONAL_MONITOR_URL),
                ("شحن", "/orders/shipping"),
                ("كل الطلبات", "/orders/"),
            )
        elif source == "watchdog_pending_backlog":
            entry["decisions"] = _nav_decisions(
                ("فتح مركز المراقبة", OPERATIONAL_MONITOR_URL),
                ("طلبات جديدة", "/orders/ordered"),
            )
        alerts.append(entry)
    return alerts


def get_watchdog_ephemeral_alerts() -> list[dict[str, Any]]:
    now = datetime.utcnow()
    date_from = now - timedelta(days=30)
    try:
        settings = get_monitor_settings()
        fin = build_financial_monitor_data(date_from, now, settings=settings)
        op = build_operational_monitor_data(date_from, now, settings=settings)
        fin_alerts = _ephemeral_from_financial(fin)
        op_alerts = _ephemeral_from_operational(op)
        if fin_alerts and op_alerts:
            for entry in fin_alerts + op_alerts:
                prev = entry.get("decisions") or []
                extra = tuple(
                    (d.get("label"), d.get("href"))
                    for d in prev[:2]
                    if d.get("label") and d.get("href")
                )
                entry["decisions"] = _nav_decisions(
                    ("نظرة عامة — مركز المراقبة", OVERVIEW_MONITOR_URL),
                    *extra,
                )
        return fin_alerts + op_alerts
    except Exception:
        return []


def persist_watchdog_alerts() -> int:
    key = _tenant_key()
    now = time.time()
    if _last_persist_ts.get(key, 0) > now - _WATCHDOG_PERSIST_COOLDOWN_SEC:
        return 0

    inserted = 0
    settings = get_monitor_settings()
    try:
        fin_now = datetime.utcnow()
        fin = build_financial_monitor_data(fin_now - timedelta(days=30), fin_now, settings=settings)
        op = build_operational_monitor_data(fin_now - timedelta(days=30), fin_now, settings=settings)
        summary = fin.get("summary") or {}
        op_summary = op.get("summary") or {}

        crit = int(summary.get("critical_count") or 0)
        listed = int(summary.get("overdue_listed") or 0)
        warn_only = int(summary.get("warning_count") or 0)
        pending_min = int(settings.get("pending_backlog_alert_min") or 22)
        stuck_min = int(settings.get("shipping_stuck_alert_min") or 3)
        loss_threshold = int(settings.get("paid_sales_loss_threshold") or 500_000)

        if listed > 0 and not _recent_system_alert("watchdog_overdue_digest", hours=5):
            db.session.add(
                SystemAlert(
                    alert_type="watchdog_overdue_digest",
                    title="مراقب مالي — طلبات متأخرة",
                    message=(
                        f"حرجة={crit}، تحذير={warn_only}، عيّنة={listed}. "
                        f"راجع {FINANCIAL_MONITOR_URL}."
                    ),
                    priority="high" if crit > 0 else "medium",
                    related_type="watchdog",
                    related_id=None,
                )
            )
            inserted += 1

        pending = int(op_summary.get("pending_count") or 0)
        if pending >= pending_min and not _recent_system_alert("watchdog_pending_digest", hours=8):
            db.session.add(
                SystemAlert(
                    alert_type="watchdog_pending_digest",
                    title="مراقب تشغيلي — تراكم «تم الطلب»",
                    message=f"يوجد {pending} طلب. راجع {OPERATIONAL_MONITOR_URL}.",
                    priority="medium",
                    related_type="watchdog",
                    related_id=None,
                )
            )
            inserted += 1

        shipping_stuck = int(op_summary.get("shipping_stuck_count") or 0)
        if shipping_stuck >= stuck_min and not _recent_system_alert("watchdog_shipping_stuck_digest", hours=6):
            db.session.add(
                SystemAlert(
                    alert_type="watchdog_shipping_stuck_digest",
                    title="مراقب تشغيلي — شحن عالق",
                    message=f"{shipping_stuck} طلب شحن عالق. راجع {OPERATIONAL_MONITOR_URL}.",
                    priority="medium",
                    related_type="watchdog",
                    related_id=None,
                )
            )
            inserted += 1

        net_profit = int(summary.get("booked_profit") or 0)
        paid = int(summary.get("paid_sales") or 0)
        if paid > loss_threshold and net_profit < 0 and not _recent_system_alert("watchdog_negative_profit_digest", hours=8):
            db.session.add(
                SystemAlert(
                    alert_type="watchdog_negative_profit_digest",
                    title="مراقب مالي — خسارة في الفترة",
                    message="الربح سالب للفترة الأخيرة. راجع الحسابات.",
                    priority="high",
                    related_type="watchdog",
                    related_id=None,
                )
            )
            inserted += 1

        if inserted:
            db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return 0

    _last_persist_ts[key] = now
    return inserted
