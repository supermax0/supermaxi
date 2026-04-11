from flask import Blueprint, render_template, request, jsonify, session, redirect, g
from extensions import db
from datetime import datetime

from models.customer import Customer
from models.product import Product
from models.invoice import Invoice
from models.order_item import OrderItem
from models.employee import Employee
from models.page import Page
from utils.product_schema_guard import ensure_customer_blacklist_columns, ensure_product_schema
from utils.customer_blacklist import is_phone_blacklisted_for_new_customer

pos_bp = Blueprint("pos", __name__, url_prefix="/pos")


@pos_bp.before_request
def pos_use_tenant_db():
    """كل طلبات POS تستخدم قاعدة بيانات الشركة (tenants/{slug}.db) والمخزون فيها."""
    if "user_id" not in session:
        return
    tenant_slug = session.get("tenant_slug")
    if tenant_slug:
        g.tenant = tenant_slug  # جعل الاستعلامات تستهدف قاعدة بيانات الشركة
        ensure_product_schema()
        ensure_customer_blacklist_columns()


# =================================================
# POS PAGE
# =================================================
@pos_bp.route("/")
def pos():
    # إذا لم يكن هناك مستخدم مسجل دخول → رجوع إلى صفحة تسجيل دخول الشركات الموحدة
    if "user_id" not in session:
        return redirect("/login")

    # المنتجات والزبائن من قاعدة بيانات الشركة (جدول المخزون product)
    tenant_id = session.get("tenant_id")
    if getattr(g, "tenant", None):
        # نحن على قاعدة الـ tenant (tenants/xxx.db) — جدول product = المخزون
        products = Product.query.filter(Product.active == True).order_by(Product.name).all()
        customers = Customer.query.order_by(Customer.name).all()
    elif tenant_id:
        products = Product.query.filter(
            db.or_(Product.tenant_id.is_(None), Product.tenant_id == tenant_id),
            Product.active == True,
        ).order_by(Product.name).all()
        customers = Customer.query.filter(
            db.or_(Customer.tenant_id.is_(None), Customer.tenant_id == tenant_id)
        ).all()
    else:
        products = Product.query.filter(Product.active == True).all()
        customers = Customer.query.all()

    # جلب معلومات المندوب للأرشيف
    employee = None
    pages = []
    can_edit_price = False
    if "user_id" in session:
        employee = Employee.query.get(session["user_id"])
        if employee:
            # جلب البيجات بناءً على role
            all_pages = employee.pages.all()
            if employee.role == "admin":
                # الأدمن يرى البيجات المرئية للأدمن
                pages = [p for p in all_pages if getattr(p, "visible_to_admin", True)]
            else:
                # الكاشير يرى البيجات المرئية للكاشير
                pages = [p for p in all_pages if getattr(p, "visible_to_cashier", True)]
            # فحص صلاحية تعديل السعر
            can_edit_price = employee.role == "admin" or getattr(employee, "can_edit_price", False)
    
    # جلب بيانات الطلب للتعديل إذا كان order_id موجود
    order_id = request.args.get("order_id")
    order_data = None
    if order_id:
        try:
            order_id = int(order_id)
            invoice = Invoice.query.get(order_id)
            if invoice:
                # جلب عناصر الطلب
                items = OrderItem.query.filter_by(invoice_id=invoice.id).all()
                # إنشاء list من dictionaries للعناصر
                items_list = []
                for item in items:
                    # جلب المنتج المتصل للحصول على الكمية الحالية في المخزن
                    product_stock = 0
                    if item.product:
                        # الكمية المتاحة للتعديل = الكمية في المخزن + الكمية المحجوزة في هذا الطلب
                        product_stock = (item.product.quantity or 0) + (item.quantity or 0)
                    
                    items_list.append({
                        "product_id": int(item.product_id),
                        "name": str(item.product_name),
                        "product_name": str(item.product_name),
                        "qty": int(item.quantity),
                        "price": float(item.price) if item.price else 0.0,
                        "stock": int(product_stock)
                    })
                
                # التأكد من أن جميع القيم قابلة للـ JSON serialization
                # جميع القيم يجب أن تكون: int, float, str, bool, None, list, dict فقط
                order_data = {
                    "id": int(invoice.id),
                    "customer_id": int(invoice.customer_id) if invoice.customer_id else None,
                    "customer_name": str(invoice.customer_name) if invoice.customer_name else "",
                    "items": items_list,  # list of dicts - قابل للـ JSON
                    "note": str(invoice.note) if invoice.note else "",
                    "scheduled_date": str(invoice.scheduled_date.strftime("%Y-%m-%d")) if invoice.scheduled_date else "",
                    "page_id": int(invoice.page_id) if invoice.page_id else None
                }
        except (ValueError, AttributeError) as e:
            print(f"Error loading order data: {e}")
            import traceback
            traceback.print_exc()
            order_data = None
    
    # التأكد من أن order_data هو dict قابل للـ JSON أو None
    if order_data is not None:
        # التحقق النهائي من JSON serialization
        import json
        try:
            json.dumps(order_data)
        except (TypeError, ValueError) as e:
            print(f"Warning: order_data not JSON serializable, setting to None: {e}")
            order_data = None
    
    return render_template(
        "pos.html",
        products=products,
        customers=customers,
        cashier_name=session.get("name"),
        role=session.get("role"),  # مهم
        employee=employee,  # للمندوبين
        pages=pages,  # البيجات التابعة للموظف
        can_edit_price=can_edit_price,  # صلاحية تعديل السعر
        order_data=order_data  # بيانات الطلب للتعديل (dict أو None فقط)
    )


# =================================================
# LIVE SEARCH CUSTOMER
# =================================================
@pos_bp.route("/search-customer")
def search_customer():
    q = request.args.get("q", "").strip()

    if not q:
        return jsonify([])

    ensure_customer_blacklist_columns()
    customers = Customer.query.filter(
        Customer.name.contains(q) |
        Customer.phone.contains(q) |
        Customer.phone2.contains(q)
    ).limit(15).all()

    msg = "هذا الزبون في القائمة السوداء — لا يُسمح بالتعامل معه."
    return jsonify([
        {
            "id": c.id,
            "name": c.name,
            "phone": c.phone,
            "phone2": c.phone2 or "",
            "city": c.city or "بغداد",
            "address": c.address or "",
            "blacklisted": bool(getattr(c, "is_blacklisted", False)),
            "blacklist_message": msg if getattr(c, "is_blacklisted", False) else "",
        } for c in customers
    ])



# =================================================
# ADD CUSTOMER (FROM POS)
# =================================================
@pos_bp.route("/add-customer", methods=["POST"])
def add_customer():
    try:
        ensure_customer_blacklist_columns()
        data = request.get_json() or {}

        name = data.get("name", "").strip() if data.get("name") else ""
        phone = data.get("phone", "").strip() if data.get("phone") else ""
        phone2 = data.get("phone2", "").strip() if data.get("phone2") else None
        city = data.get("city", "").strip() if data.get("city") else None
        address = data.get("address", "").strip() if data.get("address") else None

        # تحقق أساسي
        if not name:
            return jsonify({
                "status": "fail",
                "msg": "اسم الزبون مطلوب"
            }), 400
        
        if not phone:
            return jsonify({
                "status": "fail",
                "msg": "رقم الهاتف مطلوب"
            }), 400

        if is_phone_blacklisted_for_new_customer(phone, phone2):
            return jsonify({
                "status": "fail",
                "msg": "رقم الهاتف في القائمة السوداء — لا يُسمح بإضافة زبون بهذا الرقم.",
                "blacklisted": True,
            }), 400

        # منع تكرار الزبون حسب الرقم
        existing = Customer.query.filter_by(phone=phone).first()
        if existing:
            if getattr(existing, "is_blacklisted", False):
                return jsonify({
                    "status": "fail",
                    "msg": "هذا الزبون في القائمة السوداء — لا يُسمح بالتعامل معه.",
                    "blacklisted": True,
                }), 400
            return jsonify({
                "status": "success",
                "id": existing.id,
                "name": existing.name or "",
                "phone": existing.phone or ""
            })

        tenant_id = session.get("tenant_id")
        customer = Customer(
            name=name,
            phone=phone,
            phone2=phone2 if phone2 else None,
            city=city if city else None,
            address=address if address else None,
            tenant_id=tenant_id
        )

        db.session.add(customer)
        db.session.commit()

        # تعلم المحافظة والمنطقة من البيانات المدخلة
        from ai.learner import learn_city, learn_area
        import re
        
        if customer.city and customer.city.strip():
            # استخدام اسم الزبون والعنوان كنص للتعلم
            learning_text = f"{customer.name} {customer.address or ''} {customer.city}"
            learn_city(learning_text, customer.city.strip())
            # أيضاً تعلم من العنوان إذا كانت المحافظة موجودة فيه
            if customer.address and customer.city.strip() in customer.address:
                learn_city(customer.address, customer.city.strip())
        
        if customer.address and customer.address.strip():
            # محاولة استخراج المنطقة من العنوان
            area_keywords = ["حي", "منطقة", "محلة", "قرب", "شارع", "مجمع"]
            area_found = False
            
            for keyword in area_keywords:
                if keyword in customer.address:
                    parts = customer.address.split(keyword)
                    if len(parts) > 1:
                        # أخذ الكلمات بعد الكلمة المفتاحية
                        area = parts[1].strip()
                        # تنظيف المنطقة
                        area = re.sub(r'^[\d\s\-_.,:;]+', '', area).strip()
                        # أخذ أول 3-4 كلمات
                        area_words = area.split()[:4]
                        area = ' '.join(area_words).strip()
                        if area and len(area) > 2:
                            learning_text = f"{customer.name} {customer.address} {customer.city or ''}"
                            learn_area(learning_text, area)
                            # أيضاً تعلم من العنوان مباشرة
                            learn_area(customer.address, area)
                            area_found = True
                            break
            
            # إذا لم نجد كلمة مفتاحية، نتعلم العنوان كاملاً كمنطقة
            if not area_found and len(customer.address.strip()) > 3:
                # تنظيف العنوان من الأرقام في البداية
                cleaned_address = re.sub(r'^[\d\s\-_.,:;]+', '', customer.address.strip()).strip()
                if cleaned_address and len(cleaned_address) > 3:
                    learning_text = f"{customer.name} {customer.address} {customer.city or ''}"
                    learn_area(learning_text, cleaned_address)
                    learn_area(customer.address, cleaned_address)

        # التأكد من أن البيانات محفوظة بشكل صحيح
        return jsonify({
            "status": "success",
            "id": customer.id,
            "name": customer.name or "",
            "phone": customer.phone or ""
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "status": "fail",
            "msg": f"حدث خطأ: {str(e)}"
        }), 500



# =================================================
# LIVE SEARCH PRODUCT — من جدول المخزون (قاعدة بيانات الشركة)
# =================================================
@pos_bp.route("/search-product")
def search_product():
    q = request.args.get("q", "").strip()

    if not q:
        return jsonify([])

    # قبل الطلب: pos_use_tenant_db عيّن g.tenant = slug فالاستعلام من tenants/{slug}.db → جدول product
    # 1. مطابقة باركود ثم بحث بالاسم
    product_by_barcode = Product.query.filter(
        Product.barcode == q,
        Product.active == True
    ).first()

    if product_by_barcode:
        return jsonify([{
            "id": product_by_barcode.id,
            "name": product_by_barcode.name,
            "price": product_by_barcode.sale_price,
            "quantity": product_by_barcode.quantity or 0,
            "is_barcode": True
        }])

    # 2. بحث بالاسم — كل المنتجات النشطة التي تحتوي النص (حد 20)
    products = Product.query.filter(
        Product.active == True,
        Product.name.contains(q)
    ).limit(20).all()

    return jsonify([
        {
            "id": p.id,
            "name": p.name,
            "price": p.sale_price,
            "quantity": p.quantity,
            "is_barcode": False
        } for p in products
    ])


# =================================================
# CREATE ORDER (INVOICE + ITEMS)
# =================================================
# =================================================
# CREATE ORDER (INVOICE + ITEMS)
# =================================================
@pos_bp.route("/create-order", methods=["POST"])
def create_order():

    # ✅ تحقق الجلسة
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    ensure_customer_blacklist_columns()
    data = request.json or {}

    # ===============================
    # الزبون
    # ===============================
    customer_id = data.get("customer_id")

    if not customer_id:
        return jsonify({"error": "يجب اختيار زبون"}), 400

    customer = Customer.query.get(customer_id)
    if not customer:
        return jsonify({"error": "الزبون غير موجود"}), 400

    if getattr(customer, "is_blacklisted", False):
        return jsonify({
            "error": "هذا الزبون في القائمة السوداء — لا يُسمح بإنشاء طلب له.",
            "blacklisted": True,
        }), 400

    customer_name = customer.name

    # ===============================
    # المنتجات
    # ===============================
    items = data.get("items", [])
    if not items:
        return jsonify({"error": "لا توجد منتجات"}), 400

    # ===============================
    # الموظف
    # ===============================
    employee = Employee.query.get(session["user_id"])
    if not employee:
        return jsonify({"error": "موظف غير صالح"}), 403

    # ===============================
    # ملاحظة البيع
    # ===============================
    note = data.get("note", "").strip() if data.get("note") else None
    
    # ===============================
    # تاريخ التأجيل
    # ===============================
    scheduled_date = None
    if data.get("scheduled_date"):
        try:
            scheduled_date = datetime.strptime(data.get("scheduled_date"), "%Y-%m-%d")
        except:
            scheduled_date = None
    
    # ===============================
    # البيج
    # ===============================
    page_id = data.get("page_id")
    page_name = None
    if page_id:
        page = Page.query.get(page_id)
        if page:
            page_name = page.name
            # التحقق من أن البيج تابع للموظف
            if page not in employee.pages.all():
                page_id = None
                page_name = None

    # ===============================
    # إنشاء الفاتورة
    # ===============================
    invoice = Invoice(
        customer_id=customer_id,
        customer_name=customer_name,
        employee_id=employee.id,
        employee_name=employee.name,
        total=0,
        status="تم الطلب",
        payment_status="غير مسدد",
        note=note,
        scheduled_date=scheduled_date,
        page_id=page_id,
        page_name=page_name,
        created_at=datetime.utcnow()
    )

    db.session.add(invoice)
    db.session.flush()  # للحصول على invoice.id

    # ===============================
    # عناصر الفاتورة
    # ===============================
    total = 0

    for i in items:
        product = Product.query.get(i.get("product_id"))

        if not product:
            db.session.rollback()
            return jsonify({"error": "منتج غير موجود"}), 400

        qty = i.get("qty", 0)
        
        # ===============================
        # التحقق من توفر الكمية (Validation)
        # ===============================
        # السبب المحاسبي: منع بيع كمية أكبر من المتوفر
        # هذا يضمن دقة المخزون ومنع الكميات السالبة
        from utils.inventory_movements import validate_sale_quantity
        
        validation = validate_sale_quantity(product.id, qty)
        if not validation["valid"]:
            db.session.rollback()
            return jsonify({
                "error": validation["message"],
                "available": validation["available"]
            }), 400
        
        if product.quantity < qty:
            db.session.rollback()
            return jsonify({
                "error": f"الكمية المتوفرة ({product.quantity}) أقل من المطلوب ({qty}) - المنتج: {product.name}"
            }), 400

        # استخدام السعر المعدل من الواجهة إذا كان موجوداً، وإلا استخدم السعر الافتراضي
        custom_price = i.get("price")
        if custom_price and custom_price > 0:
            item_price = float(custom_price)
        else:
            item_price = product.sale_price

        item_total = item_price * qty

        order_item = OrderItem(
            invoice_id=invoice.id,
            product_id=product.id,
            product_name=product.name,
            quantity=qty,
            price=item_price,  # استخدام السعر المعدل
            cost=product.buy_price,
            total=item_total
        )

        product.quantity -= qty
        total += item_total

        db.session.add(order_item)

    # ===============================
    # تحديث الإجمالي
    # ===============================
    invoice.total = total

    try:
        db.session.commit()
        return jsonify({
            "success": True,
            "invoice_id": invoice.id,
            "total": total
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500



# =================================================
# GET LAST ORDERS (OPTIONAL – DASHBOARD)
# =================================================
@pos_bp.route("/last-orders")
def last_orders():
    orders = Invoice.query.order_by(
        Invoice.created_at.desc()
    ).limit(5).all()

    return jsonify([
        {
            "id": o.id,
            "customer": o.customer_name,
            "total": o.total,
            "status": o.status,
            "date": o.created_at.strftime("%Y-%m-%d %H:%M")
        } for o in orders
    ])

@pos_bp.route("/login", methods=["POST"])
def pos_login():
    data = request.get_json()

    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"status": "fail", "msg": "missing data"})

    emp = Employee.query.filter_by(
        username=username,
        password=password
    ).first()

    if not emp:
        return jsonify({"status": "fail", "msg": "invalid credentials"})

    # ===============================
    # هنا كان النقص 🔴
    # ===============================
    session.permanent = True
    session["user_id"] = emp.id
    session["name"] = emp.name
    session["role"] = emp.role
    # ربط الجلسة بالـ tenant (الشركة)
    if getattr(emp, "tenant_id", None):
        session["tenant_id"] = emp.tenant_id
        # حفظ plan_key في الجلسة لاستخدامه في التحقق من الميزات
        from models.tenant import Tenant as _Tenant
        _t = _Tenant.query.get(emp.tenant_id)
        if _t:
            session["plan_key"] = _t.plan_key

    return jsonify({
        "status": "success",
        "role": emp.role
    })


# =========================
# Logout
# =========================
@pos_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# =================================================
# GET ALL PRODUCTS — من جدول المخزون (قاعدة بيانات الشركة)
# =================================================
@pos_bp.route("/all-products")
def all_products():
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    # g.tenant معيّن من before_request → الاستعلام من tenants/{slug}.db (جدول product)
    products = Product.query.filter(Product.active == True).order_by(Product.name).all()
    
    return jsonify({
        "success": True,
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "sale_price": p.sale_price,
                "buy_price": p.buy_price,
                "quantity": p.quantity
            } for p in products
        ]
    })


# =================================================
# UPDATE PRODUCT PRICE
# =================================================
@pos_bp.route("/update-product-price", methods=["POST"])
def update_product_price():
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    # فحص صلاحية تعديل السعر
    employee = Employee.query.get(session["user_id"])
    if not employee or not employee.is_active:
        return jsonify({"error": "غير مصرح"}), 403
    
    if employee.role != "admin" and not getattr(employee, "can_edit_price", False):
        return jsonify({"error": "ليس لديك صلاحية لتعديل السعر"}), 403
    
    data = request.get_json() or {}
    product_id = data.get("product_id")
    sale_price = data.get("sale_price")
    
    if not product_id or sale_price is None:
        return jsonify({"error": "معطيات ناقصة"}), 400
    
    try:
        sale_price = float(sale_price)
        if sale_price < 0:
            return jsonify({"error": "السعر يجب أن يكون موجباً"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "سعر غير صحيح"}), 400
    
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"error": "المنتج غير موجود"}), 404
    
    old_price = product.sale_price
    product.sale_price = int(sale_price)
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "تم تحديث السعر بنجاح",
        "product": {
            "id": product.id,
            "name": product.name,
            "old_price": old_price,
            "new_price": product.sale_price
        }
    })

