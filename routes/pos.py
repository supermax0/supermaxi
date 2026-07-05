import json
from urllib.parse import parse_qs, urlparse

from flask import Blueprint, render_template, request, jsonify, session, redirect, g
from jinja2 import TemplateNotFound
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
from utils.permission_checks import guard_permission
from utils.activity_logger import INVOICE_SNAPSHOT_FIELDS, log_activity, snapshot_attrs
from utils.branch_migration import ensure_branch_schema, get_default_branch
from utils.branch_context import current_branch_id, init_branch_context
from utils.branch_stock_service import deduct_stock, get_branch_stock, receive_stock, BranchStockError
from utils.order_shipping import add_shipping_line_item, is_shipping_item
from utils.product_delivery_fees import fee_for_cart_items

pos_bp = Blueprint("pos", __name__, url_prefix="/pos")


def _should_use_legacy_ui():
    """Legacy POS UI via ?legacy=1; White Pro is the default."""
    return request.args.get("legacy") == "1"


def _parse_product_meta(product):
    raw = getattr(product, "meta_json", None)
    if not raw:
        return {}
    try:
        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _editing_order_id_from_request(data: dict) -> int | None:
    raw = data.get("order_id")
    if raw in (None, "", 0, "0"):
        try:
            ref = request.referrer or ""
            raw = (parse_qs(urlparse(ref).query).get("order_id") or [None])[0]
        except Exception:
            raw = None
    try:
        return int(raw) if raw not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        return None


def _product_bootstrap_dict(product):
    from utils.branch_sales import is_sell_from_all_branches_enabled

    meta = _parse_product_meta(product)
    if is_sell_from_all_branches_enabled():
        display_qty = product.quantity or 0
    else:
        branch_id = current_branch_id()
        display_qty = get_branch_stock(branch_id, product.id) if branch_id else (product.quantity or 0)
    return {
        "id": product.id,
        "name": product.name,
        "sku": product.sku or "",
        "barcode": product.barcode or "",
        "sale_price": product.sale_price or 0,
        "quantity": display_qty,
        "total_quantity": product.quantity or 0,
        "image_url": product.image_url or "",
        "low_stock_threshold": product.low_stock_threshold or 5,
        "category": (meta.get("category") or "").strip(),
        "store_badge": (meta.get("store_badge") or "").strip(),
        "sell_from_all_branches": is_sell_from_all_branches_enabled(),
    }


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
        ensure_branch_schema()
        init_branch_context()


@pos_bp.before_request
def pos_permission_guard():
    if request.endpoint in ("pos.pos_login", "pos.logout"):
        return None
    if "user_id" not in session:
        return None
    if request.endpoint == "pos.update_product_price":
        return guard_permission("edit_price", json=True)
    return guard_permission("view_pos")


# =================================================
# POS PAGE
# =================================================
@pos_bp.route("/", strict_slashes=False)
def pos():
    # إذا لم يكن هناك مستخدم مسجل دخول → رجوع إلى صفحة تسجيل دخول الشركات الموحدة
    if "user_id" not in session:
        return redirect("/pos/login")

    ensure_product_schema()
    ensure_customer_blacklist_columns()

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
            can_edit_price = employee.role == "admin" or employee.has_permission("edit_price")
    
    # جلب بيانات الطلب للتعديل إذا كان order_id موجود
    order_id = request.args.get("order_id")
    order_data = None
    if order_id:
        try:
            order_id = int(order_id)
            invoice = Invoice.query.get(order_id)
            if invoice:
                # جلب عناصر الطلب
                items = [item for item in OrderItem.query.filter_by(invoice_id=invoice.id).all() if not is_shipping_item(item)]
                # إنشاء list من dictionaries للعناصر
                items_list = []
                for item in items:
                    # جلب المنتج المتصل للحصول على الكمية الحالية في المخزن
                    product_stock = 0
                    if item.product:
                        # الكمية المتاحة للتعديل = الكمية في المخزن + الكمية المحجوزة في هذا الطلب
                        if item.fulfillment_branch_id:
                            product_stock = get_branch_stock(item.fulfillment_branch_id, item.product.id) + (item.quantity or 0)
                        else:
                            product_stock = (item.product.quantity or 0) + (item.quantity or 0)
                    
                    items_list.append({
                        "product_id": int(item.product_id),
                        "name": str(item.product_name),
                        "product_name": str(item.product_name),
                        "qty": int(item.quantity),
                        "price": float(item.price) if item.price else 0.0,
                        "stock": int(product_stock),
                        "fulfillment_branch_id": int(item.fulfillment_branch_id) if item.fulfillment_branch_id else None,
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
    
    cash_balance = 0
    try:
        from utils.cash_calculations import calculate_cash_balance
        cash_balance = calculate_cash_balance()
    except Exception:
        pass

    bootstrap_products = [_product_bootstrap_dict(p) for p in products]
    from models.branch import Branch

    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    default_branch_id = current_branch_id() or (get_default_branch().id if get_default_branch() else None)

    ctx = dict(
        products=products,
        bootstrap_products=bootstrap_products,
        customers=customers,
        branches=branches,
        default_branch_id=default_branch_id,
        cashier_name=session.get("name"),
        role=session.get("role"),
        employee=employee,
        pages=pages,
        can_edit_price=can_edit_price,
        order_data=order_data,
        cash_balance=cash_balance,
        company_name=session.get("tenant_slug") or session.get("name") or "Finora",
    )

    if not _should_use_legacy_ui():
        try:
            return render_template("pos_dev/pos.html", **ctx)
        except TemplateNotFound:
            pass

    return render_template("pos.html", **ctx)


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

        from utils.digits import digits_only

        name = data.get("name", "").strip() if data.get("name") else ""
        phone = digits_only(data.get("phone", "").strip() if data.get("phone") else "")
        phone2_raw = data.get("phone2", "").strip() if data.get("phone2") else None
        phone2 = digits_only(phone2_raw) if phone2_raw else None
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

        if len(phone) != 11:
            return jsonify({
                "status": "fail",
                "msg": "رقم الهاتف يجب أن يكون 11 رقم"
            }), 400

        if phone2 and len(phone2) != 11:
            return jsonify({
                "status": "fail",
                "msg": "رقم الهاتف الثاني يجب أن يكون 11 رقم"
            }), 400

        if not address:
            return jsonify({
                "status": "fail",
                "msg": "العنوان مطلوب"
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

        # التعلم اختياري — لا يفشل حفظ الزبون إذا تعذّر الكتابة على ملفات التعلم
        try:
            from ai.learner import learn_city, learn_area
            import re

            if customer.city and customer.city.strip():
                learning_text = f"{customer.name} {customer.address or ''} {customer.city}"
                learn_city(learning_text, customer.city.strip())
                if customer.address and customer.city.strip() in customer.address:
                    learn_city(customer.address, customer.city.strip())

            if customer.address and customer.address.strip():
                area_keywords = ["حي", "منطقة", "محلة", "قرب", "شارع", "مجمع"]
                area_found = False

                for keyword in area_keywords:
                    if keyword in customer.address:
                        parts = customer.address.split(keyword)
                        if len(parts) > 1:
                            area = parts[1].strip()
                            area = re.sub(r'^[\d\s\-_.,:;]+', '', area).strip()
                            area_words = area.split()[:4]
                            area = ' '.join(area_words).strip()
                            if area and len(area) > 2:
                                learning_text = f"{customer.name} {customer.address} {customer.city or ''}"
                                learn_area(learning_text, area)
                                learn_area(customer.address, area)
                                area_found = True
                                break

                if not area_found and len(customer.address.strip()) > 3:
                    cleaned_address = re.sub(r'^[\d\s\-_.,:;]+', '', customer.address.strip()).strip()
                    if cleaned_address and len(cleaned_address) > 3:
                        learning_text = f"{customer.name} {customer.address} {customer.city or ''}"
                        learn_area(learning_text, cleaned_address)
                        learn_area(customer.address, cleaned_address)
        except Exception:
            pass

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
            "image_url": product_by_barcode.image_url or "",
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
            "image_url": p.image_url or "",
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
    # إنشاء / تعديل الفاتورة
    # ===============================
    editing_order_id = _editing_order_id_from_request(data)
    invoice = None
    if editing_order_id:
        try:
            invoice = Invoice.query.get(int(editing_order_id))
        except (TypeError, ValueError):
            invoice = None
        if not invoice:
            return jsonify({"error": "الطلب المراد تعديله غير موجود"}), 404
        if (invoice.status or "") in ("تم التوصيل", "مسدد", "ملغي", "راجع", "مرتجع", "راجعة"):
            return jsonify({"error": "لا يمكن تعديل طلب مكتمل أو ملغي أو راجع"}), 400

        # إرجاع مخزون عناصر الطلب القديمة داخل نفس المعاملة قبل فحص الكميات الجديدة.
        old_items = OrderItem.query.filter_by(invoice_id=invoice.id).all()
        for old_item in old_items:
            if is_shipping_item(old_item):
                db.session.delete(old_item)
                continue
            if old_item.product:
                old_qty = int(old_item.quantity or 0)
                if old_item.fulfillment_branch_id:
                    receive_stock(old_item.fulfillment_branch_id, old_item.product.id, old_qty)
                else:
                    old_item.product.quantity = int(old_item.product.quantity or 0) + old_qty
            db.session.delete(old_item)
        db.session.flush()

        invoice.customer_id = customer_id
        invoice.customer_name = customer_name
        invoice.employee_id = employee.id
        invoice.employee_name = employee.name
        invoice.branch_id = current_branch_id() or invoice.branch_id or (get_default_branch().id if get_default_branch() else None)
        invoice.total = 0
        invoice.note = note
        invoice.scheduled_date = scheduled_date
        invoice.page_id = page_id
        invoice.page_name = page_name
    else:
        invoice = Invoice(
            customer_id=customer_id,
            customer_name=customer_name,
            employee_id=employee.id,
            employee_name=employee.name,
            branch_id=current_branch_id() or (get_default_branch().id if get_default_branch() else None),
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
        from utils.branch_sales import resolve_sale_fulfillment

        explicit_branch = i.get("fulfillment_branch_id")
        try:
            explicit_branch = int(explicit_branch) if explicit_branch not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            explicit_branch = None

        fulfillment_branch_id, validation = resolve_sale_fulfillment(
            product.id,
            qty,
            preferred_branch_id=current_branch_id() or (
                get_default_branch().id if get_default_branch() else None
            ),
            explicit_branch_id=explicit_branch,
        )
        if not validation.get("valid") or not fulfillment_branch_id:
            db.session.rollback()
            return jsonify({
                "error": validation.get("message") or f"الكمية غير متوفرة - المنتج: {product.name}",
                "available": validation.get("available", 0),
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
            total=item_total,
            fulfillment_branch_id=fulfillment_branch_id,
        )

        try:
            deduct_stock(fulfillment_branch_id, product.id, qty)
        except BranchStockError as exc:
            db.session.rollback()
            return jsonify({"error": str(exc)}), 400
        total += item_total

        db.session.add(order_item)

    # ===============================
    # تحديث الإجمالي + رسوم التوصيل
    # ===============================
    province = (getattr(customer, "city", None) or "").strip()
    shipping_fee = data.get("shipping_fee")
    if shipping_fee is None:
        shipping_fee, _ = fee_for_cart_items(
            [{"product_id": i.get("product_id"), "qty": i.get("qty", 0)} for i in items],
            province,
        )
    else:
        try:
            shipping_fee = max(0, int(shipping_fee))
        except (TypeError, ValueError):
            shipping_fee = 0

    tenant_id = getattr(customer, "tenant_id", None)
    if shipping_fee > 0:
        # تُحفظ داخلياً كمصروف توصيل عند التسديد ولا تؤثر على إجمالي الفاتورة
        add_shipping_line_item(invoice, shipping_fee, tenant_id)

    invoice.total = total

    try:
        db.session.commit()
        try:
            log_activity(
                "update" if editing_order_id else "create",
                "pos",
                f"{'تعديل طلب' if editing_order_id else 'بيع جديد'} — فاتورة #{invoice.id} بمبلغ {total}",
                entity_type="invoice",
                entity_id=invoice.id,
                payload={"invoice": snapshot_attrs(invoice, *INVOICE_SNAPSHOT_FIELDS), "items_count": len(items)},
            )
        except Exception:
            pass
        return jsonify({
            "success": True,
            "invoice_id": invoice.id,
            "total": total,
            "updated": bool(editing_order_id),
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

@pos_bp.route("/login", methods=["GET", "POST"])
def pos_login():
    if request.method == "GET":
        return render_template("pos_login.html")

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
                "quantity": p.quantity,
                "image_url": p.image_url or ""
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
    
    if employee.role != "admin" and not employee.has_permission("edit_price"):
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

