"""HTTP layer for the reports engine. No calculations here — services/reports_service.py.

Every endpoint checks the session, the reports permission and the section
permission on the server; tenant isolation comes from the session's tenant
database and branch isolation from FINORA's ORM branch scope.
"""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, render_template, request, session, url_for

from services import reports_export as rx
from services import reports_service as rs

reports_api_bp = Blueprint("reports_api", __name__, url_prefix="/reports/api/v2")


def _error(message: str, status: int):
    return jsonify({"success": False, "error": message}), status


@reports_api_bp.before_request
def _guard():
    if not session.get("user_id"):
        return _error("انتهت الجلسة، سجّل الدخول من جديد", 401)
    if not rs.check_permission("view_reports"):
        return _error("ليست لديك صلاحية عرض التقارير", 403)
    _ensure_schemas()
    return None


def _ensure_schemas() -> None:
    """Same guards FINORA's own pages run before reading these tables (cached per tenant DB)."""
    from utils.inventory_lots import ensure_inventory_lot_schema
    from utils.product_schema_guard import ensure_product_schema
    from utils.purchase_schema_guard import ensure_purchase_schema
    from utils.treasury_schema_guard import ensure_treasury_schema

    from routes.purchases import _ensure_purchase_schema as ensure_purchase_page_schema

    ensure_product_schema()
    ensure_purchase_schema()
    ensure_purchase_page_schema()
    ensure_treasury_schema()
    ensure_inventory_lot_schema()


@reports_api_bp.errorhandler(rs.ReportError)
def _report_error(exc: rs.ReportError):
    return _error(exc.message, exc.status)


def _filters() -> rs.ReportFilters:
    return rs.parse_filters(request.args)


def _company() -> tuple[str, str | None]:
    from models.invoice_settings import InvoiceSettings

    settings = InvoiceSettings.query.first()
    if not settings:
        return "FINORA", None
    name = (getattr(settings, "report_company_name", None) or settings.company_name or "").strip() or "FINORA"
    logo = None
    if getattr(settings, "report_show_logo", True):
        path = getattr(settings, "report_logo_path", None) or getattr(settings, "logo_path", None)
        if path:
            logo = path if str(path).startswith(("http", "/")) else url_for("static", filename=path)
    return name, logo


def _names(filters: rs.ReportFilters) -> tuple[str | None, str | None]:
    from models.branch import Branch
    from models.employee import Employee

    branch = (
        Branch.query.execution_options(skip_branch_scope=True).get(filters.branch_id) if filters.branch_id else None
    )
    employee = Employee.query.get(filters.employee_id) if filters.employee_id else None
    return (branch.name if branch else None), (employee.name if employee else None)


@reports_api_bp.get("/meta")
def meta():
    """Filter choices the user may pick: only their visible branches and employees."""
    from flask import g

    from models.employee import Employee
    from utils.branch_scope import allowed_branch_ids, is_general_admin

    branches = list(getattr(g, "branches", []) or [])
    allowed_ids = set(allowed_branch_ids())
    if not is_general_admin():
        branches = [b for b in branches if int(b.id) in allowed_ids]
    employees = Employee.query.filter(Employee.is_active.is_(True)).order_by(Employee.name.asc()).all()
    company, _logo = _company()
    return jsonify(
        {
            "success": True,
            "company": company,
            "sections": {s: rs.can_view(s) for s in rs.SECTIONS},
            "can_export": rs.check_permission(rs.EXPORT_PERMISSION),
            "can_pick_branch": is_general_admin() or len(branches) > 1,
            "branches": [{"id": int(b.id), "name": b.name} for b in branches],
            "employees": [{"id": int(e.id), "name": e.name} for e in employees],
            "periods": list(rs.PERIODS),
        }
    )


@reports_api_bp.get("/dashboard")
def dashboard():
    filters = _filters()
    with rs.branch_scope(filters):
        data = rs.dashboard(filters)
        data["sales_series"] = rs.sales_series(filters, request.args.get("grain") or "day")
    return jsonify({"success": True, **data})


@reports_api_bp.get("/series")
def series():
    filters = _filters()
    with rs.branch_scope(filters):
        rows = rs.sales_series(filters, request.args.get("grain") or "day")
    return jsonify({"success": True, "rows": rows})


@reports_api_bp.get("/section/<section>")
def section(section: str):
    rs.require_section(section)
    filters = _filters()
    with rs.branch_scope(filters):
        data = rs.section_report(section, filters, request.args)
    return jsonify({"success": True, "section": section, **data})


def _export_parts(section: str):
    rs.require_section(section)
    if not rs.check_permission(rs.EXPORT_PERMISSION):
        raise rs.ReportError("ليست لديك صلاحية تصدير التقارير", 403)
    filters = _filters()
    with rs.branch_scope(filters):
        report, rows, columns = rx.collect(section, filters, request.args)
        branch, employee = _names(filters)
    return filters, report, rows, columns, rx.filter_lines(filters, branch, employee)


@reports_api_bp.get("/export/<section>.xlsx")
def export_xlsx(section: str):
    filters, report, rows, columns, lines = _export_parts(section)
    company, _logo = _company()
    body = rx.to_xlsx(section, report, rows, columns, lines, company)
    name = f"finora-{section}-{filters.date_from}-{filters.date_to}.xlsx"
    return Response(
        body,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


@reports_api_bp.get("/print/<section>")
def print_view(section: str):
    _filters_obj, report, rows, columns, lines = _export_parts(section)
    company, logo = _company()
    html = rx.to_html(section, report, rows, columns, lines, company, logo, render_template)
    return Response(html, mimetype="text/html", headers={"Cache-Control": "no-store"})
