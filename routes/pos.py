import json
import threading
import time
from urllib.parse import parse_qs, urlparse

from flask import Blueprint, render_template, request, jsonify, session, redirect, g
from jinja2 import TemplateNotFound
from sqlalchemy.orm import selectinload
from werkzeug.exceptions import HTTPException
from extensions import db
from datetime import datetime

from models.customer import Customer
from models.product import Product
from models.invoice import Invoice
from models.order_item import OrderItem
from models.employee import Employee
from models.page import Page
from utils.product_schema_guard import ensure_customer_blacklist_columns, ensure_product_schema
from utils.order_item_schema_guard import ensure_order_item_schema
from utils.invoice_schema_guard import ensure_invoice_schema
from utils.product_color_service import (
    colors_quantity_total,
    colors_for_product_dict,
    get_color_quantity,
    product_has_colors,
    ProductColorError,
)
from utils.trade_in_service import (
    TradeInError,
    employee_can_access_replacement_product,
    product_sale_options,
    resolve_sale_selection,
    sync_trade_in_receipts,
)
from utils.customer_blacklist import is_phone_blacklisted_for_new_customer
from utils.permission_checks import employee_can, guard_permission
from utils.activity_logger import INVOICE_SNAPSHOT_FIELDS, log_activity, snapshot_attrs
from utils.branch_migration import ensure_branch_schema, get_default_branch
from utils.branch_context import current_branch_id, init_branch_context
from utils.branch_mode import independent_branches_enabled
from utils.branch_scope import resolve_write_branch_id
from utils.branch_stock_service import get_branch_stock, get_total_stock, BranchStockError
from utils.branch_product_service import product_for_branch
from utils.order_shipping import (
    apply_manual_delivery_fee_on_payment,
    get_shipping_fee_from_invoice,
    is_shipping_item,
)
from utils.order_stock_lock import (
    apply_stock_actions,
    check_stock_rows,
    clear_order_stock_lock,
    mark_order_stock_locked,
)
from utils.order_stock_policy import (
    deduct_order_stock,
    deferred_stock_enabled,
    ensure_policy_initialized,
    OrderStockError,
    order_needs_stock,
    restore_order_stock,
    stock_is_deducted,
)
from utils.cash_calculations import _effective_paid_amount
from utils.invoice_mutation_policy import (
    PAID_INVOICE_MUTATION_DISABLED_MESSAGE,
    paid_invoice_mutation_denied,
    paid_invoice_mutations_enabled,
)
from utils.payment_ledger import append_payment_ledger_delta
from utils.date_periods import get_period_dates, get_period_label
from services.pos_catalog import (
    catalog_family as _catalog_family,
    pos_catalog_products as _pos_catalog_products,
    product_bootstrap_dict as _product_bootstrap_dict,
    search_pos_customers,
    search_pos_products,
    shared_catalog_mode as _shared_catalog_mode,
)
from services.pos_checkout import (
    PosCheckoutError,
    activate_pos_request_branch as _activate_pos_request_branch,
    create_pos_order,
    fallback_fulfillment_branch_id as _fallback_fulfillment_branch_id,
)

pos_bp = Blueprint("pos", __name__, url_prefix="/pos")


def _should_use_legacy_ui():
    """Legacy POS UI via ?legacy=1; White Pro is the default."""
    return request.args.get("legacy") == "1"


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


def _branch_with_enough_stock(product_id, qty, *preferred_branch_ids):
    from models.branch import Branch

    qty = int(qty or 0)
    checked = set()
    for branch_id in preferred_branch_ids:
        if not branch_id:
            continue
        try:
            branch_id = int(branch_id)
        except (TypeError, ValueError):
            continue
        if branch_id in checked:
            continue
        checked.add(branch_id)
        branch = Branch.query.filter_by(id=branch_id, is_active=True).first()
        if branch and get_branch_stock(branch.id, product_id) >= qty:
            return branch.id

    candidates = []
    for branch in Branch.query.filter_by(is_active=True).order_by(Branch.is_default.desc(), Branch.id.asc()).all():
        if branch.id in checked:
            continue
        available = get_branch_stock(branch.id, product_id)
        if available >= qty:
            candidates.append((available, branch.id))
    if not candidates:
        return None
    candidates.sort(key=lambda row: (-row[0], row[1]))
    return candidates[0][1]


@pos_bp.before_request
def pos_use_tenant_db():
    """كل طلبات POS تستخدم قاعدة بيانات الشركة (tenants/{slug}.db) والمخزون فيها."""
    if "user_id" not in session:
        return
    tenant_slug = session.get("tenant_slug")
    if tenant_slug:
        g.tenant = tenant_slug  # جعل الاستعلامات تستهدف قاعدة بيانات الشركة
        ensure_product_schema()
        ensure_order_item_schema()
        ensure_invoice_schema()
        try:
            from modules.employee_desk.page_link import ensure_desk_link_schema
            ensure_desk_link_schema()
        except Exception:
            pass
        ensure_customer_blacklist_columns()
        ensure_branch_schema()
        init_branch_context()
        ensure_policy_initialized()


@pos_bp.before_request
def pos_permission_guard():
    if request.endpoint in ("pos.pos_login", "pos.logout"):
        return None
    if "user_id" not in session:
        if request.endpoint in ("pos.search_customer", "pos.search_product", "pos.last_orders"):
            # lookups return company data: an anonymous caller gets a 401, never an empty-looking 200
            return jsonify({"success": False, "error": "غير مسجّل الدخول"}), 401
        return None
    try:
        from utils.permission_checks import ensure_cashier_role_has_messages

        ensure_cashier_role_has_messages()
    except Exception:
        pass
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
    employee = Employee.query.get(session["user_id"])

    # الأدمن يحتاج كتالوج كل الفروع حتى يختار فرع الخصم داخل نقطة البيع.
    # الموظف يبقى على النطاق المفروض من فرعه فقط.
    tenant_id = session.get("tenant_id")
    if getattr(g, "tenant", None):
        product_query = Product.query
        customer_query = Customer.query
        if employee and employee.role == "admin":
            product_query = product_query.execution_options(skip_branch_scope=True)
            customer_query = customer_query.execution_options(skip_branch_scope=True)
        products = product_query.filter(
            Product.active == True,  # noqa: E712
            Product.pos_visible.isnot(False),
        ).order_by(Product.name).all()
        customers = customer_query.order_by(Customer.name).all()
    elif tenant_id:
        products = Product.query.filter(
            db.or_(Product.tenant_id.is_(None), Product.tenant_id == tenant_id),
            Product.active == True,  # noqa: E712
            Product.pos_visible.isnot(False),
        ).order_by(Product.name).all()
        customers = Customer.query.filter(
            db.or_(Customer.tenant_id.is_(None), Customer.tenant_id == tenant_id)
        ).all()
    else:
        products = Product.query.filter(
            Product.active == True,  # noqa: E712
            Product.pos_visible.isnot(False),
        ).all()
        customers = Customer.query.all()

    # جلب معلومات المندوب للأرشيف
    products = [
        product
        for product in products
        if employee_can_access_replacement_product(employee, product)
    ]
    pages = []
    can_edit_price = False
    can_print_invoice = False
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
        can_print_invoice = employee_can(employee, "print_pos_invoice")
    
    # جلب بيانات الطلب للتعديل إذا كان order_id موجود
    order_id = request.args.get("order_id")
    order_data = None
    if order_id:
        try:
            order_id = int(order_id)
            invoice_query = Invoice.query
            if employee and employee.role == "admin":
                invoice_query = invoice_query.execution_options(skip_branch_scope=True)
            invoice = invoice_query.filter(Invoice.id == order_id).first()
            if invoice and not paid_invoice_mutation_denied(invoice):
                # جلب عناصر الطلب
                items = [item for item in OrderItem.query.filter_by(invoice_id=invoice.id).all() if not is_shipping_item(item)]
                # إنشاء list من dictionaries للعناصر
                items_list = []
                for item in items:
                    # لا نضيف كمية الطلب إلى المتاح إلا إذا كانت مخصومة فعلاً.
                    # الطلب المؤجل لا يحجز مخزوناً، وإضافتها هنا تعرض رصيداً وهمياً.
                    product_stock = 0
                    item_branch_id = item.fulfillment_branch_id or _fallback_fulfillment_branch_id(invoice)
                    reserved_qty = int(item.quantity or 0) if stock_is_deducted(invoice) else 0
                    if item.product:
                        if item_branch_id:
                            product_stock = get_branch_stock(item_branch_id, item.product.id) + reserved_qty
                        else:
                            product_stock = int(item.product.quantity or 0) + reserved_qty
                    
                    color_name = (getattr(item, "variant_color", None) or "").strip()
                    color_stock = 0
                    if color_name and item.product:
                        color_stock = get_color_quantity(item.product.id, color_name) + reserved_qty

                    items_list.append({
                        "product_id": int(item.product_id),
                        "name": str(item.product_name),
                        "product_name": str(item.product_name),
                        "qty": int(item.quantity),
                        "price": float(item.price) if item.price else 0.0,
                        "stock": int(product_stock),
                        "color": color_name,
                        "color_stock": int(color_stock),
                        "sale_mode": getattr(item, "sale_mode", None) or "normal",
                        "trade_in_source_product_id": getattr(
                            item, "trade_in_source_product_id", None
                        ),
                        "trade_in_source_product_name": getattr(
                            item, "trade_in_source_product_name", None
                        ) or "",
                        "fulfillment_branch_id": int(item_branch_id) if item_branch_id else None,
                    })
                
                # التأكد من أن جميع القيم قابلة للـ JSON serialization
                # جميع القيم يجب أن تكون: int, float, str, bool, None, list, dict فقط
                order_data = {
                    "id": int(invoice.id),
                    "customer_id": int(invoice.customer_id) if invoice.customer_id else None,
                    "customer_name": str(invoice.customer_name) if invoice.customer_name else "",
                    "customer_city": str(invoice.customer.city) if invoice.customer and invoice.customer.city else "",
                    "employee_name": str(invoice.employee_name) if invoice.employee_name else "",
                    "items": items_list,
                    "note": str(invoice.note) if invoice.note else "",
                    "scheduled_date": str(invoice.scheduled_date.strftime("%Y-%m-%d")) if invoice.scheduled_date else "",
                    "page_id": int(invoice.page_id) if invoice.page_id else None,
                    "page_name": str(invoice.page_name) if invoice.page_name else "",
                    "discount_amount": int(getattr(invoice, "discount_amount", 0) or 0),
                    "branch_id": int(invoice.branch_id) if invoice.branch_id else None,
                    "location_url": str(invoice.location_url or ""),
                    "location_lat": invoice.location_lat,
                    "location_lng": invoice.location_lng,
                    "location_label": str(invoice.location_label or ""),
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

    # Admin POS loads local copies from every branch.  Present them as one
    # shared catalogue so a single toaster/TV never appears twice.
    bootstrap_products = _pos_catalog_products(products)
    from models.branch import Branch

    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    default_branch_id = current_branch_id() or (get_default_branch().id if get_default_branch() else None)
    if employee and employee.role != "admin" and employee.branch_id:
        default_branch_id = int(employee.branch_id)
    branch_options = [branch.to_dict() for branch in branches]

    oil_ui = {
        "feature_enabled": False,
        "mode_on": False,
        "can_toggle": False,
        "can_create": False,
        "settings": {},
    }
    try:
        from modules.order_installment_lifecycle.service import ui_context_for_employee

        oil_ui = ui_context_for_employee(employee)
    except Exception:
        pass

    ctx = dict(
        products=bootstrap_products,
        bootstrap_products=bootstrap_products,
        product_pos_stock_map={p["id"]: p["quantity"] for p in bootstrap_products},
        customers=customers,
        branches=branches,
        branch_options=branch_options,
        default_branch_id=default_branch_id,
        is_admin=bool(employee and employee.role == "admin"),
        cashier_name=session.get("name"),
        role=session.get("role"),
        employee=employee,
        pages=pages,
        can_edit_price=can_edit_price,
        can_print_invoice=can_print_invoice,
        can_view_my_orders=employee_can(employee, "view_my_orders"),
        order_data=order_data,
        cash_balance=cash_balance,
        company_name=session.get("tenant_slug") or session.get("name") or "Finora",
        paid_invoice_mutations_enabled=paid_invoice_mutations_enabled(),
        order_installment_ui=oil_ui,
    )

    if not _should_use_legacy_ui():
        try:
            return render_template("pos_dev/pos.html", **ctx)
        except TemplateNotFound:
            pass

    return render_template("pos.html", **ctx)


_MY_ORDERS_PERIODS = (
    ("this_month", "هذا الشهر"),
    ("today", "اليوم"),
    ("yesterday", "أمس"),
    ("this_week", "هذا الأسبوع"),
    ("last_7_days", "آخر 7 أيام"),
    ("last_30_days", "آخر 30 يوم"),
    ("last_month", "الشهر الماضي"),
    ("this_year", "السنة الحالية"),
    ("all", "كل الفترات"),
    ("custom", "نطاق مخصص"),
)
_MY_ORDERS_PERIOD_KEYS = {key for key, _label in _MY_ORDERS_PERIODS}


def _my_orders_period():
    """Resolve the POS my-orders date range. Default is the current month."""
    period_type = (request.args.get("period_type") or "this_month").strip()
    if period_type not in _MY_ORDERS_PERIOD_KEYS:
        period_type = "this_month"

    custom_from = (request.args.get("date_from") or "").strip() or None
    custom_to = (request.args.get("date_to") or "").strip() or None
    if period_type == "all":
        month_from, month_to = get_period_dates("this_month")
        return period_type, None, None, "كل الفترات", month_from.isoformat(), month_to.isoformat()

    try:
        date_from, date_to = get_period_dates(period_type, custom_from, custom_to)
    except (TypeError, ValueError):
        period_type = "this_month"
        date_from, date_to = get_period_dates("this_month")

    return (
        period_type,
        date_from,
        date_to,
        get_period_label(period_type, custom_from, custom_to),
        date_from.isoformat(),
        date_to.isoformat(),
    )


def _my_order_status_tone(status):
    """Return a presentation-only color tone for an order status."""
    value = (status or "").strip().lower()
    if any(word in value for word in ("راجع", "مرتجع", "ملغي", "مرفوض", "cancel", "return", "reject")):
        return "danger"
    if any(word in value for word in ("واصل", "تم التوصيل", "مكتمل", "مسدد", "deliver", "complete", "paid")):
        return "success"
    if any(word in value for word in ("شحن", "تجهيز", "قيد", "pending", "ship", "process")):
        return "warning"
    return "primary"


def _my_order_row(invoice):
    product_names = []
    for item in invoice.items:
        if is_shipping_item(item):
            continue
        name = (item.product_name or "").strip()
        if name and name not in product_names:
            product_names.append(name)

    customer = invoice.customer
    return {
        "id": invoice.id,
        "customer_name": (customer.name if customer else invoice.customer_name) or "—",
        "phone": (customer.phone if customer else "") or "—",
        "status": (invoice.status or "غير محدد").strip(),
        "status_tone": _my_order_status_tone(invoice.status),
        "product_names": product_names or ["—"],
    }


@pos_bp.route("/my-orders")
def my_orders():
    """Show only the orders created by the employee in the active session."""
    if "user_id" not in session:
        return redirect("/pos/login")

    employee = Employee.query.get(session["user_id"])
    if not employee:
        session.clear()
        return redirect("/pos/login")
    if not employee_can(employee, "view_my_orders"):
        return redirect("/pos"), 403

    search = (request.args.get("q") or "").strip()
    selected_status = (request.args.get("status") or "").strip()
    period_type, date_from, date_to, period_label, custom_date_from, custom_date_to = _my_orders_period()
    page = request.args.get("page", 1, type=int) or 1
    page = max(page, 1)

    employee_filter = Invoice.employee_id == employee.id
    query = (
        Invoice.query
        .options(selectinload(Invoice.customer), selectinload(Invoice.items))
        .filter(employee_filter)
    )

    if date_from and date_to:
        query = query.filter(
            db.func.date(Invoice.created_at) >= date_from,
            db.func.date(Invoice.created_at) <= date_to,
        )

    if selected_status:
        query = query.filter(Invoice.status == selected_status)

    if search:
        pattern = f"%{search}%"
        query = query.filter(db.or_(
            db.cast(Invoice.id, db.String).ilike(pattern),
            Invoice.customer_name.ilike(pattern),
            Invoice.customer.has(Customer.phone.ilike(pattern)),
            Invoice.items.any(OrderItem.product_name.ilike(pattern)),
        ))

    pagination = query.order_by(Invoice.created_at.desc(), Invoice.id.desc()).paginate(
        page=page,
        per_page=20,
        error_out=False,
    )
    rows = [_my_order_row(invoice) for invoice in pagination.items]
    statuses = [
        status
        for (status,) in (
            db.session.query(Invoice.status)
            .filter(employee_filter, Invoice.status.isnot(None), Invoice.status != "")
            .distinct()
            .order_by(Invoice.status.asc())
            .all()
        )
    ]
    total_orders = Invoice.query.filter(employee_filter).count()
    filter_args = {"period_type": period_type}
    if search:
        filter_args["q"] = search
    if selected_status:
        filter_args["status"] = selected_status
    if period_type == "custom":
        filter_args["date_from"] = custom_date_from
        filter_args["date_to"] = custom_date_to

    return render_template(
        "pos_my_orders.html",
        employee=employee,
        orders=rows,
        pagination=pagination,
        statuses=statuses,
        selected_status=selected_status,
        search=search,
        total_orders=total_orders,
        period_type=period_type,
        period_label=period_label,
        period_options=_MY_ORDERS_PERIODS,
        custom_date_from=custom_date_from,
        custom_date_to=custom_date_to,
        filter_args=filter_args,
    )


# =================================================
# LIVE SEARCH CUSTOMER
# =================================================
@pos_bp.route("/search-customer")
def search_customer():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    employee = Employee.query.get(session.get("user_id"))
    branch_id = resolve_write_branch_id(
        request.args,
        allow_admin_any_branch=True,
    )
    return jsonify(search_pos_customers(employee, q, branch_id=branch_id))



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
        employee = Employee.query.get(session.get("user_id"))
        write_branch_id = resolve_write_branch_id(
            data,
            allow_admin_any_branch=True,
        )
        if not _activate_pos_request_branch(write_branch_id):
            return jsonify({
                "status": "fail",
                "msg": "فرع الزبون غير موجود أو غير نشط",
            }), 400

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

        if not city:
            return jsonify({
                "status": "fail",
                "msg": "المحافظة مطلوبة"
            }), 400

        if is_phone_blacklisted_for_new_customer(phone, phone2):
            return jsonify({
                "status": "fail",
                "msg": "رقم الهاتف في القائمة السوداء — لا يُسمح بإضافة زبون بهذا الرقم.",
                "blacklisted": True,
            }), 400

        # منع تكرار الزبون حسب الرقم داخل الفرع المختار فقط.
        existing_query = Customer.query
        if employee and employee.role == "admin":
            existing_query = existing_query.execution_options(skip_branch_scope=True)
        if _shared_catalog_mode():
            existing = existing_query.filter_by(phone=phone).first()
        else:
            existing = existing_query.filter_by(
                branch_id=write_branch_id,
                phone=phone,
            ).first()
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
            branch_id=write_branch_id,
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
    except HTTPException:
        raise
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
    employee = Employee.query.get(session.get("user_id"))
    branch_id = resolve_write_branch_id(
        request.args,
        allow_admin_any_branch=True,
    )
    return jsonify(search_pos_products(employee, q, branch_id=branch_id))


# =================================================
# CREATE ORDER (INVOICE + ITEMS)
# =================================================
@pos_bp.route("/create-order", methods=["POST"])
def create_order():
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    employee = Employee.query.get(session["user_id"])
    if not employee:
        return jsonify({"error": "موظف غير صالح"}), 403
    data = request.json or {}
    submission_token = (
        data.get("submission_token")
        or request.headers.get("X-Submission-Token")
        or ""
    ).strip()
    try:
        payload = create_pos_order(
            employee=employee,
            customer_id=data.get("customer_id"),
            items=data.get("items") or [],
            branch_id=data.get("branch_id"),
            note=data.get("note"),
            scheduled_date=data.get("scheduled_date"),
            page_id=data.get("page_id"),
            discount_amount=data.get("discount_amount"),
            order_id=_editing_order_id_from_request(data),
            submission_token=submission_token,
            source="web_pos",
            raw_data=data,
        )
    except PosCheckoutError as exc:
        return jsonify(exc.payload), exc.status_code
    return jsonify(payload)


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
    employee = Employee.query.get(session["user_id"])
    products = Product.query.filter(
        Product.active == True,  # noqa: E712
        Product.pos_visible.isnot(False),
    ).order_by(Product.name).all()
    products = [
        product
        for product in products
        if employee_can_access_replacement_product(employee, product)
    ]
    
    return jsonify({
        "success": True,
        "products": [
            {**row, "buy_price": row.get("buy_price", 0)}
            for row in _pos_catalog_products(products)
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
    if not employee_can_access_replacement_product(employee, product):
        return jsonify({"error": "منتج استبدال متاح للإدمن فقط"}), 403
    
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


# =================================================
# JSON for API clients (FINORA Management Desktop)
# =================================================
def _pos_visible_catalog(employee):
    """Same product set and payload as /pos/all-products (active, POS-visible, replacement rules)."""
    products = Product.query.filter(
        Product.active == True,  # noqa: E712
        Product.pos_visible.isnot(False),
    ).order_by(Product.name).all()
    products = [p for p in products if employee_can_access_replacement_product(employee, p)]
    return _pos_catalog_products(products)


@pos_bp.route("/api/bootstrap")
def pos_api_bootstrap():
    """Provinces, permissions and branch the POS screen needs (checks mirror the web POS)."""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    from utils.branch_context import current_branch_id
    from utils.permission_checks import employee_can
    from utils.tenant_provinces import get_tenant_provinces_config

    employee = Employee.query.get(session["user_id"])
    config = get_tenant_provinces_config()
    primary = config.get("primary") or ""
    provinces = [primary] + [name for name in (config.get("list") or []) if name and name != primary]
    from modules.inventory_locations.selection import choices as storage_choices
    return jsonify({
        "success": True,
        "provinces": [name for name in provinces if name],
        "branch_id": current_branch_id(),
        "can_edit_price": employee_can(employee, "edit_price"),
        "can_print": employee_can(employee, "print_pos_invoice"),
        "can_pay": employee_can(employee, "pay_orders"),
        "storage_sources":storage_choices(current_branch_id() or _fallback_fulfillment_branch_id()),
    })


@pos_bp.route("/api/products")
def pos_api_products(*, _snapshot=False):
    """Paginated POS catalogue (search by name / SKU / barcode, category filter)."""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    employee = Employee.query.get(session["user_id"])
    rows = _pos_visible_catalog(employee)
    categories = sorted({(row.get("category") or "").strip() for row in rows if (row.get("category") or "").strip()})

    search = (request.args.get("search") or "").strip().lower()
    if search:
        rows = [
            row for row in rows
            if search in (row.get("name") or "").lower()
            or search in (row.get("sku") or "").lower()
            or search == (row.get("barcode") or "").lower()
            or (len(search) >= 4 and search in (row.get("barcode") or "").lower())
        ]
    category = (request.args.get("category") or "").strip()
    if category:
        rows = [row for row in rows if (row.get("category") or "").strip() == category]

    page_size = (len(rows) or 1) if _snapshot else min(60, max(1, request.args.get("page_size", 24, type=int) or 24))
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, request.args.get("page", 1, type=int) or 1), total_pages)
    start = (page - 1) * page_size
    return jsonify({
        "success": True,
        "rows": rows[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "categories": categories,
    })
