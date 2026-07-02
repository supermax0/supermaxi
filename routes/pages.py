# routes/pages.py
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from extensions import db
from models.page import Page, employee_pages
from models.employee import Employee
from models.invoice import Invoice
from sqlalchemy.sql import func
from sqlalchemy import or_

from utils.decorators import permission_required
from utils.permission_checks import employee_can, get_current_employee
from utils.pages_import import bulk_create_pages, extract_page_names_hybrid, MAX_IMAGE_BYTES

pages_bp = Blueprint("pages", __name__, url_prefix="/pages")


def _pages_stats():
    stats = (
        db.session.query(Invoice.page_id, func.count(Invoice.id).label("orders"))
        .filter(Invoice.page_id.isnot(None))
        .group_by(Invoice.page_id)
        .all()
    )
    stats_map = {s.page_id: s.orders for s in stats}
    returned_stats = (
        db.session.query(Invoice.page_id, func.count(Invoice.id).label("returned"))
        .filter(
            Invoice.page_id.isnot(None),
            or_(Invoice.status == "راجع", Invoice.status == "ملغي", Invoice.payment_status == "مرتجع"),
        )
        .group_by(Invoice.page_id)
        .all()
    )
    returned_map = {s.page_id: s.returned for s in returned_stats}
    delivered_stats = (
        db.session.query(Invoice.page_id, func.count(Invoice.id).label("delivered"))
        .filter(Invoice.page_id.isnot(None), or_(Invoice.status == "تم التوصيل", Invoice.status == "مسدد"))
        .group_by(Invoice.page_id)
        .all()
    )
    delivered_map = {s.page_id: s.delivered for s in delivered_stats}
    return stats_map, returned_map, delivered_map


@pages_bp.route("/", methods=["GET", "POST"])
@permission_required("view_pages")
def pages():
    if request.method == "POST":
        if not employee_can(get_current_employee(), "manage_pages"):
            return jsonify({"error": "غير مصرح"}), 403
        page = Page(name=request.form["name"])
        db.session.add(page)
        db.session.commit()
        return redirect(url_for("pages.pages"))

    pages_list = Page.query.all()
    stats_map, returned_map, delivered_map = _pages_stats()
    employees_all = Employee.query.filter_by(is_active=True).all()
    pages_data = []
    for page in pages_list:
        employees_list = page.employees.all()
        pages_data.append(
            {
                "page": page,
                "employees": employees_list,
                "orders_count": stats_map.get(page.id, 0),
                "returned_count": returned_map.get(page.id, 0),
                "delivered_count": delivered_map.get(page.id, 0),
            }
        )
    return render_template(
        "pages.html",
        pages_data=pages_data,
        employees_all=employees_all,
        can_manage_pages=employee_can(get_current_employee(), "manage_pages"),
    )


@pages_bp.route("/delete/<int:id>", methods=["POST"])
@permission_required("manage_pages")
def delete_page(id):
    page = Page.query.get_or_404(id)
    linked = Invoice.query.filter_by(page_id=page.id).count()
    if linked:
        return jsonify({"success": False, "error": f"لا يمكن الحذف: {linked} فاتورة مرتبطة بهذا البيج"}), 400
    db.session.delete(page)
    db.session.commit()
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True})
    return redirect(url_for("pages.pages"))


@pages_bp.route("/employee/<int:employee_id>")
@permission_required("view_pages")
def get_employee_pages(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    pages = employee.pages.all()
    return jsonify({"pages": [{"id": p.id, "name": p.name} for p in pages]})


@pages_bp.route("/employee-orders/<int:employee_id>")
@permission_required("view_pages")
def get_employee_orders(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    orders = Invoice.query.filter_by(employee_id=employee_id).all()
    pages = employee.pages.all()
    page_stats = {}
    for page in pages:
        page_orders = Invoice.query.filter_by(employee_id=employee_id, page_id=page.id).all()
        page_stats[page.id] = {
            "name": page.name,
            "orders_count": len(page_orders),
            "orders": [{"id": o.id, "total": o.total} for o in page_orders],
        }
    return jsonify(
        {
            "employee": {"id": employee.id, "name": employee.name},
            "pages_count": len(pages),
            "pages": [{"id": p.id, "name": p.name} for p in pages],
            "total_orders": len(orders),
            "page_stats": page_stats,
        }
    )


@pages_bp.route("/assign-employees/<int:page_id>", methods=["POST"])
@permission_required("manage_pages")
def assign_page_employees(page_id):
    page = Page.query.get_or_404(page_id)
    data = request.get_json(silent=True) or {}
    employee_ids = data.get("employee_ids") or []
    page.employees = []
    for eid in employee_ids:
        emp = Employee.query.get(eid)
        if emp:
            page.employees.append(emp)
    db.session.commit()
    return jsonify({"success": True, "message": "تم تحديث موظفي البيج"})


@pages_bp.route("/import-from-image", methods=["POST"])
@permission_required("manage_pages")
def import_pages_from_image():
    file = request.files.get("image")
    if not file or not file.filename:
        return jsonify({"success": False, "error": "لم يتم اختيار صورة."}), 400

    image_bytes = file.read()
    if not image_bytes:
        return jsonify({"success": False, "error": "ملف الصورة فارغ."}), 400
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return jsonify({"success": False, "error": "حجم الصورة كبير جداً (الحد الأقصى 8 ميغابايت)."}), 400

    force_ai = str(request.form.get("force_ai") or "").strip().lower() in ("1", "true", "yes", "on")
    result = extract_page_names_hybrid(image_bytes, force_ai=force_ai)
    status = 200 if result.get("success") else 400
    return jsonify(result), status


@pages_bp.route("/bulk-create", methods=["POST"])
@permission_required("manage_pages")
def bulk_create_pages_route():
    data = request.get_json(silent=True) or {}
    names = data.get("names") or []
    if not isinstance(names, list) or not names:
        return jsonify({"success": False, "error": "لم يتم إرسال أسماء للإضافة."}), 400

    result = bulk_create_pages(names)
    status = 200 if result.get("success") else 400
    return jsonify(result), status


@pages_bp.route("/update-visibility/<int:page_id>", methods=["POST"])
@permission_required("manage_pages")
def update_page_visibility(page_id):
    page = Page.query.get_or_404(page_id)
    data = request.get_json() or {}
    if "visible_to_cashier" in data:
        page.visible_to_cashier = bool(data["visible_to_cashier"])
    if "visible_to_admin" in data:
        page.visible_to_admin = bool(data["visible_to_admin"])
    db.session.commit()
    return jsonify({"success": True, "message": "تم تحديث الإعدادات بنجاح"})
