"""مركز المراقبة الموحّد — تجميع بيانات الألسنة الثلاثة."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, or_

from extensions import db
from models.branch import Branch
from models.employee import Employee
from models.invoice import Invoice
from models.page import Page
from models.system_alert import SystemAlert
from utils.date_periods import get_period_dates
from utils.monitor_settings import MONITORS_HUB_URL, get_monitor_settings

RETURN_STATUSES = ("مرتجع", "راجع", "راجعة", "راجعه")
CANCELED_STATUSES = ("ملغي",)
DELIVERED_STATUSES = ("تم التوصيل", "مسدد", "واصل", "واصلة")

VALID_TABS = frozenset({"overview", "financial", "operational", "performance"})
_ALERT_SEVERITY = {"danger": 0, "warning": 1, "info": 2}


def parse_monitor_filters(
    *,
    branch_id: int | None = None,
    page_id: int | None = None,
    employee_id: int | None = None,
) -> dict[str, int | None]:
    return {
        "branch_id": int(branch_id) if branch_id else None,
        "page_id": int(page_id) if page_id else None,
        "employee_id": int(employee_id) if employee_id else None,
    }


def _apply_invoice_filters(query, filters: dict[str, int | None] | None):
    if not filters:
        return query
    if filters.get("branch_id"):
        query = query.filter(Invoice.branch_id == filters["branch_id"])
    if filters.get("page_id"):
        query = query.filter(Invoice.page_id == filters["page_id"])
    if filters.get("employee_id"):
        query = query.filter(Invoice.employee_id == filters["employee_id"])
    return query


def _health_class(score: int) -> str:
    if score >= 70:
        return "success"
    if score >= 40:
        return "warning"
    return "danger"


def get_monitor_filter_options() -> dict[str, list[dict[str, Any]]]:
    branches = [
        {"id": b.id, "name": b.name}
        for b in Branch.query.filter(Branch.is_active.is_(True)).order_by(Branch.name).all()
    ]
    pages = [{"id": p.id, "name": p.name} for p in Page.query.order_by(Page.name).all()]
    employees = [
        {"id": e.id, "name": e.name}
        for e in Employee.query.filter(Employee.is_active.is_(True), Employee.role != "admin")
        .order_by(Employee.name)
        .all()
    ]
    return {"branches": branches, "pages": pages, "employees": employees}


def get_watchdog_saved_alerts(limit: int = 15) -> list[dict[str, Any]]:
    try:
        rows = (
            SystemAlert.query.filter_by(related_type="watchdog", is_dismissed=False)
            .order_by(SystemAlert.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": a.id,
                "alert_type": a.alert_type,
                "title": a.title,
                "message": a.message,
                "priority": a.priority,
                "is_read": bool(a.is_read),
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "created_display": a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else "—",
            }
            for a in rows
        ]
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return []


def fmt_money(value) -> str:
    return f"{int(value or 0):,} د.ع"


def parse_monitor_date(value, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        return datetime.strptime(str(value), "%Y-%m-%d")
    except ValueError:
        return fallback


def resolve_monitor_date_range(
    *,
    period: str | None = None,
    date_from_raw: str | None = None,
    date_to_raw: str | None = None,
) -> tuple[datetime, datetime, str]:
    now = datetime.utcnow()
    period_key = (period or "last_30_days").strip()
    if period_key == "custom" and date_from_raw and date_to_raw:
        d_from = parse_monitor_date(date_from_raw, now - timedelta(days=30)).date()
        d_to = parse_monitor_date(date_to_raw, now).date()
    else:
        if period_key not in (
            "today",
            "yesterday",
            "last_7_days",
            "last_30_days",
            "this_month",
            "this_week",
        ):
            period_key = "last_30_days"
        d_from, d_to = get_period_dates(period_key)

    date_from = datetime.combine(d_from, datetime.min.time())
    date_to = datetime.combine(d_to, datetime.max.time()).replace(microsecond=999999)
    if date_from > date_to:
        date_from, date_to = date_to.replace(hour=0, minute=0, second=0, microsecond=0), date_from.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
    return date_from, date_to, period_key


def _not_bad_status_condition():
    return (
        or_(Invoice.status.is_(None), ~Invoice.status.in_(RETURN_STATUSES + CANCELED_STATUSES)),
        or_(Invoice.payment_status.is_(None), ~Invoice.payment_status.in_(RETURN_STATUSES + CANCELED_STATUSES)),
    )


def _rate(part, total):
    return round((float(part or 0) / float(total or 1)) * 100, 1)


def build_performance_monitor_data(
    date_from: datetime,
    date_to: datetime,
    min_orders: int,
    min_sales: int,
    *,
    filters: dict[str, int | None] | None = None,
) -> dict[str, Any]:
    valid_conditions = _not_bad_status_condition()
    delivered_condition = or_(
        Invoice.status.in_(DELIVERED_STATUSES),
        Invoice.payment_status.in_(("مسدد", "تم التوصيل")),
    )

    page_rows = (
        _apply_invoice_filters(
            db.session.query(
                Invoice.page_id,
                func.count(Invoice.id).label("orders_count"),
                func.coalesce(func.sum(case((delivered_condition, 1), else_=0)), 0).label("delivered_count"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                or_(
                                    Invoice.status.in_(RETURN_STATUSES + CANCELED_STATUSES),
                                    Invoice.payment_status.in_(RETURN_STATUSES + CANCELED_STATUSES),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("returned_count"),
                func.coalesce(
                    func.sum(case((valid_conditions[0] & valid_conditions[1], Invoice.total), else_=0)),
                    0,
                ).label("clean_sales"),
            ),
            filters,
        )
        .filter(Invoice.created_at >= date_from, Invoice.created_at <= date_to)
        .group_by(Invoice.page_id)
        .all()
    )
    page_stats = {row.page_id: row for row in page_rows}
    pages = Page.query.order_by(Page.name).all()
    if filters and filters.get("page_id"):
        pages = [p for p in pages if p.id == filters["page_id"]]
    page_monitor = []
    total_page_orders = 0
    total_page_sales = 0

    for page in pages:
        row = page_stats.get(page.id)
        orders_count = int(getattr(row, "orders_count", 0) or 0)
        clean_sales = int(getattr(row, "clean_sales", 0) or 0)
        delivered_count = int(getattr(row, "delivered_count", 0) or 0)
        returned_count = int(getattr(row, "returned_count", 0) or 0)
        return_rate = _rate(returned_count, orders_count)
        delivered_rate = _rate(delivered_count, orders_count)

        if orders_count == 0:
            health, health_class, note = "خامد", "danger", "لا توجد طلبات ضمن الفترة"
        elif return_rate >= 30:
            health, health_class, note = "يحتاج متابعة", "warning", "نسبة الراجع/الإلغاء عالية"
        elif orders_count >= 3 and delivered_rate < 40:
            health, health_class, note = "توصيل ضعيف", "warning", "نسبة الوصول أقل من المطلوب"
        else:
            health, health_class, note = "مستقر", "success", "الأداء ضمن الطبيعي"

        total_page_orders += orders_count
        total_page_sales += clean_sales
        page_monitor.append(
            {
                "id": page.id,
                "name": page.name,
                "orders_count": orders_count,
                "sales": clean_sales,
                "sales_display": fmt_money(clean_sales),
                "delivered_count": delivered_count,
                "delivered_rate": delivered_rate,
                "returned_count": returned_count,
                "return_rate": return_rate,
                "assigned_employees": ", ".join(emp.name for emp in page.employees.all()) or "غير محدد",
                "health": health,
                "health_class": health_class,
                "note": note,
            }
        )

    unassigned_row = page_stats.get(None)
    unassigned_orders = int(getattr(unassigned_row, "orders_count", 0) or 0)
    if unassigned_orders:
        unassigned_sales = int(getattr(unassigned_row, "clean_sales", 0) or 0)
        unassigned_returned = int(getattr(unassigned_row, "returned_count", 0) or 0)
        unassigned_delivered = int(getattr(unassigned_row, "delivered_count", 0) or 0)
        total_page_orders += unassigned_orders
        total_page_sales += unassigned_sales
        page_monitor.append(
            {
                "id": None,
                "name": "طلبات بدون بيج",
                "orders_count": unassigned_orders,
                "sales": unassigned_sales,
                "sales_display": fmt_money(unassigned_sales),
                "delivered_count": unassigned_delivered,
                "delivered_rate": _rate(unassigned_delivered, unassigned_orders),
                "returned_count": unassigned_returned,
                "return_rate": _rate(unassigned_returned, unassigned_orders),
                "assigned_employees": "غير محدد",
                "health": "ناقص ربط",
                "health_class": "warning",
                "note": "طلبات لا تحتوي page_id",
            }
        )

    page_monitor.sort(key=lambda item: (item["health_class"] == "success", -item["orders_count"]))

    employee_rows = (
        _apply_invoice_filters(
            db.session.query(
                Invoice.employee_id,
                func.count(Invoice.id).label("orders_count"),
                func.coalesce(func.sum(case((valid_conditions[0] & valid_conditions[1], Invoice.total), else_=0)), 0).label("sales"),
                func.coalesce(func.sum(case((delivered_condition, 1), else_=0)), 0).label("delivered_count"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                or_(
                                    Invoice.status.in_(RETURN_STATUSES + CANCELED_STATUSES),
                                    Invoice.payment_status.in_(RETURN_STATUSES + CANCELED_STATUSES),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("returned_count"),
                func.max(Invoice.created_at).label("last_order_at"),
            ),
            filters,
        )
        .filter(Invoice.created_at >= date_from, Invoice.created_at <= date_to)
        .group_by(Invoice.employee_id)
        .all()
    )
    employee_stats = {row.employee_id: row for row in employee_rows}
    employees = (
        Employee.query.filter(Employee.is_active.is_(True), Employee.role != "admin").order_by(Employee.name).all()
    )
    if filters and filters.get("employee_id"):
        employees = [e for e in employees if e.id == filters["employee_id"]]
    employee_monitor = []
    weak_employees = []
    total_employee_orders = 0
    total_employee_sales = 0

    for employee in employees:
        row = employee_stats.get(employee.id)
        orders_count = int(getattr(row, "orders_count", 0) or 0)
        sales = int(getattr(row, "sales", 0) or 0)
        delivered_count = int(getattr(row, "delivered_count", 0) or 0)
        returned_count = int(getattr(row, "returned_count", 0) or 0)
        last_order_at = getattr(row, "last_order_at", None)
        reasons = []
        if orders_count < min_orders:
            reasons.append(f"طلبات أقل من {min_orders}")
        if min_sales > 0 and sales < min_sales:
            reasons.append(f"مبيعات أقل من {fmt_money(min_sales)}")
        if orders_count > 0 and _rate(returned_count, orders_count) >= 30:
            reasons.append("راجع/إلغاء عالي")

        item = {
            "id": employee.id,
            "name": employee.name,
            "username": employee.username,
            "role": "مدير" if employee.role == "admin" else "كاشير",
            "orders_count": orders_count,
            "sales": sales,
            "sales_display": fmt_money(sales),
            "delivered_count": delivered_count,
            "returned_count": returned_count,
            "return_rate": _rate(returned_count, orders_count),
            "last_order_at": last_order_at,
            "last_order_display": last_order_at.strftime("%Y-%m-%d %H:%M") if last_order_at else "لا يوجد",
            "status": "ضعيف" if reasons else "طبيعي",
            "status_class": "danger" if reasons else "success",
            "reason": "، ".join(reasons) if reasons else "الأداء ضمن الحد",
        }
        total_employee_orders += orders_count
        total_employee_sales += sales
        employee_monitor.append(item)
        if reasons:
            weak_employees.append(item)

    employee_monitor.sort(key=lambda item: (item["status_class"] == "success", item["orders_count"], item["sales"]))
    weak_employees.sort(key=lambda item: (item["orders_count"], item["sales"]))
    alerts = [page for page in page_monitor if page["health_class"] in ("danger", "warning")][:8]

    weak_count = len(weak_employees)
    health_score = max(0, min(100, 100 - weak_count * 8 - len(alerts) * 5))

    return {
        "date_from": date_from,
        "date_to": date_to,
        "min_orders": min_orders,
        "min_sales": min_sales,
        "page_monitor": page_monitor,
        "employee_monitor": employee_monitor,
        "weak_employees": weak_employees,
        "alerts": alerts,
        "health_score": health_score,
        "summary": {
            "pages_count": len(page_monitor),
            "page_orders": total_page_orders,
            "page_sales": total_page_sales,
            "page_sales_display": fmt_money(total_page_sales),
            "employees_count": len(employee_monitor),
            "weak_employees_count": weak_count,
            "employee_orders": total_employee_orders,
            "employee_sales": total_employee_sales,
            "employee_sales_display": fmt_money(total_employee_sales),
            "health_score": health_score,
        },
    }


def build_overview_monitor_data(
    financial: dict[str, Any],
    operational: dict[str, Any],
    performance: dict[str, Any],
) -> dict[str, Any]:
    fin_score = int(financial.get("health_score") or 0)
    op_score = int(operational.get("health_score") or 0)
    perf_score = int(performance.get("health_score") or 0)
    health_scores = {
        "financial": {
            "score": fin_score,
            "label": "مالي",
            "tab": "financial",
            "class": _health_class(fin_score),
        },
        "operational": {
            "score": op_score,
            "label": "تشغيلي",
            "tab": "operational",
            "class": _health_class(op_score),
        },
        "performance": {
            "score": perf_score,
            "label": "أداء",
            "tab": "performance",
            "class": _health_class(perf_score),
        },
    }
    combined: list[dict[str, Any]] = []
    for tab_key, data, label in (
        ("financial", financial, "مالي"),
        ("operational", operational, "تشغيلي"),
        ("performance", performance, "أداء"),
    ):
        for alert in data.get("alerts") or []:
            item = dict(alert)
            item["source_tab"] = tab_key
            item["source_label"] = label
            if tab_key == "performance" and "title" not in item:
                item["title"] = item.get("name") or "تنبيه أداء"
                item["message"] = item.get("note") or ""
                item["type"] = item.get("type") or "warning"
                item["icon"] = item.get("icon") or "⚠️"
            combined.append(item)
    combined.sort(
        key=lambda x: (
            _ALERT_SEVERITY.get(str(x.get("type") or "info"), 9),
            str(x.get("title") or ""),
        )
    )

    fin_s = financial.get("summary") or {}
    op_s = operational.get("summary") or {}
    perf_s = performance.get("summary") or {}
    quick_stats = {
        "critical_orders": int(fin_s.get("critical_count") or 0),
        "pending_backlog": int(op_s.get("pending_count") or 0),
        "shipping_stuck": int(op_s.get("shipping_stuck_count") or 0),
        "weak_employees": int(perf_s.get("weak_employees_count") or 0),
    }
    health_score = round((fin_score + op_score + perf_score) / 3)

    return {
        "health_scores": health_scores,
        "top_alerts": combined[:6],
        "quick_stats": quick_stats,
        "health_score": health_score,
        "summary": {
            "health_score": health_score,
            "alerts_count": len(combined),
            **quick_stats,
        },
    }


def build_monitors_hub_data(
    tab: str,
    *,
    date_from: datetime,
    date_to: datetime,
    period_key: str,
    overdue_min_days: int | None = None,
    stuck_days: int | None = None,
    min_orders: int | None = None,
    min_sales: int | None = None,
    filters: dict[str, int | None] | None = None,
) -> dict[str, Any]:
    from utils.financial_watchdog import build_financial_monitor_data, build_operational_monitor_data

    settings = get_monitor_settings()
    tab = tab if tab in VALID_TABS else "overview"
    overdue_min_days = overdue_min_days if overdue_min_days is not None else settings["overdue_warning_days"]
    stuck_days = stuck_days if stuck_days is not None else settings["shipping_stuck_days"]
    min_orders = min_orders if min_orders is not None else settings["performance_min_orders"]
    min_sales = min_sales if min_sales is not None else settings["performance_min_sales"]
    filters = filters or {}

    financial = build_financial_monitor_data(
        date_from, date_to, overdue_min_days=overdue_min_days, settings=settings, filters=filters
    )
    operational = build_operational_monitor_data(
        date_from, date_to, stuck_days=stuck_days, settings=settings, filters=filters
    )
    performance = build_performance_monitor_data(
        date_from, date_to, min_orders, min_sales, filters=filters
    )
    overview = build_overview_monitor_data(financial, operational, performance)

    tab_map = {
        "overview": overview,
        "financial": financial,
        "operational": operational,
        "performance": performance,
    }
    tab_data = tab_map[tab]

    return {
        "tab": tab,
        "period": period_key,
        "date_from": date_from,
        "date_to": date_to,
        "settings": settings,
        "filters": filters,
        "filter_options": get_monitor_filter_options(),
        "saved_alerts": get_watchdog_saved_alerts(),
        "financial": financial,
        "operational": operational,
        "performance": performance,
        "overview": overview,
        "tab_data": tab_data,
        "hub_url": MONITORS_HUB_URL,
    }


def build_monitor_summary_payload(hub_data: dict[str, Any]) -> dict[str, Any]:
    tab = hub_data.get("tab") or "overview"
    tab_data = hub_data.get("tab_data") or {}
    summary = tab_data.get("summary") or {}
    return {
        "tab": tab,
        "summary": summary,
        "alerts": tab_data.get("alerts") or tab_data.get("top_alerts") or [],
        "health_score": tab_data.get("health_score") or summary.get("health_score"),
        "updated_at": datetime.utcnow().isoformat(),
    }


def build_monitor_assistant_context(hub_data: dict[str, Any]) -> str:
    payload = build_monitor_summary_payload(hub_data)
    tab = payload.get("tab") or "overview"
    summary = payload.get("summary") or {}
    lines = [
        f"سياق مركز المراقبة — اللسان: {tab}",
        f"صحة اللسان: {payload.get('health_score')}/100",
    ]
    for key in ("critical_orders", "pending_backlog", "shipping_stuck", "weak_employees", "revenue", "paid_sales", "pending_count"):
        if key in summary and summary[key] is not None:
            lines.append(f"{key}: {summary[key]}")
    for alert in (payload.get("alerts") or [])[:5]:
        title = alert.get("title") or alert.get("name") or "تنبيه"
        msg = alert.get("message") or alert.get("note") or ""
        lines.append(f"- {title}: {msg}")
    return "\n".join(lines)


def build_monitor_live_payload(hub_data: dict[str, Any]) -> dict[str, Any]:
    tab = hub_data.get("tab") or "overview"
    tab_data = hub_data.get("tab_data") or {}
    payload: dict[str, Any] = {
        "tab": tab,
        "health_score": tab_data.get("health_score") or (tab_data.get("summary") or {}).get("health_score"),
        "summary": tab_data.get("summary") or {},
        "alerts": tab_data.get("alerts") or tab_data.get("top_alerts") or [],
        "updated_at": datetime.utcnow().isoformat(),
        "saved_alerts": hub_data.get("saved_alerts") or [],
    }
    if tab == "overview":
        payload["overview"] = {
            "health_scores": tab_data.get("health_scores") or {},
            "quick_stats": tab_data.get("quick_stats") or {},
            "top_alerts": tab_data.get("top_alerts") or [],
        }
    elif tab == "financial":
        payload["tables"] = {
            "overdue_orders": tab_data.get("overdue_orders") or [],
            "top_expenses": tab_data.get("top_expenses") or [],
        }
        payload["chart"] = tab_data.get("chart") or {}
    elif tab == "operational":
        payload["tables"] = {
            "pending_orders": tab_data.get("pending_orders") or [],
            "stuck_shipping": tab_data.get("stuck_shipping") or [],
            "shipping_breakdown": tab_data.get("shipping_breakdown") or [],
            "employee_breakdown": tab_data.get("employee_breakdown") or [],
        }
        payload["chart"] = tab_data.get("chart") or {}
        payload["funnel"] = tab_data.get("funnel") or {}
        payload["status_distribution"] = tab_data.get("status_distribution") or []
    elif tab == "performance":
        payload["tables"] = {
            "page_monitor": tab_data.get("page_monitor") or [],
            "weak_employees": tab_data.get("weak_employees") or [],
            "employee_monitor": tab_data.get("employee_monitor") or [],
        }
    return payload
