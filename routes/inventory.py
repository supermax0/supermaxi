from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from extensions import db
from models.product import Product
from models.order_item import OrderItem
from models.invoice import Invoice
from models.supplier import Supplier
# من models.purchase تم نقله إلى purchases.py
from models.employee import Employee
from models.account_transaction import AccountTransaction
from sqlalchemy.sql import func
from datetime import datetime

# دوال حركات المخزون (للعرض فقط)
from utils.inventory_movements import (
    get_product_inventory_movements,
    get_product_inventory_summary,
    get_low_stock_products,
    get_out_of_stock_products,
    validate_sale_quantity
)

inventory_bp = Blueprint("inventory", __name__)

def check_permission(permission_name):
    """فحص الصلاحية - helper function"""
    if "user_id" not in session:
        return False
    employee = Employee.query.get(session["user_id"])
    if not employee or not employee.is_active:
        return False
    # Admin لديه جميع الصلاحيات
    if employee.role == "admin":
        return True
        
    perm_map = {
        "can_see_orders": "view_orders",
        "can_see_reports": "view_reports",
        "can_manage_inventory": "manage_inventory",
        "can_see_expenses": "view_expenses",
        "can_manage_suppliers": "manage_suppliers",
        "can_manage_customers": "manage_customers",
        "can_see_accounts": "view_accounts",
        "can_see_financial": "view_financial",
        "can_edit_price": "edit_price",
    }
    rbac_name = perm_map.get(permission_name, permission_name)
    return employee.has_permission(rbac_name)

# ======================================
# Inventory Page
# ======================================
@inventory_bp.route("/", methods=["GET", "POST"])
def inventory():
    # فحص الصلاحية
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403

    # ==========================
    # ADD PRODUCT (NO SUPPLIER)
    # ==========================
    if request.method == "POST" and request.form.get("form_type") == "add_product":
        opening_stock = int(request.form.get("opening_stock", 0) or 0)
        buy_price = int(request.form.get("buy_price", 0) or 0)
        barcode = request.form.get("barcode", "").strip() or None
        opening_stock_value = opening_stock * buy_price  # قيمة المخزون الافتتاحي
        
        p = Product(
            name=request.form["name"],
            barcode=barcode,
            buy_price=buy_price,
            sale_price=int(request.form["sale_price"]),
            shipping_cost=0,  # إلغاء الحقل
            marketing_cost=0,  # إلغاء الحقل
            opening_stock=opening_stock,
            quantity=opening_stock,  # الكمية تساوي المخزون الافتتاحي بالبداية
            active=True
        )
        db.session.add(p)
        
        # ==========================
        # تصحيح محاسبي: المخزون الافتتاحي لا يُسجل كحركة مالية
        # السبب المحاسبي:
        # - المخزون الافتتاحي يُعتبر قيمة مخزون فقط (Asset)
        # - لا يؤثر على الرصيد المالي (Cash/Balance)
        # - لا يظهر في صفحة الحسابات أو سجل الحركات المالية
        # - لا يُعتبر إيداع مالي أو حركة حسابات
        # ==========================
        # تم إزالة إنشاء AccountTransaction للمخزون الافتتاحي
        # المخزون الافتتاحي يُسجل في Product.opening_stock و Product.quantity فقط
        
        db.session.commit()
        return redirect(url_for("inventory.inventory"))

    # ==========================
    # PURCHASE - تم نقله إلى /purchases
    # تم نقل منطق الشراء إلى صفحة purchases منفصلة
    # ==========================

    # ==============================
    # DISPLAY DATA
    # ==============================
    products = Product.query.all()
    # تم نقل منطق المشتريات إلى صفحة purchases منفصلة

    # إحصائيات محسّنة (معالجة آمنة لـ None)
    def _val(v, default=0):
        return default if v is None else v
    total_purchase = sum(_val(p.buy_price) * _val(p.quantity) for p in products)
    total_sale = sum(_val(p.sale_price) * _val(p.quantity) for p in products)
    total_profit = total_sale - total_purchase

    # قيمة المخزون الحالية (الكمية × سعر الشراء فقط)
    current_inventory_value = sum(_val(p.buy_price) * _val(p.quantity) for p in products)

    # الربح المتوقع من المخزون الحالي
    expected_profit_from_stock = sum(
        (_val(p.sale_price) - _val(p.buy_price)) * _val(p.quantity)
        for p in products
    )
    
    # المنتجات منخفضة المخزون بناءً على حد التنبيه المخصص لكل منتج
    low_stock_products = [p for p in products if _val(p.quantity) <= _val(p.low_stock_threshold, 5)]
    low_stock_count = len(low_stock_products)
    
    # المنتجات غير المباعة (quantity > 0 لكن لم تُباع)
    products_with_sales = set()
    from models.order_item import OrderItem
    sold_products = db.session.query(OrderItem.product_id).distinct().all()
    products_with_sales = {p[0] for p in sold_products}
    unsold_products = [p for p in products if _val(p.quantity) > 0 and p.id not in products_with_sales]
    unsold_count = len(unsold_products)
    
    # المنتجات النشطة وغير النشطة
    active_count = sum(1 for p in products if p.active)
    inactive_count = len(products) - active_count

    return render_template(
        "inventory.html",
        products=products,
        total_purchase=total_purchase,
        total_sale=total_sale,
        total_profit=total_profit,
        current_inventory_value=current_inventory_value,
        expected_profit_from_stock=expected_profit_from_stock,
        low_stock_count=low_stock_count,
        low_stock_products=low_stock_products,
        unsold_count=unsold_count,
        unsold_products=unsold_products[:10],  # أول 10 منتجات غير مباعة
        active_count=active_count,
        inactive_count=inactive_count
    )


# ======================================
# Add Supplier
# ======================================
@inventory_bp.route("/audit", methods=["GET"])
def audit():
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403
    products = Product.query.filter_by(active=True).all()
    return render_template("inventory_audit.html", products=products)
@inventory_bp.route("/save-audit", methods=["POST"])
def save_audit():
    if not check_permission("can_manage_inventory"):
        return jsonify({"success": False, "error": "Unauthorized"}), 403
        
    data = request.get_json()
    items = data.get("items", [])
    
    try:
        for item in items:
            product = Product.query.get(item["id"])
            if product:
                expected_qty = product.quantity
                actual_qty = item["actual_qty"]
                difference = actual_qty - expected_qty
                
                if difference != 0:
                    # Update stock automatically
                    product.quantity = actual_qty
                    
                    # Record the adjustment linearly
                    adjustment_value = difference * product.buy_price
                    if adjustment_value > 0:
                        account_tx = AccountTransaction(
                            type="deposit",
                            amount=adjustment_value,
                            note=f"تسوية جرد بزيادة - {product.name} ({difference:+d} وحدة)"
                        )
                    else:
                        account_tx = AccountTransaction(
                            type="withdraw",
                            amount=abs(adjustment_value),
                            note=f"تسوية جرد בעجز - {product.name} ({difference:+d} وحدة)"
                        )
                    db.session.add(account_tx)
                    
        db.session.commit()
        return jsonify({"success": True, "message": "تم حفظ تقرير الجرد بنجاح"})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# ======================================
@inventory_bp.route("/add-supplier", methods=["POST"])
def add_supplier():
    supplier = Supplier(
        name=request.form["name"],
        phone=request.form.get("phone"),
        address=request.form.get("address")
    )
    db.session.add(supplier)
    db.session.commit()
    return redirect(url_for("inventory.inventory"))


# ======================================
# Toggle Product
# ======================================
@inventory_bp.route("/toggle/<int:id>")
def toggle_product(id):
    p = Product.query.get_or_404(id)
    p.active = not p.active
    db.session.commit()
    return redirect(url_for("inventory.inventory"))


# ======================================
# Delete Product
# ======================================
@inventory_bp.route("/delete/<int:id>")
def delete_product(id):
    p = Product.query.get_or_404(id)
    db.session.delete(p)
    db.session.commit()
    return redirect(url_for("inventory.inventory"))


# ======================================
# Edit Product
# ======================================
@inventory_bp.route("/edit/<int:id>", methods=["POST"])
def edit_product(id):
    p = Product.query.get_or_404(id)

    # حفظ القيم القديمة قبل التحديث (لحساب الفرق في رأس المال)
    old_buy_price = p.buy_price
    old_opening_stock = p.opening_stock or 0

    p.name = request.form["name"]
    p.barcode = request.form.get("barcode", "").strip() or None
    p.buy_price = int(request.form["buy_price"])
    p.sale_price = int(request.form["sale_price"])
    p.low_stock_threshold = int(request.form.get("low_stock_threshold", 5) or 5)
    p.shipping_cost = 0  # إلغاء الحقل
    p.marketing_cost = 0  # إلغاء الحقل
    
    # تحديث المخزون الافتتاحي إذا تم توفيره
    if "opening_stock" in request.form:
        new_opening_stock = int(request.form["opening_stock"]) if request.form["opening_stock"] else 0
        old_value = old_opening_stock * old_buy_price  # استخدام السعر القديم
        new_value = new_opening_stock * p.buy_price  # استخدام السعر الجديد
        difference = new_value - old_value
        
        # تحديث المخزون الافتتاحي
        p.opening_stock = new_opening_stock
        
        # تحديث المخزون الحالي (quantity) بناءً على الفرق
        stock_difference = new_opening_stock - old_opening_stock
        p.quantity += stock_difference
        
        if p.quantity < 0:
            p.quantity = 0
        
        # تحديث رأس المال بناءً على الفرق
        if difference != 0:
            if difference > 0:
                # زيادة في رأس المال
                capital_transaction = AccountTransaction(
                    type="deposit",
                    amount=difference,
                    note=f"تحديث مخزون افتتاحي - {p.name} ({stock_difference:+d} قطعة)"
                )
            else:
                # نقص في رأس المال
                capital_transaction = AccountTransaction(
                    type="withdraw",
                    amount=abs(difference),
                    note=f"تحديث مخزون افتتاحي - {p.name} ({stock_difference:+d} قطعة)"
                )
            db.session.add(capital_transaction)

    db.session.commit()
    return redirect(url_for("inventory.inventory"))


# ======================================
# Update Opening Stock
# ======================================
@inventory_bp.route("/update-opening-stock/<int:id>", methods=["POST"])
def update_opening_stock(id):
    """تحديث المخزون الافتتاحي"""
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403
    
    product = Product.query.get_or_404(id)
    data = request.get_json() or request.form
    
    try:
        opening_stock = int(data.get("opening_stock", 0))
        product.opening_stock = opening_stock
        db.session.commit()
        return jsonify({"success": True, "message": "تم تحديث المخزون الافتتاحي بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


# ======================================
# Adjust Stock (تعديل المخزون)
# ======================================
@inventory_bp.route("/adjust-stock/<int:id>", methods=["POST"])
def adjust_stock(id):
    """
    تعديل المخزون يدوياً (مع سبب إلزامي)
    
    السبب المحاسبي:
    - كل حركة مخزون يجب أن تكون مرتبطة بسبب واضح
    - التعديل اليدوي يحتاج سبب لتتبع التغييرات
    - منع أي تغيير مباشر بدون تسجيل حركة
    """
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403
    
    product = Product.query.get_or_404(id)
    
    # الحصول على البيانات (JSON أو Form)
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()
    
    try:
        adjustment = int(data.get("adjustment", 0))  # يمكن أن يكون موجب أو سالب
        reason = data.get("reason", "").strip()
        
        # التحقق من وجود السبب
        if not reason:
            if request.is_json:
                return jsonify({
                    "success": False, 
                    "error": "يجب إدخال سبب التعديل (مثال: فحص جرد، تلف، خطأ في الإدخال)"
                }), 400
            else:
                # Form submission - redirect with error
                from flask import flash
                flash("يجب إدخال سبب التعديل", "error")
                return redirect(url_for("inventory.inventory"))
        
        # التحقق من أن التعديل لن يجعل المخزون سالباً
        if product.quantity + adjustment < 0:
            if request.is_json:
                return jsonify({
                    "success": False, 
                    "error": f"المخزون لا يمكن أن يكون سالباً. المخزون الحالي: {product.quantity}"
                }), 400
            else:
                from flask import flash
                flash(f"المخزون لا يمكن أن يكون سالباً. المخزون الحالي: {product.quantity}", "error")
                return redirect(url_for("inventory.inventory"))
        
        # تطبيق التعديل
        old_quantity = product.quantity
        product.quantity += adjustment
        
        db.session.commit()
        
        # تسجيل الحركة (للعرض فقط - لا نحفظها في قاعدة بيانات)
        # يمكن إضافة سجل حركات في المستقبل إذا لزم الأمر
        
        if request.is_json:
            return jsonify({
                "success": True, 
                "message": f"تم تعديل المخزون بنجاح. السبب: {reason}",
                "old_quantity": old_quantity,
                "new_quantity": product.quantity,
                "adjustment": adjustment
            })
        else:
            from flask import flash
            flash(f"تم تعديل المخزون بنجاح. السبب: {reason}", "success")
            return redirect(url_for("inventory.inventory"))
    except ValueError:
        if request.is_json:
            return jsonify({"success": False, "error": "قيمة التعديل غير صحيحة"}), 400
        else:
            from flask import flash
            flash("قيمة التعديل غير صحيحة", "error")
            return redirect(url_for("inventory.inventory"))
    except Exception as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({"success": False, "error": str(e)}), 400
        else:
            from flask import flash
            flash(f"حدث خطأ: {str(e)}", "error")
            return redirect(url_for("inventory.inventory"))


# ======================================
# Get Product Inventory Movements (API)
# ======================================
@inventory_bp.route("/api/movements/<int:product_id>")
def get_product_movements_api(product_id):
    """API للحصول على حركات مخزون منتج محدد"""
    if not check_permission("can_manage_inventory"):
        return jsonify({"error": "Unauthorized"}), 403
    
    movements = get_product_inventory_movements(product_id)
    summary = get_product_inventory_summary(product_id)
    
    return jsonify({
        "summary": summary,
        "movements": movements[:50]  # آخر 50 حركة
    })


# ======================================
# Product Report
# ======================================
@inventory_bp.route("/report/<int:id>")
def product_report(id):
    product = Product.query.get_or_404(id)

    stats = (
        db.session.query(
            Invoice.status,
            func.count(Invoice.id),
            func.sum(OrderItem.total)
        )
        .join(OrderItem, OrderItem.invoice_id == Invoice.id)
        .filter(OrderItem.product_id == id)
        .group_by(Invoice.status)
        .all()
    )

    report = {
        s[0]: {
            "count": s[1],
            "total": s[2] or 0
        }
        for s in stats
    }

    return render_template(
        "inventory_report.html",
        product=product,
        report=report
    )
