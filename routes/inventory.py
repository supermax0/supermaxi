import json
import os

from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, current_app
from werkzeug.utils import secure_filename
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

from utils.product_schema_guard import ensure_product_schema

inventory_bp = Blueprint("inventory", __name__)


def _load_product_meta(product) -> dict:
    raw = ((product.meta_json if product else None) or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _split_multiline_values(raw) -> list[str]:
    items: list[str] = []
    for line in str(raw or "").splitlines():
        value = line.strip()
        if value:
            items.append(value)
    return items


def _parse_specs_text(raw) -> list[dict]:
    items: list[dict] = []
    for line in str(raw or "").splitlines():
        row = line.strip(" -\t\r\n")
        if not row:
            continue
        if ":" in row:
            label, value = row.split(":", 1)
        elif " - " in row:
            label, value = row.split(" - ", 1)
        else:
            label, value = "تفصيل", row
        value = value.strip()
        label = label.strip() or "تفصيل"
        if value:
            items.append({"label": label, "value": value})
    return items


def _parse_optional_date(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _extract_specs_items(meta: dict | None) -> list[dict]:
    meta = meta or {}
    raw_items = meta.get("specs_items")
    items: list[dict] = []
    if isinstance(raw_items, list):
        for row in raw_items:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "").strip() or "تفصيل"
            value = str(row.get("value") or "").strip()
            if value:
                items.append({"label": label, "value": value})
    if items:
        return items
    return _parse_specs_text(meta.get("specs_text"))


def _specs_items_from_form(form) -> list[dict]:
    labels = form.getlist("spec_label[]")
    values = form.getlist("spec_value[]")
    items: list[dict] = []
    count = max(len(labels), len(values))
    for idx in range(count):
        label = str(labels[idx] if idx < len(labels) else "").strip() or "تفصيل"
        value = str(values[idx] if idx < len(values) else "").strip()
        if value:
            items.append({"label": label, "value": value})
    if items:
        return items
    return _parse_specs_text(form.get("specs_text"))


def _meta_from_inventory_add_form(form) -> dict:
    """بناء meta_json من نموذج صفحة إضافة/تعديل المنتج."""
    meta_keys = (
        "barcode_type",
        "unit",
        "brand",
        "category",
        "subcategory",
        "branch_note",
        "warranty",
        "tax_applied",
        "sales_tax_type",
        "product_type",
        "shelf",
        "shelf_row",
        "shelf_loc",
        "weight",
        "custom_field_1",
        "custom_field_2",
        "custom_field_3",
        "custom_field_4",
        "purchase_ex_tax",
        "purchase_inc_tax",
        "sale_ex_tax",
        "sale_inc_tax",
    )
    meta: dict = {}
    for k in meta_keys:
        v = (form.get(k) or "").strip()
        if v:
            meta[k] = v
    if form.get("enable_imei"):
        meta["enable_imei"] = True
    if bool(form.get("not_for_sale")):
        meta["not_for_sale"] = True
    video_url = (form.get("video_url") or "").strip()
    if video_url:
        meta["video_url"] = video_url
    gallery_urls = _split_multiline_values(form.get("gallery_urls"))
    if gallery_urls:
        meta["gallery"] = gallery_urls
    specs_items = _specs_items_from_form(form)
    if specs_items:
        meta["specs_items"] = specs_items
    store_badge = (form.get("store_badge") or "").strip()
    if store_badge:
        meta["store_badge"] = store_badge
    return meta


def _inventory_add_summary():
    """إحصائيات مختصرة لشريط الملخص في صفحة إضافة المنتج."""
    products = Product.query.all()

    def _val(v, default=0):
        return default if v is None else v

    current_inventory_value = sum(_val(p.buy_price) * _val(p.quantity) for p in products)
    expected_profit_from_stock = sum(
        (_val(p.sale_price) - _val(p.buy_price)) * _val(p.quantity) for p in products
    )
    return {
        "products_count": len(products),
        "current_inventory_value": current_inventory_value,
        "expected_profit_from_stock": expected_profit_from_stock,
    }


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

    ensure_product_schema()

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
# Add Product — صفحة مخصصة (نموذج متقدم)
# ======================================
@inventory_bp.route("/add", methods=["GET", "POST"])
@inventory_bp.route("/add/", methods=["GET", "POST"])
def add_product_page():
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403

    ensure_product_schema()

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            ctx = _inventory_add_summary()
            ctx["error"] = "يرجى إدخال اسم المنتج."
            ctx["edit_product"] = None
            ctx["product_meta"] = {}
            ctx["product_specs_items"] = []
            eid = (request.form.get("edit_product_id") or "").strip()
            if eid.isdigit():
                ep = Product.query.get(int(eid))
                if ep:
                    ctx["edit_product"] = ep
                    ctx["product_meta"] = _load_product_meta(ep)
                    ctx["product_specs_items"] = _extract_specs_items(ctx["product_meta"])
            return render_template("inventory_add_product.html", **ctx), 400

        opening_stock = int(request.form.get("opening_stock", 0) or 0)
        buy_price = int(request.form.get("buy_price", 0) or 0)
        sale_price = int(request.form.get("sale_price", 0) or 0)
        barcode = (request.form.get("barcode") or "").strip() or None
        sku = (request.form.get("sku") or "").strip() or None
        not_for_sale_flag = bool(request.form.get("not_for_sale"))
        low_stock_threshold = int(request.form.get("low_stock_threshold", 5) or 5)
        description = (request.form.get("description") or "").strip() or None
        external_image_url = (request.form.get("external_image_url") or "").strip() or None
        skin_type = (request.form.get("skin_type") or "").strip() or None
        usage_type = (request.form.get("usage_type") or "").strip() or None
        requires_patch_test = bool(request.form.get("requires_patch_test"))
        expiry_date = _parse_optional_date(request.form.get("expiry_date"))
        opened_date = _parse_optional_date(request.form.get("opened_date"))
        batch_number = (request.form.get("batch_number") or "").strip() or None

        meta = _meta_from_inventory_add_form(request.form)

        edit_raw = (request.form.get("edit_product_id") or "").strip()
        edit_id = int(edit_raw) if edit_raw.isdigit() else None

        image_url = None
        file = request.files.get("product_image")
        if file and file.filename:
            ext = os.path.splitext(file.filename)[1].lower()
            if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                upload_folder = os.path.join(current_app.root_path, "static", "uploads", "products")
                os.makedirs(upload_folder, exist_ok=True)
                raw = secure_filename(file.filename)
                safe = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{raw}"
                path = os.path.join(upload_folder, safe)
                file.save(path)
                image_url = f"/static/uploads/products/{safe}"
        if not image_url and external_image_url:
            image_url = external_image_url

        if edit_id:
            p = Product.query.get(edit_id)
            if not p:
                ctx = _inventory_add_summary()
                ctx["error"] = "المنتج غير موجود للتعديل."
                ctx["edit_product"] = None
                ctx["product_meta"] = {}
                ctx["product_specs_items"] = []
                return render_template("inventory_add_product.html", **ctx), 404

            old_buy_price = p.buy_price
            old_opening_stock = p.opening_stock or 0

            p.name = name
            p.sku = sku
            p.barcode = barcode
            p.buy_price = buy_price
            p.sale_price = sale_price
            p.low_stock_threshold = max(0, low_stock_threshold)
            p.description = description
            p.skin_type = skin_type
            p.usage_type = usage_type
            p.requires_patch_test = requires_patch_test
            p.expiry_date = expiry_date
            p.opened_date = opened_date
            p.batch_number = batch_number
            p.shipping_cost = 0
            p.marketing_cost = 0
            p.active = not not_for_sale_flag

            if image_url:
                p.image_url = image_url
            elif external_image_url:
                p.image_url = external_image_url

            if "opening_stock" in request.form:
                new_opening_stock = int(request.form.get("opening_stock") or 0)
                old_value = old_opening_stock * old_buy_price
                new_value = new_opening_stock * p.buy_price
                difference = new_value - old_value
                p.opening_stock = new_opening_stock
                stock_difference = new_opening_stock - old_opening_stock
                p.quantity = (p.quantity or 0) + stock_difference
                if p.quantity < 0:
                    p.quantity = 0
                if difference != 0:
                    if difference > 0:
                        capital_transaction = AccountTransaction(
                            type="deposit",
                            amount=difference,
                            note=f"تحديث مخزون افتتاحي - {p.name} ({stock_difference:+d} قطعة)",
                        )
                    else:
                        capital_transaction = AccountTransaction(
                            type="withdraw",
                            amount=abs(difference),
                            note=f"تحديث مخزون افتتاحي - {p.name} ({stock_difference:+d} قطعة)",
                        )
                    db.session.add(capital_transaction)

            p.meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
            db.session.commit()

            action = (request.form.get("submit_action") or "save").strip()
            if action == "add_another":
                return redirect(url_for("inventory.add_product_page"))
            return redirect(url_for("inventory.inventory"))

        p = Product(
            name=name,
            sku=sku,
            barcode=barcode,
            buy_price=buy_price,
            sale_price=sale_price,
            shipping_cost=0,
            marketing_cost=0,
            opening_stock=opening_stock,
            quantity=opening_stock,
            active=not not_for_sale_flag,
            low_stock_threshold=max(0, low_stock_threshold),
            description=description,
            image_url=image_url,
            skin_type=skin_type,
            usage_type=usage_type,
            requires_patch_test=requires_patch_test,
            expiry_date=expiry_date,
            opened_date=opened_date,
            batch_number=batch_number,
            meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
        )
        db.session.add(p)
        db.session.commit()

        action = (request.form.get("submit_action") or "save").strip()
        if action == "add_another":
            return redirect(url_for("inventory.add_product_page"))
        # save | opening | group_prices → العودة لقائمة المخزون
        return redirect(url_for("inventory.inventory"))

    ctx = _inventory_add_summary()
    ctx["edit_product"] = None
    ctx["product_meta"] = {}
    ctx["product_specs_items"] = []
    edit_arg = request.args.get("edit", type=int)
    if edit_arg:
        ep = Product.query.get(edit_arg)
        if ep:
            ctx["edit_product"] = ep
            ctx["product_meta"] = _load_product_meta(ep)
            ctx["product_specs_items"] = _extract_specs_items(ctx["product_meta"])
        else:
            ctx["error"] = "المنتج غير موجود."
    return render_template("inventory_add_product.html", **ctx)


# ======================================
# Add Supplier
# ======================================
@inventory_bp.route("/audit", methods=["GET"])
def audit():
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403

    ensure_product_schema()
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
    meta = _load_product_meta(p)

    # حفظ القيم القديمة قبل التحديث (لحساب الفرق في رأس المال)
    old_buy_price = p.buy_price
    old_opening_stock = p.opening_stock or 0

    p.name = request.form["name"]
    p.sku = request.form.get("sku", "").strip() or None
    p.barcode = request.form.get("barcode", "").strip() or None
    p.buy_price = int(request.form["buy_price"])
    p.sale_price = int(request.form["sale_price"])
    p.low_stock_threshold = int(request.form.get("low_stock_threshold", 5) or 5)
    p.shipping_cost = 0  # إلغاء الحقل
    p.marketing_cost = 0  # إلغاء الحقل
    p.description = request.form.get("description", "").strip() or None
    p.image_url = request.form.get("image_url", "").strip() or None

    video_url = request.form.get("video_url", "").strip()
    gallery_urls = _split_multiline_values(request.form.get("gallery_urls"))
    specs_items = _specs_items_from_form(request.form)
    store_badge = request.form.get("store_badge", "").strip()

    for key, value in (
        ("video_url", video_url),
        ("store_badge", store_badge),
    ):
        if value:
            meta[key] = value
        else:
            meta.pop(key, None)
    if specs_items:
        meta["specs_items"] = specs_items
    else:
        meta.pop("specs_items", None)
        meta.pop("specs_text", None)
    if gallery_urls:
        meta["gallery"] = gallery_urls
    else:
        meta.pop("gallery", None)
    p.meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
    
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
