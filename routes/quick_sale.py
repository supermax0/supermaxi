from __future__ import annotations

from datetime import datetime

from flask import Blueprint, g, jsonify, redirect, render_template, request, session, url_for

from extensions import db
from models.branch import Branch, BranchStock
from models.customer import Customer
from models.delivery_agent import DeliveryAgent
from models.employee import Employee
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from models.treasury_account import TreasuryAccount
from utils.branch_migration import ensure_branch_schema
from utils.branch_context import init_branch_context
from utils.branch_scope import resolve_write_branch_id
from utils.branch_mode import independent_branches_enabled
from utils.branch_stock_service import BranchStockError
from utils.delivery_expense_service import sync_delivery_expense_for_invoice
from utils.order_shipping import apply_manual_delivery_fee_on_payment
from utils.order_stock_lock import apply_stock_actions, check_stock_rows, mark_order_stock_locked
from utils.order_stock_lock import clear_order_stock_lock
from utils.order_stock_policy import deferred_stock_enabled, ensure_policy_initialized
from utils.payment_ledger import append_payment_ledger_delta
from utils.payroll_schema import ensure_payroll_schema
from utils.payroll_service import sync_commission_line_for_invoice
from utils.permission_checks import employee_can
from utils.invoice_schema_guard import ensure_invoice_schema
from utils.product_color_service import (
    ProductColorError,
    colors_for_product_dict,
    product_has_colors,
)
from utils.product_schema_guard import ensure_customer_blacklist_columns, ensure_product_schema
from utils.order_item_schema_guard import ensure_order_item_schema
from utils.trade_in_service import (
    TradeInError,
    employee_can_access_replacement_product,
    product_sale_options,
    resolve_sale_selection,
    sync_trade_in_receipts,
)
from utils.customer_blacklist import is_phone_blacklisted_for_new_customer
from utils.tenant_feature_flags import tenant_feature_enabled
from utils.treasury_helpers import get_default_cash_account
from utils.tenant_provinces import get_tenant_provinces_config


quick_sale_bp = Blueprint("quick_sale", __name__, url_prefix="/quick-sale")


@quick_sale_bp.before_request
def quick_sale_use_tenant_db():
    if "user_id" not in session:
        return
    tenant_slug = session.get("tenant_slug")
    if tenant_slug:
        g.tenant = tenant_slug
        ensure_product_schema()
        ensure_order_item_schema()
        ensure_invoice_schema()
        ensure_customer_blacklist_columns()
        ensure_branch_schema()
        init_branch_context()
        ensure_policy_initialized()


@quick_sale_bp.before_request
def quick_sale_feature_guard():
    """Keep Quick Sale independent from POS while enforcing its own toggle."""
    if "user_id" not in session:
        return None
    if tenant_feature_enabled("quick_sale"):
        return None
    if request.method == "GET" and request.path.rstrip("/") == "/quick-sale":
        return redirect("/")
    return jsonify({"success": False, "error": "ميزة البيع السريع غير مفعلة"}), 403


def _current_employee():
    if "user_id" not in session:
        return None
    return Employee.query.get(session["user_id"])


def _can_use_quick_sale(employee: Employee | None) -> bool:
    if not employee or not employee.is_active:
        return False
    return employee_can(employee, "view_quick_sale")


def _safe_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _product_payload(product: Product, branch: Branch) -> dict:
    from utils.branch_stock_service import get_branch_stock

    # Shared-mode catalog copies can have different product IDs per branch.
    # Resolve the matching branch copy before showing its quantity.
    stock = get_branch_stock(int(branch.id), int(product.id))
    payload = {
        "id": product.id,
        "sale_key": f"{int(branch.id)}:{int(product.id)}",
        "branch_id": int(branch.id),
        "branch_name": branch.name,
        "name": product.name,
        "sku": product.sku or "",
        "barcode": product.barcode or "",
        "price": int(product.sale_price or 0),
        "stock": stock,
        "image_url": product.image_url or "",
    }
    payload.update(colors_for_product_dict(product))
    payload.update(product_sale_options(product))
    return payload


def _quick_sale_family_key(product: Product) -> str:
    """Stable shared-catalog identity used to collapse branch copies."""
    group_id = str(getattr(product, "catalog_group_id", "") or "").strip()
    if group_id:
        return f"group:{group_id}"
    barcode = str(getattr(product, "barcode", "") or "").strip().lower()
    if barcode:
        return f"barcode:{barcode}"
    sku = str(getattr(product, "sku", "") or "").strip().lower()
    if sku:
        return f"sku:{sku}"
    name = " ".join(str(getattr(product, "name", "") or "").strip().lower().split())
    return f"name:{name}"


def _quick_sale_branches(employee: Employee | None) -> list[Branch]:
    query = Branch.query.execution_options(skip_branch_scope=True).filter_by(is_active=True)
    if employee and employee.role != "admin":
        if not employee.branch_id:
            return []
        query = query.filter(Branch.id == int(employee.branch_id))
    return query.order_by(Branch.is_default.desc(), Branch.name.asc()).all()


def _activate_quick_sale_branch(source=None) -> Branch:
    """Resolve the sale branch once and apply it to all scoped reads/writes."""
    branch_id = resolve_write_branch_id(source, allow_admin_any_branch=True)
    branch = (
        Branch.query.execution_options(skip_branch_scope=True)
        .filter_by(id=int(branch_id), is_active=True)
        .first()
    )
    if branch is None:
        from flask import abort

        abort(400, description="الفرع المختار غير موجود أو غير نشط")
    g.branch = branch
    g.view_all_branches = False
    return branch


def _product_branch_filter(branch_id: int):
    """Return products that belong to, or are stocked by, the selected branch."""
    legacy_product_ids = db.session.query(BranchStock.product_id).filter(
        BranchStock.branch_id == int(branch_id)
    )
    if not independent_branches_enabled():
        # In shared mode the product row can belong to another branch while
        # its physical stock row belongs to the selected branch.  Filtering
        # only by Product.branch_id made those products disappear from quick
        # sale, even though inventory showed them.
        return db.or_(
            Product.branch_id == int(branch_id),
            Product.id.in_(legacy_product_ids),
        )
    return db.or_(
        Product.branch_id == int(branch_id),
        db.and_(Product.branch_id.is_(None), Product.id.in_(legacy_product_ids)),
    )


DEFAULT_QUICK_SALE_CITY = "بغداد"
ADVANCED_CHECKOUT_FEATURE = "quick_sale_advanced_checkout"


def _walk_in_phone(employee: Employee | None, provided_phone: str = "") -> str:
    phone = (provided_phone or "").strip()
    if phone:
        return phone
    if employee and employee.id:
        return f"QS{int(employee.id):06d}"
    return "QS000000"


def _account_payload(account: TreasuryAccount, branch_name: str = "") -> dict:
    is_cash = (account.account_type or "").strip().lower() == "cash"
    return {
        "id": account.id,
        "name": account.name,
        "type": account.account_type,
        "is_default": bool(account.is_default),
        "branch_id": account.branch_id,
        "branch_name": branch_name or "فرع غير محدد",
        "label": (
            f"{branch_name or 'فرع غير محدد'} — نقدي — {account.name}"
            if is_cash
            else f"{branch_name or 'فرع غير محدد'} — تحويل/بطاقة — {account.name}"
        ),
    }


def _active_payment_account(raw_id, branch_id: int) -> TreasuryAccount | None:
    account_id = _safe_int(raw_id)
    if account_id <= 0:
        return None
    return (
        TreasuryAccount.query.execution_options(skip_branch_scope=True)
        .filter_by(id=account_id, branch_id=int(branch_id), is_active=True)
        .first()
    )


def _customer_payload(customer: Customer) -> dict:
    blacklisted = bool(getattr(customer, "is_blacklisted", False))
    return {
        "id": customer.id,
        "name": customer.name or "",
        "phone": customer.phone or "",
        "phone2": customer.phone2 or "",
        "city": customer.city or DEFAULT_QUICK_SALE_CITY,
        "address": customer.address or "",
        "blacklisted": blacklisted,
        "blacklist_message": (
            "هذا الزبون في القائمة السوداء — لا يُسمح بالتعامل معه."
            if blacklisted
            else ""
        ),
    }


@quick_sale_bp.route("/")
def page():
    employee = _current_employee()
    if not _can_use_quick_sale(employee):
        return redirect("/pos")
    advanced_checkout_enabled = tenant_feature_enabled(
        ADVANCED_CHECKOUT_FEATURE,
        default=False,
    )
    branches = _quick_sale_branches(employee)
    selected_branch = _activate_quick_sale_branch({})
    # Every branch offered in the selector must be immediately sellable. This
    # also lets the standard payment modal filter accounts after an admin
    # switches branches without finding an empty account list.
    for branch in branches:
        get_default_cash_account(int(branch.id))
    payment_accounts = []
    delivery_agents = []
    if advanced_checkout_enabled:
        allowed_branch_ids = [int(branch.id) for branch in branches]
        accounts = (
            TreasuryAccount.query.execution_options(skip_branch_scope=True)
            .filter(
                TreasuryAccount.branch_id.in_(allowed_branch_ids or [-1]),
                TreasuryAccount.is_active.is_(True),
            )
            .order_by(
                TreasuryAccount.is_default.desc(),
                TreasuryAccount.account_type.asc(),
                TreasuryAccount.name.asc(),
            )
            .all()
        )
        branch_ids = {int(account.branch_id) for account in accounts if account.branch_id}
        branch_names = {
            int(branch.id): branch.name
            for branch in Branch.query.execution_options(skip_branch_scope=True)
            .filter(Branch.id.in_(branch_ids or [-1]))
            .all()
        }
        payment_accounts = [
            _account_payload(account, branch_names.get(int(account.branch_id or 0), ""))
            for account in accounts
        ]
        delivery_agents = [
            {"id": agent.id, "name": agent.name, "branch_id": agent.branch_id}
            for agent in DeliveryAgent.query.execution_options(skip_branch_scope=True)
            .filter(
                DeliveryAgent.branch_id.in_(allowed_branch_ids or [-1]),
                DeliveryAgent.is_active.is_(True),
            )
            .order_by(DeliveryAgent.name.asc())
            .all()
        ]
    provinces_config = get_tenant_provinces_config()
    return render_template(
        "quick_sale.html",
        cashier_name=(employee.name if employee else "موظف"),
        quick_branches=[branch.to_dict() for branch in branches],
        quick_branch_id=int(selected_branch.id),
        quick_branch_name=selected_branch.name,
        quick_is_admin=bool(employee and employee.role == "admin"),
        advanced_checkout_enabled=advanced_checkout_enabled,
        quick_payment_accounts=payment_accounts,
        quick_delivery_agents=delivery_agents,
        quick_provinces=provinces_config.get("list") or [DEFAULT_QUICK_SALE_CITY],
        quick_primary_province=provinces_config.get("primary") or DEFAULT_QUICK_SALE_CITY,
    )


@quick_sale_bp.route("/customers", methods=["GET"])
def search_customers():
    employee = _current_employee()
    if not _can_use_quick_sale(employee):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    if not tenant_feature_enabled(ADVANCED_CHECKOUT_FEATURE, default=False):
        return jsonify({"success": False, "error": "الميزة غير مفعلة"}), 403

    query_text = (request.args.get("q") or "").strip()
    if len(query_text) < 2:
        return jsonify({"success": True, "customers": []})
    like = f"%{query_text}%"
    # Customers are company contacts, not inventory. They can be reused by
    # every branch while the resulting invoice keeps its selected branch.
    customers = (
        Customer.query.execution_options(skip_branch_scope=True).filter(
            db.or_(
                Customer.name.ilike(like),
                Customer.phone.ilike(like),
                Customer.phone2.ilike(like),
            )
        )
        .order_by(Customer.name.asc(), Customer.id.desc())
        .limit(15)
        .all()
    )
    return jsonify({
        "success": True,
        "customers": [_customer_payload(customer) for customer in customers],
    })


@quick_sale_bp.route("/customers", methods=["POST"])
def add_customer():
    employee = _current_employee()
    if not _can_use_quick_sale(employee):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    if not tenant_feature_enabled(ADVANCED_CHECKOUT_FEATURE, default=False):
        return jsonify({"success": False, "error": "الميزة غير مفعلة"}), 403

    data = request.get_json(force=True) or {}
    preferred = int(_activate_quick_sale_branch(data).id)
    name = str(data.get("name") or "").strip()
    phone = str(data.get("phone") or "").strip()
    phone2 = str(data.get("phone2") or "").strip()
    city = str(data.get("city") or "").strip()
    address = str(data.get("address") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "أدخل اسم الزبون"}), 400
    if not phone:
        return jsonify({"success": False, "error": "أدخل رقم هاتف الزبون"}), 400
    if not city:
        return jsonify({"success": False, "error": "اختر المحافظة"}), 400
    if not address:
        return jsonify({"success": False, "error": "أدخل عنوان الزبون"}), 400
    if len(name) > 150 or len(phone) > 20 or len(phone2) > 20 or len(city) > 100 or len(address) > 255:
        return jsonify({"success": False, "error": "بيانات الزبون أطول من الحد المسموح"}), 400
    if is_phone_blacklisted_for_new_customer(phone, phone2 or None):
        return jsonify({
            "success": False,
            "error": "رقم الهاتف في القائمة السوداء — لا يُسمح بإضافة هذا الزبون.",
        }), 400

    customer = (
        Customer.query.execution_options(skip_branch_scope=True)
        .filter_by(phone=phone)
        .first()
    )
    if customer:
        if getattr(customer, "is_blacklisted", False):
            return jsonify({"success": False, "error": "هذا الزبون في القائمة السوداء"}), 400
        return jsonify({"success": True, "customer": _customer_payload(customer), "existing": True})

    customer = Customer(
        branch_id=preferred,
        name=name,
        phone=phone,
        phone2=phone2 or None,
        city=city,
        address=address,
        tenant_id=session.get("tenant_id"),
    )
    db.session.add(customer)
    db.session.commit()
    return jsonify({"success": True, "customer": _customer_payload(customer), "existing": False})


@quick_sale_bp.route("/products")
def products():
    employee = _current_employee()
    if not _can_use_quick_sale(employee):
        return jsonify({"success": False, "error": "غير مصرح"}), 403

    q = (request.args.get("q") or "").strip()
    branches = _quick_sale_branches(employee)
    grouped_payloads: dict[str, list[dict]] = {}
    seen: set[tuple[int, str]] = set()
    for branch in branches:
        query = Product.query.execution_options(skip_branch_scope=True).filter(
            Product.active == True,  # noqa: E712
            Product.pos_visible.isnot(False),
            _product_branch_filter(branch.id),
        )
        if q:
            like = f"%{q}%"
            query = query.filter(
                db.or_(
                    Product.name.ilike(like),
                    Product.sku.ilike(like),
                    Product.barcode.ilike(like),
                    Product.description.ilike(like),
                )
            )
        for product in query.order_by(Product.name.asc()).limit(24).all():
            if not employee_can_access_replacement_product(employee, product):
                continue
            family = _quick_sale_family_key(product)
            key = (int(branch.id), family)
            if key in seen:
                continue
            seen.add(key)
            payload = _product_payload(product, branch)
            grouped_payloads.setdefault(family, []).append(payload)

    payloads = []
    for family_key, sources in grouped_payloads.items():
        sources.sort(key=lambda row: (-int(row.get("stock") or 0), row["branch_name"]))
        representative = dict(sources[0])
        representative["sale_key"] = family_key
        representative["stock"] = sum(max(0, int(row.get("stock") or 0)) for row in sources)
        representative["branch_name"] = (
            sources[0]["branch_name"]
            if len(sources) == 1
            else f"متوفر في {len(sources)} فروع"
        )
        representative["stock_sources"] = sources
        payloads.append(representative)
    payloads.sort(key=lambda row: row["name"])
    return jsonify({
        "success": True,
        "branches": [branch.to_dict() for branch in branches],
        "products": payloads[:72],
    })


@quick_sale_bp.route("/execute", methods=["POST"])
def execute():
    employee = _current_employee()
    if not _can_use_quick_sale(employee):
        return jsonify({"success": False, "error": "غير مصرح"}), 403

    data = request.get_json(force=True) or {}
    selected_branch = _activate_quick_sale_branch(data)
    preferred = int(selected_branch.id)
    advanced_checkout_enabled = tenant_feature_enabled(
        ADVANCED_CHECKOUT_FEATURE,
        default=False,
    )
    advanced_checkout = bool(data.get("advanced_checkout")) and advanced_checkout_enabled
    customer_data = data.get("customer") or {}
    selected_customer = None
    selected_customer_id = _safe_int(customer_data.get("customer_id"))
    if advanced_checkout and selected_customer_id > 0:
        selected_customer = (
            Customer.query.execution_options(skip_branch_scope=True)
            .filter_by(id=selected_customer_id)
            .first()
        )
        if not selected_customer:
            return jsonify({"success": False, "error": "الزبون المختار غير موجود"}), 400
        if getattr(selected_customer, "is_blacklisted", False):
            return jsonify({
                "success": False,
                "error": "هذا الزبون في القائمة السوداء — لا يُسمح بالتعامل معه.",
            }), 400
    add_customer = advanced_checkout and selected_customer is None and bool(customer_data.get("enabled"))
    provided_name = str(customer_data.get("name") or "").strip()
    provided_phone = str(customer_data.get("phone") or "").strip()
    phone2 = str(customer_data.get("phone2") or "").strip()
    provided_city = str(customer_data.get("city") or "").strip()
    address = str(customer_data.get("address") or "").strip()
    if add_customer:
        if not provided_name:
            return jsonify({"success": False, "error": "أدخل اسم الزبون"}), 400
        if not provided_phone:
            return jsonify({"success": False, "error": "أدخل رقم هاتف الزبون"}), 400
        if len(provided_name) > 150 or len(provided_phone) > 20 or len(phone2) > 20 or len(address) > 255:
            return jsonify({"success": False, "error": "بيانات الزبون أطول من الحد المسموح"}), 400
    if selected_customer is not None:
        phone = selected_customer.phone
        city = selected_customer.city or DEFAULT_QUICK_SALE_CITY
        name = selected_customer.name
    else:
        phone = _walk_in_phone(
            employee,
            provided_phone if (add_customer or not advanced_checkout) else "",
        )
        city = provided_city or DEFAULT_QUICK_SALE_CITY
        name = (
            provided_name
            if add_customer
            else ((employee.name if employee and employee.name else "").strip() or "موظف")
        )
    items = data.get("items") or []

    if not items:
        return jsonify({"success": False, "error": "أضف منتج واحد على الأقل"}), 400

    allowed_branch_ids = {int(branch.id) for branch in _quick_sale_branches(employee)}
    clean_items = []
    stock_rows = []
    for item in items:
        product_id = _safe_int(item.get("product_id"))
        source_branch_id = _safe_int(item.get("branch_id"), preferred)
        qty = max(1, _safe_int(item.get("qty"), 1))
        if product_id <= 0:
            continue
        if source_branch_id not in allowed_branch_ids:
            return jsonify({"success": False, "error": "فرع المنتج غير مسموح لهذا المستخدم"}), 403
        product = (
            Product.query.execution_options(skip_branch_scope=True)
            .filter(
                Product.id == product_id,
                Product.active.is_(True),
                Product.pos_visible.isnot(False),
                _product_branch_filter(source_branch_id),
            )
            .first()
        )
        if not product:
            return jsonify({
                "success": False,
                "error": "المنتج غير موجود في فرعه أو غير فعال",
            }), 400
        if not employee_can_access_replacement_product(employee, product):
            return jsonify({
                "success": False,
                "error": "منتج استبدال متاح للإدمن فقط",
            }), 403
        variant_color = (item.get("color") or item.get("variant_color") or "").strip()
        if product_has_colors(product) and not variant_color:
            return jsonify({"success": False, "error": f"يجب اختيار لون للمنتج: {product.name}"}), 400
        try:
            sale_mode, unit_price, source_product = resolve_sale_selection(
                product,
                item,
                allow_custom_price=employee_can(employee, "edit_price"),
                customer_city=city,
            )
        except TradeInError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        clean_items.append({
            "product": product,
            "qty": qty,
            "price": unit_price,
            "fulfillment_branch_id": source_branch_id,
            "variant_color": variant_color or None,
            "sale_mode": sale_mode,
            "source_product": source_product,
        })
        stock_rows.append({
            "product": product,
            "product_id": product.id,
            "quantity": qty,
            "variant_color": variant_color or None,
            "fulfillment_branch_id": source_branch_id,
        })

    if not clean_items:
        return jsonify({"success": False, "error": "لا توجد منتجات صالحة"}), 400

    stock_check = check_stock_rows(stock_rows, preferred_branch_id=preferred)
    if advanced_checkout and not stock_check.can_fulfill:
        return jsonify({
            "success": False,
            "error": stock_check.reason_text or "المخزون غير كافٍ لتنفيذ البيع السريع",
        }), 400

    total = sum(int(row["price"]) * int(row["qty"]) for row in clean_items)
    default_cash_account = get_default_cash_account(preferred) if stock_check.can_fulfill else None
    payment_type = str(data.get("payment_type") or "cash").strip().lower()
    payment_status = "مسدد"
    paid_amount = total
    payment_account = None
    if advanced_checkout:
        if payment_type not in {"credit", "cash", "partial", "bank"}:
            return jsonify({"success": False, "error": "طريقة التسديد غير صحيحة"}), 400
        if payment_type in {"credit", "partial"} and selected_customer is None and not add_customer:
            return jsonify({
                "success": False,
                "error": "اختر زبوناً أو أضف زبوناً لأن الفاتورة فيها مبلغ متبقٍ",
            }), 400
        if payment_type == "credit":
            payment_status = "غير مسدد"
            paid_amount = 0
        elif payment_type == "partial":
            paid_amount = _safe_int(data.get("paid_amount"))
            if paid_amount <= 0 or paid_amount >= total:
                return jsonify({
                    "success": False,
                    "error": "المبلغ الجزئي يجب أن يكون أكبر من صفر وأقل من إجمالي الفاتورة",
                }), 400
            payment_status = "جزئي"

        if payment_type != "credit":
            payment_account = _active_payment_account(data.get("treasury_account_id"), preferred)
            if not payment_account:
                return jsonify({"success": False, "error": "اختر حساب استلام فعال"}), 400
            account_is_cash = (payment_account.account_type or "").strip().lower() == "cash"
            if payment_type == "cash" and not account_is_cash:
                return jsonify({"success": False, "error": "اختر حساباً نقدياً للدفع النقدي"}), 400
            if payment_type == "bank" and account_is_cash:
                return jsonify({"success": False, "error": "اختر البنك أو البطاقة المستلمة"}), 400
    elif stock_check.can_fulfill:
        payment_account = _active_payment_account(data.get("treasury_account_id"), preferred)
        if payment_account is None:
            payment_account = default_cash_account

    delivery_agent = None
    if advanced_checkout and data.get("delivery_agent_id") not in (None, "", 0, "0"):
        delivery_agent = DeliveryAgent.query.filter_by(
            id=_safe_int(data.get("delivery_agent_id")),
            branch_id=preferred,
            is_active=True,
        ).first()
        if not delivery_agent:
            return jsonify({"success": False, "error": "مندوب التوصيل غير موجود أو غير فعال"}), 400

    customer = selected_customer or Customer.query.execution_options(skip_branch_scope=True).filter_by(
        phone=phone,
    ).first()
    if customer:
        if selected_customer is None:
            customer.name = name or customer.name
            customer.city = city
        if add_customer and selected_customer is None:
            customer.phone2 = phone2 or None
            customer.address = address or None
    else:
        customer = Customer(
            branch_id=preferred,
            name=name,
            phone=phone,
            phone2=(phone2 or None) if add_customer else None,
            city=city,
            address=(address or None) if add_customer else None,
            tenant_id=getattr(clean_items[0]["product"], "tenant_id", None),
        )
        db.session.add(customer)
        db.session.flush()

    invoice = Invoice(
        customer_id=customer.id,
        customer_name=customer.name,
        employee_id=employee.id if employee else None,
        employee_name=employee.name if employee else None,
        branch_id=preferred,
        total=0,
        paid_amount=0,
        status=(
            "تم الطلب"
            if (not stock_check.can_fulfill or delivery_agent is not None)
            else "تم التوصيل"
        ),
        payment_status=("غير مسدد" if not stock_check.can_fulfill else payment_status),
        note=(
            "بيع سريع - مقفل بانتظار توفر المخزون"
            if not stock_check.can_fulfill
            else f"بيع سريع - {payment_status}"
        ),
        shipping_status="قيد الشحن" if delivery_agent is not None else None,
        delivery_agent_id=delivery_agent.id if delivery_agent is not None else None,
        created_at=datetime.utcnow(),
        stock_is_deducted=False,
    )
    db.session.add(invoice)
    db.session.flush()

    for idx, row in enumerate(clean_items):
        product = row["product"]
        qty = int(row["qty"])
        unit_price = int(row["price"])
        line_total = unit_price * qty
        fulfillment_branch_id = (
            stock_check.actions[idx].fulfillment_branch_id
            if stock_check.can_fulfill and idx < len(stock_check.actions)
            else None
        )
        variant_color = row.get("variant_color")
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=qty,
                price=unit_price,
                cost=int(product.buy_price or 0),
                total=line_total,
                fulfillment_branch_id=fulfillment_branch_id,
                variant_color=variant_color,
                sale_mode=row["sale_mode"],
                trade_in_source_product_id=None,
                trade_in_source_product_name=None,
            )
        )

    delivery_fee = max(0, _safe_int(data.get("delivery_fee"), 0))

    invoice.total = total
    if stock_check.can_fulfill:
        try:
            apply_stock_actions(stock_check.actions, invoice=invoice)
            invoice.stock_is_deducted = True
            invoice.stock_deducted_at = datetime.utcnow()
        except (BranchStockError, ProductColorError) as exc:
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 400
        invoice.paid_amount = paid_amount
        tenant_id = getattr(customer, "tenant_id", None)
        apply_manual_delivery_fee_on_payment(invoice, delivery_fee, tenant_id)
        if int(invoice.paid_amount or 0) > 0:
            append_payment_ledger_delta(
                invoice.id,
                int(invoice.paid_amount or 0),
                payment_account.id if payment_account is not None else None,
            )
        delivery_expense_account_id = None
        if invoice.payment_status == "مسدد" and delivery_fee > 0:
            delivery_expense_account_id = default_cash_account.id
        sync_delivery_expense_for_invoice(
            invoice,
            treasury_account_id=delivery_expense_account_id,
        )
        ensure_payroll_schema()
        sync_commission_line_for_invoice(invoice)
    else:
        invoice.paid_amount = 0
        if deferred_stock_enabled():
            clear_order_stock_lock(invoice)
        else:
            mark_order_stock_locked(invoice, stock_check.reason_text)

    db.session.flush()
    sync_trade_in_receipts(invoice)

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 500

    return jsonify(
        {
            "success": True,
            "invoice_id": invoice.id,
            "total": invoice.total,
            "stock_locked": bool(getattr(invoice, "is_stock_locked", False)),
            "stock_lock_reason": getattr(invoice, "stock_lock_reason", None),
            "print_url": url_for("orders.invoice_page", order_id=invoice.id),
        }
    )
