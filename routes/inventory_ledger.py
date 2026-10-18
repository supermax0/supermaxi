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
from utils.permission_checks import check_permission
from utils.branch_mode import independent_branches_enabled

inventory_ledger_bp = Blueprint("inventory_ledger", __name__, url_prefix="/inventory/ledger")


# ======================================
# Inventory Ledger Page (Main)
# ======================================
@inventory_ledger_bp.route("/")
def inventory_ledger():
    """الصفحة الرئيسية لسجل حركات المخزون"""
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403
    
    # جلب جميع المنتجات
    products = Product.query.filter_by(active=True).order_by(Product.name, Product.id).all()
    if not independent_branches_enabled():
        grouped_products = {}
        for product in products:
            group_key = str(product.catalog_group_id or "").strip() or f"product:{product.id}"
            grouped_products.setdefault(group_key, product)
        products = list(grouped_products.values())
    
    # ملخصات الحركات لجميع المنتجات
    summaries = [get_product_inventory_summary(product.id) for product in products]
    inventory_quantities = {
        summary["product_id"]: summary["actual_quantity"] for summary in summaries
    }
    
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

    # الفروع النشطة (لتصفية الحركات حسب الفرع)
    branches = []
    try:
        from models.branch import Branch

        branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    except Exception:
        db.session.rollback()
        branches = []
    
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
        selected_summary=selected_summary,
        branches=branches,
        inventory_quantities=inventory_quantities,
    )


# ======================================
# Get Product Movements (API)
# ======================================
@inventory_ledger_bp.route("/api/product/<int:product_id>")
def get_product_movements(product_id):
    """API للحصول على حركات مخزون منتج محدد"""
    if not check_permission("can_manage_inventory"):
        return jsonify({"error": "Unauthorized"}), 403
    
    branch_id = request.args.get("branch_id", type=int)
    if branch_id:
        # حركات فرع محدد: الملخص يُحسب من حركات هذا الفرع فقط
        movements = get_product_inventory_movements(product_id, branch_id=branch_id)
        product = Product.query.get(product_id)
        total_in = sum(int(m.get("quantity_in") or 0) for m in movements)
        total_out = sum(int(m.get("quantity_out") or 0) for m in movements)
        balance = movements[-1]["balance_after"] if movements else 0
        actual = balance
        try:
            from models.branch import BranchStock

            row = BranchStock.query.filter_by(product_id=product_id, branch_id=branch_id).first()
            actual = int(row.quantity or 0) if row else 0
        except Exception:
            db.session.rollback()
        summary = {
            "product_id": product_id,
            "product_name": product.name if product else "",
            "total_in": total_in,
            "total_out": total_out,
            "calculated_balance": balance,
            "actual_quantity": actual,
            "movements_count": len(movements),
            "is_balanced": balance == actual,
            "difference": actual - balance,
            "branch_id": branch_id,
        }
    else:
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
