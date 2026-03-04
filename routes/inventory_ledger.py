"""
صفحة سجل حركات المخزون (Inventory Ledger)
عرض سجل حركات المخزون للمنتجات (للقراءة فقط)
"""

from flask import Blueprint, render_template, request, jsonify, session, redirect
from extensions import db
from models.product import Product
from models.employee import Employee
from utils.inventory_movements import (
    get_product_inventory_movements,
    get_product_inventory_summary,
    get_all_products_movements_summary
)

inventory_ledger_bp = Blueprint("inventory_ledger", __name__, url_prefix="/inventory/ledger")

def check_permission(permission_name):
    """فحص الصلاحية"""
    if "user_id" not in session:
        return False
    employee = Employee.query.get(session["user_id"])
    if not employee or not employee.is_active:
        return False
    if employee.role == "admin":
        return True
    return getattr(employee, permission_name, False)


# ======================================
# Inventory Ledger Page (Main)
# ======================================
@inventory_ledger_bp.route("/")
def inventory_ledger():
    """الصفحة الرئيسية لسجل حركات المخزون"""
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403
    
    # جلب جميع المنتجات
    products = Product.query.filter_by(active=True).order_by(Product.name).all()
    
    # ملخصات الحركات لجميع المنتجات
    summaries = get_all_products_movements_summary()
    
    # إحصائيات عامة
    total_products = len(products)
    low_stock_count = len([s for s in summaries if s["actual_quantity"] <= 5 and s["actual_quantity"] > 0])
    out_of_stock_count = len([s for s in summaries if s["actual_quantity"] == 0])
    balanced_count = len([s for s in summaries if s["is_balanced"]])
    
    # جلب حركات منتج محدد إذا تم تحديده
    selected_product_id = request.args.get("product_id", type=int)
    selected_movements = None
    selected_summary = None
    
    if selected_product_id:
        selected_movements = get_product_inventory_movements(selected_product_id)
        selected_summary = get_product_inventory_summary(selected_product_id)
    
    return render_template(
        "inventory_ledger.html",
        products=products,
        summaries=summaries,
        total_products=total_products,
        low_stock_count=low_stock_count,
        out_of_stock_count=out_of_stock_count,
        balanced_count=balanced_count,
        selected_product_id=selected_product_id,
        selected_movements=selected_movements,
        selected_summary=selected_summary
    )


# ======================================
# Get Product Movements (API)
# ======================================
@inventory_ledger_bp.route("/api/product/<int:product_id>")
def get_product_movements(product_id):
    """API للحصول على حركات مخزون منتج محدد"""
    if not check_permission("can_manage_inventory"):
        return jsonify({"error": "Unauthorized"}), 403
    
    movements = get_product_inventory_movements(product_id)
    summary = get_product_inventory_summary(product_id)
    
    return jsonify({
        "product": {
            "id": summary["product_id"],
            "name": summary["product_name"]
        },
        "summary": summary,
        "movements": movements
    })
