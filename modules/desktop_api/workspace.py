"""Read-only Smart Workspace adapters over FINORA's existing reporting/audit engines."""
from datetime import datetime, timezone

from flask import g, jsonify, request
from modules.desktop_api.routes import desktop_api_bp
from modules.desktop_api.branches import _authorize


@desktop_api_bp.get("/workspace")
def desktop_workspace():
    denied = _authorize()
    if denied is not None:
        return denied
    # Existing 0.8.0 clients refresh this list and remove the withdrawn entries.
    return jsonify(ok=True, pages=[])


@desktop_api_bp.get("/workspace/sales")
def workspace_sales():
    denied = _authorize()
    if denied is not None:
        return denied
    from services import reports_service as reports
    from modules.reports_api.routes import _ensure_schemas
    from modules.desktop_api.routes import _error

    if not reports.can_view("sales"):
        return _error("ليست لديك صلاحية عرض المبيعات", 403, "forbidden")
    _ensure_schemas()
    # Accept no client tenant/branch override. ORM scope comes from the authenticated session.
    filters = reports.parse_filters({"period": "today"})
    with reports.branch_scope(filters):
        today = reports.sales_totals(filters, filters.date_from, filters.date_to)
        previous = reports.sales_totals(filters, *filters.previous())
    return jsonify(ok=True, value=today["net"], previous=previous["net"],
                   change=reports._pct(today["net"], previous["net"]),
                   date=filters.date_from.isoformat(), captured_at=datetime.now(timezone.utc).isoformat())


# Only documented entities with a native, permission-checked destination are exposed.
ACTIVITY_ENTITIES = {
    "invoice": ("can_see_orders", "orders", "فاتورة"),
    "order": ("can_see_orders", "orders", "طلب"),
    "product": ("can_manage_inventory", "products", "منتج"),
    "customer": ("manage_customers", "customers", "عميل"),
    "purchase": ("can_manage_inventory", "purchases", "شراء"),
}


@desktop_api_bp.get("/workspace/receivables")
def workspace_receivables():
    # Same debt (including documented opening debts and partial payments) as the native Customers screen.
    from modules.desktop_api import customers
    from sqlalchemy import func, case
    denied = customers._authorize()
    if denied is not None:
        return denied
    query, debt, overdue = customers._workspace_query("")
    total = query.with_entities(func.coalesce(func.sum(debt), 0),
                                func.coalesce(func.sum(overdue), 0),
                                func.sum(case((debt > 0, 1), else_=0))).one()
    return jsonify(ok=True, value=int(total[0]), overdue=int(total[1]), debtors=int(total[2] or 0),
                   captured_at=datetime.now(timezone.utc).isoformat())


@desktop_api_bp.get("/workspace/shipping")
def workspace_shipping():
    from modules.desktop_api.shipping_center import _authorize as authorize_shipping
    from models.shipping_report import ShippingReport
    denied = authorize_shipping()
    if denied is not None:
        return denied
    return jsonify(ok=True, open_manifests=ShippingReport.query.filter(ShippingReport.is_executed.is_(False)).count())


@desktop_api_bp.get("/workspace/activity")
def workspace_activity():
    denied = _authorize()
    if denied is not None:
        return denied
    from models.activity_log import ActivityLog
    from utils.branch_scope import allowed_branch_ids, current_employee, is_general_admin
    from utils.permission_checks import employee_can

    employee = current_employee()
    types = [kind for kind, (permission, _, _) in ACTIVITY_ENTITIES.items()
             if employee_can(employee, permission)]
    if not types:
        return jsonify(ok=True, rows=[], has_more=False)
    try:
        before = max(0, int(request.args.get("before", "0")))
    except (TypeError, ValueError):
        from modules.desktop_api.routes import _error
        return _error("مؤشر السجل غير صحيح", 400, "validation_error")
    query = ActivityLog.query.filter(ActivityLog.entity_type.in_(types))
    # ActivityLog is not branch-scoped by the general ORM listener; enforce it explicitly.
    if getattr(g, "independent_branches_enabled", True):
        query = query.filter(ActivityLog.branch_id.in_(allowed_branch_ids()))
    if not is_general_admin(employee):
        query = query.filter(ActivityLog.employee_id == employee.id)
    if before:
        query = query.filter(ActivityLog.id < before)
    records = query.order_by(ActivityLog.id.desc()).limit(21).all()
    labels = {"create": "إضافة", "update": "تعديل", "delete": "حذف", "cancel": "إلغاء", "return": "إرجاع"}
    rows = []
    for record in records[:20]:
        _, window, name = ACTIVITY_ENTITIES[record.entity_type]
        entity_id = str(record.entity_id or "")
        valid_id = entity_id.isdecimal() and 0 < int(entity_id) <= 2**53 - 1
        rows.append({"id": record.id, "title": f"{labels.get(record.action, 'تحديث')} {name}",
                     "actor": record.employee_name or "", "at": record.created_at.replace(tzinfo=timezone.utc).isoformat(),
                     "target": {"window": window, **({"entityId": int(entity_id)} if valid_id else {})},
                     "deleted": record.action == "delete"})
    # Do not return payloads, request paths, IP addresses or customer/financial details.
    return jsonify(ok=True, rows=rows, has_more=len(records) > 20)
