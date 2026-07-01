"""Activity log page and API."""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import or_

from extensions import db
from models.activity_log import ActivityLog
from models.employee import Employee
from utils.decorators import permission_required

activity_bp = Blueprint("activity", __name__)

ACTION_LABELS = {
    "view": "عرض",
    "create": "إنشاء",
    "update": "تعديل",
    "delete": "حذف",
    "login": "دخول",
    "logout": "خروج",
    "login_failed": "دخول فاشل",
    "export": "تصدير",
}

CATEGORY_LABELS = {
    "orders": "الطلبات",
    "pos": "نقطة البيع",
    "inventory": "المخزون",
    "purchases": "المشتريات",
    "finance": "المالية",
    "reports": "التقارير",
    "employees": "الموظفين",
    "customers": "الزبائن",
    "shipping": "الشحن",
    "settings": "الإعدادات",
    "messages": "المراسلة",
    "pages": "البيجات",
    "suppliers": "الموردين",
    "beauty": "التجميل",
    "publisher": "النشر",
    "workspace": "مساحة العمل",
    "social": "السوشيال",
    "auth": "المصادقة",
    "system": "النظام",
}


@activity_bp.route("/")
@permission_required("view_activity")
def activity_page():
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()
    return render_template(
        "activity.html",
        employees=employees,
        action_labels=ACTION_LABELS,
        category_labels=CATEGORY_LABELS,
    )


@activity_bp.route("/api/list")
@permission_required("view_activity")
def activity_list_api():
    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = min(100, max(10, request.args.get("per_page", 50, type=int) or 50))

    q = ActivityLog.query

    employee_id = request.args.get("employee_id", type=int)
    if employee_id:
        q = q.filter(ActivityLog.employee_id == employee_id)

    action = (request.args.get("action") or "").strip()
    if action:
        q = q.filter(ActivityLog.action == action)

    category = (request.args.get("category") or "").strip()
    if category:
        q = q.filter(ActivityLog.category == category)

    search = (request.args.get("q") or "").strip()
    if search:
        like = f"%{search}%"
        q = q.filter(or_(ActivityLog.summary.ilike(like), ActivityLog.request_path.ilike(like)))

    date_from = (request.args.get("date_from") or "").strip()
    if date_from:
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            q = q.filter(ActivityLog.created_at >= dt_from)
        except ValueError:
            pass

    date_to = (request.args.get("date_to") or "").strip()
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            q = q.filter(ActivityLog.created_at <= dt_to)
        except ValueError:
            pass

    q = q.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    items = []
    for row in pagination.items:
        d = row.to_dict()
        d["action_label"] = ACTION_LABELS.get(row.action, row.action)
        d["category_label"] = CATEGORY_LABELS.get(row.category, row.category)
        items.append(d)

    return jsonify(
        {
            "items": items,
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
        }
    )


@activity_bp.route("/api/stats")
@permission_required("view_activity")
def activity_stats_api():
    from sqlalchemy import func

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    total = ActivityLog.query.count()
    today = ActivityLog.query.filter(ActivityLog.created_at >= today_start).count()
    logins_today = ActivityLog.query.filter(
        ActivityLog.created_at >= today_start,
        ActivityLog.action == "login",
    ).count()
    mutations_today = ActivityLog.query.filter(
        ActivityLog.created_at >= today_start,
        ActivityLog.action.in_(("create", "update", "delete")),
    ).count()
    return jsonify(
        {
            "total": total,
            "today": today,
            "logins_today": logins_today,
            "mutations_today": mutations_today,
        }
    )
