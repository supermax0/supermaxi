# routes/pages.py
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session
from extensions import db
from models.page import Page
from models.employee import Employee
from models.invoice import Invoice
from sqlalchemy.sql import func
from sqlalchemy import or_

pages_bp = Blueprint("pages", __name__, url_prefix="/pages")

# ===============================
# Pages Page
# ===============================
@pages_bp.route("/", methods=["GET", "POST"])
def pages():
    # إضافة بيج جديد
    if request.method == "POST":
        page = Page(
            name=request.form["name"]
        )
        db.session.add(page)
        db.session.commit()
        return redirect(url_for("pages.pages"))
    
    # جلب جميع البيجات
    pages = Page.query.all()
    
    # حساب عدد الطلبات لكل بيج (الطلبات الكلية)
    stats = (
        db.session.query(
            Invoice.page_id,
            func.count(Invoice.id).label("orders")
        )
        .filter(Invoice.page_id.isnot(None))
        .group_by(Invoice.page_id)
        .all()
    )
    
    stats_map = {
        s.page_id: s.orders
        for s in stats
    }
    
    # حساب عدد الراجع لكل بيج
    returned_stats = (
        db.session.query(
            Invoice.page_id,
            func.count(Invoice.id).label("returned")
        )
        .filter(
            Invoice.page_id.isnot(None),
            or_(
                Invoice.status == "راجع",
                Invoice.status == "ملغي",
                Invoice.payment_status == "مرتجع"
            )
        )
        .group_by(Invoice.page_id)
        .all()
    )
    
    returned_map = {
        s.page_id: s.returned
        for s in returned_stats
    }
    
    # حساب عدد الواصل لكل بيج
    delivered_stats = (
        db.session.query(
            Invoice.page_id,
            func.count(Invoice.id).label("delivered")
        )
        .filter(
            Invoice.page_id.isnot(None),
            or_(
                Invoice.status == "تم التوصيل",
                Invoice.status == "مسدد"
            )
        )
        .group_by(Invoice.page_id)
        .all()
    )
    
    delivered_map = {
        s.page_id: s.delivered
        for s in delivered_stats
    }
    
    # جلب الموظفين لكل بيج
    pages_data = []
    for page in pages:
        employees_list = page.employees.all()
        orders_count = stats_map.get(page.id, 0)
        returned_count = returned_map.get(page.id, 0)
        delivered_count = delivered_map.get(page.id, 0)
        pages_data.append({
            "page": page,
            "employees": employees_list,
            "orders_count": orders_count,
            "returned_count": returned_count,
            "delivered_count": delivered_count
        })
    
    return render_template("pages.html", pages_data=pages_data)

# ===============================
# Delete Page
# ===============================
@pages_bp.route("/delete/<int:id>")
def delete_page(id):
    page = Page.query.get_or_404(id)
    db.session.delete(page)
    db.session.commit()
    return redirect(url_for("pages.pages"))

# ===============================
# Get Pages for Employee (API)
# ===============================
@pages_bp.route("/employee/<int:employee_id>")
def get_employee_pages(employee_id):
    """جلب البيجات التابعة لموظف معين"""
    employee = Employee.query.get_or_404(employee_id)
    pages = employee.pages.all()
    return jsonify({
        "pages": [{"id": p.id, "name": p.name} for p in pages]
    })

# ===============================
# Get Employee Orders with Pages (API)
# ===============================
@pages_bp.route("/employee-orders/<int:employee_id>")
def get_employee_orders(employee_id):
    """جلب طلبات الموظف مع عدد البيجات"""
    employee = Employee.query.get_or_404(employee_id)
    
    # جلب الطلبات
    orders = Invoice.query.filter_by(employee_id=employee_id).all()
    
    # جلب البيجات
    pages = employee.pages.all()
    
    # حساب عدد الطلبات لكل بيج
    page_stats = {}
    for page in pages:
        page_orders = Invoice.query.filter_by(
            employee_id=employee_id,
            page_id=page.id
        ).all()
        page_stats[page.id] = {
            "name": page.name,
            "orders_count": len(page_orders),
            "orders": [{"id": o.id, "total": o.total} for o in page_orders]
        }
    
    return jsonify({
        "employee": {"id": employee.id, "name": employee.name},
        "pages_count": len(pages),
        "pages": [{"id": p.id, "name": p.name} for p in pages],
        "total_orders": len(orders),
        "page_stats": page_stats
    })

# ===============================
# Update Page Visibility
# ===============================
@pages_bp.route("/update-visibility/<int:page_id>", methods=["POST"])
def update_page_visibility(page_id):
    """تحديث إظهار/إخفاء البيج"""
    if "user_id" not in session:
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    
    employee = Employee.query.get(session["user_id"])
    if not employee or employee.role != "admin":
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    
    page = Page.query.get_or_404(page_id)
    data = request.get_json()
    
    if "visible_to_cashier" in data:
        page.visible_to_cashier = bool(data["visible_to_cashier"])
    if "visible_to_admin" in data:
        page.visible_to_admin = bool(data["visible_to_admin"])
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "تم تحديث الإعدادات بنجاح"
    })
