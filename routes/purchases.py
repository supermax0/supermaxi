"""
صفحة المشتريات (Purchases)
إدارة عمليات الشراء والموردين
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, flash
from extensions import db
from models.product import Product
from models.supplier import Supplier
from models.purchase import Purchase
from models.account_transaction import AccountTransaction
from models.employee import Employee
from sqlalchemy.sql import func
from datetime import datetime, date

purchases_bp = Blueprint("purchases", __name__, url_prefix="/purchases")

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
# Purchases Page (Main)
# ======================================
@purchases_bp.route("/", methods=["GET", "POST"])
def purchases():
    """الصفحة الرئيسية للمشتريات مع التبويبات"""
    # فحص الصلاحية
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403

    # ==========================
    # PURCHASE (SUPPLIER + PRODUCT)
    # نفس المنطق من inventory.py لكن في صفحة منفصلة
    # ==========================
    if request.method == "POST" and request.form.get("form_type") == "purchase":
        product = Product.query.get_or_404(request.form["product_id"])
        supplier = Supplier.query.get_or_404(request.form["supplier_id"])

        quantity = int(request.form["quantity"])
        price = int(request.form["buy_price"])
        payment_method = request.form.get("payment_method", "credit")  # نقدي أو آجل
        
        # إجمالي الشراء
        purchase_total = quantity * price

        # تحويل تاريخ الشراء من string إلى date
        purchase_date_obj = datetime.strptime(
            request.form["purchase_date"], "%Y-%m-%d"
        ).date()
        
        purchase = Purchase(
            supplier_id=supplier.id,
            product_id=product.id,
            quantity=quantity,
            price=price,  # سعر الشراء للوحدة
            total=purchase_total,  # الإجمالي للمورد
            purchase_date=purchase_date_obj
        )

        # تحديث المخزون
        product.quantity += quantity
        product.buy_price = price  # حفظ سعر الشراء الأساسي

        # تحديث دين المورد (فقط إذا كان الدفع آجل)
        if payment_method == "credit":
            # الدفع آجل - إضافة الدين
            supplier.total_debt += purchase_total
        # إذا كان نقدي، لا نضيف دين (تم الدفع فوراً)
        
        # ==========================
        # تصحيح محاسبي: الشراء النقدي ينقص الكاش # CRUCIAL ACCOUNTING FIX
        # السبب المحاسبي:
        # - الشراء النقدي يُعتبر حركة نقدية (صرف من الصندوق)
        # - يجب تسجيله تلقائياً في AccountTransaction
        # - هذا يضمن دقة الرصيد النقدي في صفحة الصندوق
        # - الشراء الآجل لا يؤثر على الكاش (يُسجل دين فقط)
        # ==========================
        if payment_method == "cash":
            # الشراء النقدي - إنشاء حركة صرف تلقائياً
            cash_transaction = AccountTransaction(
                type="withdraw",
                amount=purchase_total,
                note=f"صندوق - شراء نقدي - {product.name} ({quantity} قطعة) من {supplier.name} - إجمالي: {purchase_total:,} د.ع"
            )
            db.session.add(cash_transaction)

        db.session.add(purchase)
        db.session.commit()
        
        # إرجاع JSON للاستجابة AJAX (اختياري) أو redirect
        if request.headers.get('Content-Type') == 'application/json':
            return jsonify({
                "success": True,
                "message": f"تم تنفيذ الشراء بنجاح ({'نقدي' if payment_method == 'cash' else 'آجل'})"
            })
        
        # Flash message للنجاح
        flash(f"✅ تم تنفيذ الشراء بنجاح - الطريقة: {'نقدي' if payment_method == 'cash' else 'آجل'}", "success")
        return redirect(url_for("purchases.purchases"))

    # ==============================
    # DISPLAY DATA
    # ==============================
    products = Product.query.filter_by(active=True).all()
    suppliers = Supplier.query.all()
    purchases_list = Purchase.query.order_by(Purchase.created_at.desc()).all()

    # إحصائيات المشتريات
    total_purchases = sum(p.total for p in purchases_list)
    purchases_count = len(purchases_list)
    
    # المشتريات لهذا الشهر
    today = date.today()
    current_month_start = today.replace(day=1)
    monthly_purchases = Purchase.query.filter(
        Purchase.purchase_date >= current_month_start
    ).all()
    monthly_total = sum(p.total for p in monthly_purchases)

    # الموردون الأكثر شراءً
    supplier_stats = db.session.query(
        Supplier.name,
        func.sum(Purchase.total).label('total_purchases'),
        func.count(Purchase.id).label('purchases_count')
    ).join(
        Purchase, Purchase.supplier_id == Supplier.id
    ).group_by(
        Supplier.id, Supplier.name
    ).order_by(
        func.sum(Purchase.total).desc()
    ).limit(5).all()
    
    # المنتجات الأكثر شراءً
    product_stats = db.session.query(
        Product.name,
        func.sum(Purchase.quantity).label('total_quantity'),
        func.sum(Purchase.total).label('total_value'),
        func.count(Purchase.id).label('purchases_count')
    ).join(
        Purchase, Purchase.product_id == Product.id
    ).group_by(
        Product.id, Product.name
    ).order_by(
        func.sum(Purchase.quantity).desc()
    ).limit(5).all()
    
    # إجمالي ديون الموردين
    total_supplier_debts = sum(s.total_debt for s in suppliers)
    
    # عدد الموردين الذين لديهم ديون
    suppliers_with_debt = len([s for s in suppliers if s.total_debt > 0])

    return render_template(
        "purchases.html",
        products=products,
        suppliers=suppliers,
        purchases=purchases_list,
        total_purchases=total_purchases,
        purchases_count=purchases_count,
        monthly_total=monthly_total,
        supplier_stats=supplier_stats,
        product_stats=product_stats,
        total_supplier_debts=total_supplier_debts,
        suppliers_with_debt=suppliers_with_debt
    )


# ======================================
# Get Purchases (API - للبحث والتصفية)
# ======================================
@purchases_bp.route("/api/list")
def get_purchases():
    """API للحصول على المشتريات مع البحث والتصفية"""
    if not check_permission("can_manage_inventory"):
        return jsonify({"error": "Unauthorized"}), 403

    # معاملات البحث والتصفية
    supplier_id = request.args.get("supplier_id", type=int)
    product_id = request.args.get("product_id", type=int)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    search = request.args.get("search", "").strip()

    # بناء الاستعلام
    query = Purchase.query

    if supplier_id:
        query = query.filter(Purchase.supplier_id == supplier_id)
    
    if product_id:
        query = query.filter(Purchase.product_id == product_id)
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
            query = query.filter(Purchase.purchase_date >= date_from_obj)
        except:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
            query = query.filter(Purchase.purchase_date <= date_to_obj)
        except:
            pass

    purchases_list = query.order_by(Purchase.created_at.desc()).all()

    # فلترة بالبحث (اسم المورد أو المنتج)
    if search:
        search_lower = search.lower()
        purchases_list = [
            p for p in purchases_list
            if search_lower in p.supplier.name.lower() or
               search_lower in p.product.name.lower()
        ]

    return jsonify([
        {
            "id": p.id,
            "date": p.purchase_date.strftime("%Y-%m-%d") if p.purchase_date else "",
            "supplier": p.supplier.name if p.supplier else "",
            "product": p.product.name if p.product else "",
            "quantity": p.quantity,
            "price": p.price,
            "total": p.total
        }
        for p in purchases_list
    ])


# ======================================
# Export Purchases (CSV)
# ======================================
@purchases_bp.route("/export")
def export_purchases():
    """تصدير المشتريات إلى CSV"""
    if not check_permission("can_manage_inventory"):
        return jsonify({"error": "Unauthorized"}), 403
    
    from flask import make_response
    
    # جلب جميع المشتريات
    purchases_list = Purchase.query.order_by(Purchase.created_at.desc()).all()
    
    # إنشاء CSV
    csv_lines = ['التاريخ,المورد,المنتج,الكمية,السعر,الإجمالي\n']
    
    for p in purchases_list:
        date_str = p.purchase_date.strftime("%Y-%m-%d") if p.purchase_date else ""
        supplier_name = p.supplier.name if p.supplier else ""
        product_name = p.product.name if p.product else ""
        csv_lines.append(f"{date_str},{supplier_name},{product_name},{p.quantity},{p.price},{p.total}\n")
    
    csv_content = '\ufeff' + ''.join(csv_lines)  # BOM for Excel
    
    response = make_response(csv_content)
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=purchases_{date.today().strftime("%Y%m%d")}.csv'
    
    return response
