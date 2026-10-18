from flask import Blueprint, render_template, request, jsonify
from sqlalchemy.orm import joinedload
from extensions import db
from utils.branch_scope import resolve_write_branch_id
from models.shipping import ShippingCompany
from models.invoice import Invoice
from models.shipping_payment import ShippingPayment
from models.order_item import OrderItem
from models.product import Product
from datetime import datetime
import secrets

from utils.payment_ledger import append_payment_ledger_delta
from utils.delivery_expense_service import sync_delivery_expense_for_invoice
from utils.order_shipping import apply_manual_delivery_fee_on_payment
from utils.permission_checks import guard_permission
from utils.activity_logger import (
    INVOICE_SNAPSHOT_FIELDS,
    log_activity,
    log_mutation,
    snapshot_attrs,
)
from utils.treasury_helpers import resolve_treasury_account_id
from utils.treasury_schema_guard import ensure_treasury_schema
from utils.shipping_settlement_service import ensure_paid_shipping_order_settled
from utils.order_stock_policy import OrderStockError, ensure_stock_for_transition, select_order_stock_branch
from utils.barcode_normalization import normalize_barcode
from utils.tenant_feature_flags import tenant_feature_enabled

shipping_bp = Blueprint("shipping", __name__, url_prefix="/shipping")


def _shipping_company_key(name):
    return " ".join(str(name or "").split()).casefold()


def _unique_shipping_companies(companies):
    unique = []
    seen = set()
    for company in companies:
        key = _shipping_company_key(company.name)
        if key in seen:
            continue
        seen.add(key)
        unique.append(company)
    return unique


def _merged_shipping_company_ids(company):
    key = _shipping_company_key(company.name)
    return [
        item.id for item in ShippingCompany.query.order_by(ShippingCompany.id).all()
        if _shipping_company_key(item.name) == key
    ]


def _company_shipping_barcode_matches(order, barcode):
    from utils.shipping_barcodes import get_shipping_barcodes_list
    code = normalize_barcode(barcode)
    return bool(code) and any(normalize_barcode(saved) == code for saved in get_shipping_barcodes_list(order))


def _company_return_order_payload(order):
    return {
        "id": order.id,
        "customer": getattr(order.customer, "name", "") if order.customer else "",
        "phone": getattr(order.customer, "phone", "") if order.customer else "",
        "total": int(order.total or 0),
        "remaining": remaining_amount(order),
        "status": order.status,
        "shipping_company": order.shipping_company.name if order.shipping_company else "",
    }


def _company_returns_feature_guard(json_response=False):
    if tenant_feature_enabled("shipping_company_returns", default=False):
        return None
    if json_response:
        return jsonify({"success": False, "error": "ميزة مرتجع شركة النقل غير مفعلة لهذه الشركة"}), 403
    return jsonify({"success": False, "error": "ميزة مرتجع شركة النقل غير مفعلة لهذه الشركة"}), 403


def _company_returns_action(raw_action):
    return str(raw_action or "return").strip().lower()


def company_returns_action_permission(raw_action):
    return "pay_orders" if _company_returns_action(raw_action) == "settle" else "return_orders"


@shipping_bp.route("/company-returns")
def company_returns_page():
    denied = _company_returns_feature_guard()
    if denied:
        return denied
    companies = _unique_shipping_companies(
        ShippingCompany.query.order_by(ShippingCompany.name, ShippingCompany.id).all()
    )
    return render_template("shipping_company_returns.html", companies=companies)


@shipping_bp.route("/company-returns/lookup")
def company_returns_lookup():
    denied = _company_returns_feature_guard(json_response=True)
    if denied:
        return denied
    barcode = normalize_barcode(request.args.get("barcode"))
    company_id = request.args.get("company_id", type=int)
    action = _company_returns_action(request.args.get("action"))
    if action not in {"return", "settle"}:
        return jsonify({"success": False, "error": "نوع العملية غير صالح"}), 400
    if not barcode or not company_id:
        return jsonify({"success": False, "error": "اختر شركة النقل وامسح باركودها"}), 400
    company = ShippingCompany.query.get(company_id)
    if not company:
        return jsonify({"success": False, "error": "شركة النقل غير موجودة"}), 404
    company_ids = _merged_shipping_company_ids(company)
    orders = Invoice.query.options(joinedload(Invoice.customer), joinedload(Invoice.shipping_company)).filter(Invoice.shipping_company_id.in_(company_ids)).all()
    order = next((item for item in orders if _company_shipping_barcode_matches(item, barcode)), None)
    if not order:
        return jsonify({"success": False, "error": "لم يتم العثور على طلب بهذا الباركود لهذه الشركة"}), 404
    if is_returned(order.status, order.payment_status) or is_canceled(order.status, order.payment_status):
        return jsonify({"success": False, "error": "هذا الطلب مرتجع أو ملغي مسبقاً"}), 409
    if action == "settle" and remaining_amount(order) <= 0:
        return jsonify({"success": False, "error": "هذا الطلب مسدد مسبقاً"}), 409
    return jsonify({"success": True, "order": _company_return_order_payload(order), "barcode": barcode})


@shipping_bp.route("/company-returns/confirm", methods=["POST"])
def company_returns_confirm():
    denied = _company_returns_feature_guard(json_response=True)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    barcode = normalize_barcode(data.get("barcode"))
    company_id = data.get("company_id")
    if not barcode or not company_id:
        return jsonify({"success": False, "error": "بيانات المرتجع غير مكتملة"}), 400
    company = ShippingCompany.query.get(company_id)
    if not company:
        return jsonify({"success": False, "error": "شركة النقل غير موجودة"}), 404
    company_ids = _merged_shipping_company_ids(company)
    order = next((item for item in Invoice.query.filter(Invoice.shipping_company_id.in_(company_ids)).all() if _company_shipping_barcode_matches(item, barcode)), None)
    if not order:
        return jsonify({"success": False, "error": "باركود شركة النقل لا يطابق أي طلب"}), 404
    return return_order(order.id)


@shipping_bp.route("/company-returns/confirm-bulk", methods=["POST"])
def company_returns_confirm_bulk():
    denied = _company_returns_feature_guard(json_response=True)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    action = _company_returns_action(data.get("action"))
    if action not in {"return", "settle"}:
        return jsonify({"success": False, "error": "نوع العملية غير صالح"}), 400
    if not isinstance(items, list) or not items:
        return jsonify({"success": False, "error": "لا توجد طلبات للتنفيذ"}), 400
    completed, errors = [], []
    try:
        treasury_account_id = None
        if action == "settle":
            ensure_treasury_schema()
            treasury_account_id = resolve_treasury_account_id(data.get("treasury_account_id"))
        for item in items[:100]:
            barcode = normalize_barcode(item.get("barcode"))
            company_id = item.get("company_id")
            company = ShippingCompany.query.get(company_id) if company_id else None
            company_ids = _merged_shipping_company_ids(company) if company else []
            order = next((candidate for candidate in Invoice.query.filter(Invoice.shipping_company_id.in_(company_ids)).all() if _company_shipping_barcode_matches(candidate, barcode)), None) if company else None
            if not order:
                errors.append({"barcode": barcode, "error": "باركود شركة النقل لا يطابق أي طلب"})
                continue
            before = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
            previous_paid = _effective_paid_amount_inv(order)
            if action == "settle":
                if is_returned(order.status, order.payment_status) or is_canceled(order.status, order.payment_status):
                    errors.append({"order_id": order.id, "barcode": barcode, "error": "لا يمكن تسديد طلب مرتجع أو ملغي"})
                    continue
                if remaining_amount(order) <= 0:
                    errors.append({"order_id": order.id, "barcode": barcode, "error": "الطلب مسدد مسبقاً"})
                    continue
                try:
                    select_order_stock_branch(order, item.get("branch_id") or data.get("branch_id"))
                    ensure_stock_for_transition(order, target_payment_status="مسدد")
                except OrderStockError as exc:
                    errors.append({"order_id": order.id, "barcode": barcode, "error": exc.message})
                    continue
                order.payment_status = "مسدد"
                order.paid_amount = order.total
                delivery_fee = _parse_opening_balance(item.get("delivery_fee"))
                tenant_id = getattr(order, "tenant_id", None)
                if getattr(order, "customer", None) is not None:
                    tenant_id = getattr(order.customer, "tenant_id", tenant_id)
                apply_manual_delivery_fee_on_payment(order, delivery_fee, tenant_id)
                ensure_paid_shipping_order_settled(order, treasury_account_id=treasury_account_id)
                append_payment_ledger_delta(order.id, _effective_paid_amount_inv(order) - previous_paid)
                sync_delivery_expense_for_invoice(order, treasury_account_id=treasury_account_id)
                log_text = f"تسديد الطلب #{order.id} من شركة النقل"
            else:
                try:
                    already_returned, message = process_order_return(order, barcode)
                except OrderLifecycleError as exc:
                    errors.append({"order_id": order.id, "barcode": barcode, "error": exc.message})
                    continue
                if already_returned:
                    errors.append({"order_id": order.id, "barcode": barcode, "error": message})
                    continue
                db.session.add(ShippingPayment(branch_id=order.branch_id, shipping_company_id=order.shipping_company_id, invoice_id=order.id, amount=order.total, action="ترجيع"))
                append_payment_ledger_delta(order.id, _effective_paid_amount_inv(order) - previous_paid)
                sync_delivery_expense_for_invoice(order)
                log_text = f"ترجيع الطلب #{order.id} من شركة النقل"
            log_mutation("update", "shipping", "invoice", order.id, before, snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS), log_text)
            completed.append(order.id)
        db.session.commit()
        operation_name = "تسديد" if action == "settle" else "مرتجع"
        return jsonify({"success": True, "completed": completed, "errors": errors, "message": f"تم تنفيذ {operation_name} {len(completed)} طلب بنجاح"})
    except OrderLifecycleError as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": exc.message, "completed": completed, "errors": errors}), exc.status_code
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc), "completed": completed, "errors": errors}), 500

_SHIPPING_WRITE_ENDPOINTS = {
    "shipping.add_company",
    "shipping.update_company",
    "shipping.delete_company",
    "shipping.settle_order",
    "shipping.collect_company_balance",
    "shipping.cancel_order",
    "shipping.return_order",
    "shipping.company_returns_confirm",
    "shipping.company_returns_confirm_bulk",
}


@shipping_bp.before_request
def _shipping_permission_guard():
    from flask import session
    if "user_id" not in session:
        return None
    perm = "manage_shipping" if request.endpoint in _SHIPPING_WRITE_ENDPOINTS else "view_shipping"
    denied = guard_permission(perm)
    if denied:
        return denied
    action_permissions = {
        "shipping.settle_order": "pay_orders",
        "shipping.cancel_order": "delete_orders",
        "shipping.return_order": "return_orders",
        "shipping.company_returns_confirm": "return_orders",
        "shipping.company_returns_confirm_bulk": company_returns_action_permission(
            (request.get_json(silent=True) or {}).get("action")
        ),
    }
    action_permission = action_permissions.get(request.endpoint)
    if action_permission:
        return guard_permission(action_permission)
    return None

# حالات مساعدة لتوحيد المنطق مع الدفع الجزئي
RETURN_STATUSES = ["مرتجع", "راجع", "راجعة"]
CANCELED_STATUSES = ["ملغي"]
from utils.order_status import is_canceled, is_returned, is_completed
from utils.order_lifecycle import OrderLifecycleError, process_order_cancel, process_order_return
from utils.cash_calculations import _effective_paid_amount as _effective_paid_amount_inv


def _ensure_shipping_opening_balance_column():
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(db.engine)
        if "shipping_company" not in inspector.get_table_names():
            return
        cols = {col["name"] for col in inspector.get_columns("shipping_company")}
        if "opening_balance" not in cols:
            db.session.execute(
                text("ALTER TABLE shipping_company ADD COLUMN opening_balance INTEGER DEFAULT 0")
            )
            db.session.commit()
    except Exception:
        db.session.rollback()


def _parse_opening_balance(raw_value):
    if raw_value is None:
        return 0
    cleaned = str(raw_value).strip().replace(",", "").replace(" ", "")
    if not cleaned:
        return 0
    try:
        return max(0, int(float(cleaned)))
    except (TypeError, ValueError):
        return 0


def effective_paid_amount(order: Invoice) -> int:
    total = int(getattr(order, "total", 0) or 0)
    payment_status = getattr(order, "payment_status", None)
    status = getattr(order, "status", None)

    if payment_status in ("مرتجع", "ملغي", "راجع", "راجعة") or status in (
        "مرتجع",
        "ملغي",
        "راجع",
        "راجعة",
    ):
        return 0
    if payment_status == "مسدد" or status in ("مسدد", "تم التوصيل"):
        return max(total, 0)
    if payment_status == "جزئي":
        paid_amount = int(getattr(order, "paid_amount", 0) or 0)
        if paid_amount < 0:
            return 0
        return min(paid_amount, total) if total > 0 else paid_amount
    return 0


def remaining_amount(order: Invoice) -> int:
    total = int(getattr(order, "total", 0) or 0)
    remaining = total - effective_paid_amount(order)
    return remaining if remaining > 0 else 0

# =====================================
# Shipping Main Page
# =====================================
@shipping_bp.route("/")
def shipping_page():
    _ensure_shipping_opening_balance_column()

    companies = _unique_shipping_companies(
        ShippingCompany.query.order_by(ShippingCompany.name, ShippingCompany.id).all()
    )
    result = []
    total_orders = 0
    total_due = 0

    for c in companies:
        company_ids = _merged_shipping_company_ids(c)
        orders = Invoice.query.filter(Invoice.shipping_company_id.in_(company_ids)).all()
        opening_balance = sum(
            int(getattr(item, "opening_balance", 0) or 0)
            for item in ShippingCompany.query.filter(ShippingCompany.id.in_(company_ids)).all()
        )

        orders_due = sum(
            remaining_amount(o) for o in orders
            if o.payment_status != "مرتجع"
            and o.status not in (CANCELED_STATUSES + RETURN_STATUSES)
        )
        due = opening_balance + orders_due
        total_orders += len(orders)
        total_due += due

        result.append({
            "id": c.id,
            "name": c.name,
            "orders_count": len(orders),
            "opening_balance": opening_balance,
            "orders_due": orders_due,
            "due": due,
            "access_token": c.access_token,
            "public_url": f"/delivery/public/{c.access_token}" if c.access_token else None
        })

    return render_template(
        "shipping.html",
        companies=result,
        shipping_total_orders=total_orders,
        shipping_total_due=total_due,
    )

# =====================================
# Add Shipping Company
# =====================================
@shipping_bp.route("/add", methods=["POST"])
def add_company():
    _ensure_shipping_opening_balance_column()
    data = request.json
    name = data.get("name")

    if not name:
        return jsonify({"error": "name required"}), 400

    duplicate = next(
        (item for item in ShippingCompany.query.all()
         if _shipping_company_key(item.name) == _shipping_company_key(name)),
        None,
    )
    if duplicate:
        return jsonify({"success": False, "error": "شركة النقل موجودة مسبقاً", "id": duplicate.id}), 409

    opening_balance = _parse_opening_balance(data.get("opening_balance"))

    # إنشاء token فريد
    access_token = secrets.token_urlsafe(32)
    
    # التأكد من أن الـ token فريد
    while ShippingCompany.query.filter_by(access_token=access_token).first():
        access_token = secrets.token_urlsafe(32)

    # إنشاء username و password افتراضيين
    username = name.lower().replace(" ", "_") + "_" + str(datetime.now().timestamp())[:10]
    password = secrets.token_urlsafe(8)  # كلمة مرور عشوائية
    
    # التأكد من أن username فريد
    while ShippingCompany.query.filter_by(username=username).first():
        username = name.lower().replace(" ", "_") + "_" + str(datetime.now().timestamp())[:10]

    company = ShippingCompany(
        branch_id=resolve_write_branch_id(data),
        name=name,
        opening_balance=opening_balance,
        access_token=access_token,
        username=username,
        password=password
    )
    db.session.add(company)
    db.session.commit()
    try:
        log_activity(
            "create",
            "shipping",
            f"إضافة شركة شحن: {company.name}",
            entity_type="shipping_company",
            entity_id=company.id,
            payload={"name": company.name, "opening_balance": company.opening_balance},
        )
    except Exception:
        pass
    
    return jsonify({
        "success": True,
        "id": company.id,
        "access_token": company.access_token,
        "username": company.username,
        "password": company.password,
        "login_url": "/delivery/login"
    })

# =====================================
# Update Company
# =====================================
@shipping_bp.route("/update/<int:id>", methods=["POST"])
def update_company(id):
    _ensure_shipping_opening_balance_column()
    company = ShippingCompany.query.get_or_404(id)
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "اسم الشركة مطلوب"}), 400

    # Branch copies share one display name; do not treat them as duplicates.
    sibling_ids = set(_merged_shipping_company_ids(company))
    sibling_ids.add(int(company.id))
    duplicate = next(
        (
            item
            for item in ShippingCompany.query.all()
            if item.id not in sibling_ids
            and _shipping_company_key(item.name) == _shipping_company_key(name)
        ),
        None,
    )
    if duplicate:
        return jsonify({"success": False, "error": "يوجد شركة أخرى بنفس الاسم"}), 400

    opening_balance = _parse_opening_balance(data.get("opening_balance"))
    old_name = company.name
    members = (
        ShippingCompany.query.filter(ShippingCompany.id.in_(sibling_ids))
        .order_by(ShippingCompany.id.asc())
        .all()
    )
    for member in members:
        member.name = name
        # Keep the edited combined opening balance on the representative row only.
        member.opening_balance = opening_balance if member.id == company.id else 0
    db.session.commit()
    try:
        log_activity(
            "update",
            "shipping",
            f"تعديل شركة شحن: {old_name} → {company.name}",
            entity_type="shipping_company",
            entity_id=company.id,
            payload={"name": company.name, "opening_balance": company.opening_balance},
        )
    except Exception:
        pass
    return jsonify({
        "success": True,
        "name": company.name,
        "opening_balance": opening_balance,
    })


# =====================================
# Delete Company
# =====================================
@shipping_bp.route("/delete/<int:id>", methods=["POST"])
def delete_company(id):
    company = ShippingCompany.query.get_or_404(id)
    company_name = company.name

    has_orders = Invoice.query.filter_by(shipping_company_id=id).first()
    if has_orders:
        return jsonify({"error": "company has orders"}), 400

    db.session.delete(company)
    db.session.commit()
    try:
        log_activity(
            "delete",
            "shipping",
            f"حذف شركة شحن: {company_name}",
            entity_type="shipping_company",
            entity_id=id,
        )
    except Exception:
        pass
    return jsonify({"success": True})

# =====================================
# Company Orders
# =====================================
@shipping_bp.route("/orders/<int:id>")
def company_orders(id):
    orders = Invoice.query.filter_by(shipping_company_id=id).all()

    # عرض فقط الطلبات المستحقة الدفع (المتبقي > 0) مع استبعاد الملغاة/المرتجعة
    return jsonify([
        {
            "id": o.id,
            "customer": o.customer.name,
            "phone": o.customer.phone,
            "total": o.total,
            "status": o.status,
            "payment": o.payment_status,
            "paid_amount": int(o.paid_amount or 0),
            "remaining": remaining_amount(o),
        }
        for o in orders 
        if o.payment_status != "مرتجع"
        and o.status not in (CANCELED_STATUSES + RETURN_STATUSES)
        and remaining_amount(o) > 0
    ])

# =====================================
# Settle Order (with history)
# =====================================
@shipping_bp.route("/settle/<int:order_id>", methods=["POST"])
def settle_order(order_id):
    order = Invoice.query.get_or_404(order_id)
    before = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
    data = request.get_json(silent=True) or {}
    ensure_treasury_schema()
    treasury_account_id = resolve_treasury_account_id(data.get("treasury_account_id"))

    amount = remaining_amount(order)
    if amount <= 0:
        if ensure_paid_shipping_order_settled(order, treasury_account_id=treasury_account_id):
            db.session.commit()
            return jsonify({"success": True, "message": "تم تسجيل تسديد شركة الشحن للطلب المسدد مسبقاً"})
        return jsonify({"success": True, "message": "الطلب مسدد مسبقاً"})

    delivery_fee = max(0, int(data.get("delivery_fee") or 0))

    try:
        select_order_stock_branch(order, data.get("branch_id"))
        ensure_stock_for_transition(order, target_payment_status="مسدد")
    except OrderStockError as exc:
        db.session.rollback()
        return jsonify({"success": False, "code": "INSUFFICIENT_STOCK", "error": exc.message, "shortages": exc.shortages}), 409
    prev_eff = _effective_paid_amount_inv(order)
    order.payment_status = "مسدد"
    order.paid_amount = order.total
    tenant_id = getattr(order, "tenant_id", None)
    if getattr(order, "customer", None) is not None:
        tenant_id = getattr(order.customer, "tenant_id", tenant_id)
    apply_manual_delivery_fee_on_payment(order, delivery_fee, tenant_id)
    if delivery_fee <= 0:
        order.paid_amount = order.total

    ensure_paid_shipping_order_settled(order, treasury_account_id=treasury_account_id)

    append_payment_ledger_delta(order.id, _effective_paid_amount_inv(order) - prev_eff)
    sync_delivery_expense_for_invoice(order, treasury_account_id=treasury_account_id)
    db.session.commit()
    log_mutation(
        "update",
        "shipping",
        "invoice",
        order.id,
        before,
        snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
        f"تسديد الطلب #{order.id} من شركة النقل",
    )
    return jsonify({"success": True})


@shipping_bp.route("/collect/<int:id>", methods=["POST"])
def collect_company_balance(id):
    _ensure_shipping_opening_balance_column()
    company = ShippingCompany.query.get_or_404(id)
    data = request.get_json(silent=True) or {}
    ensure_treasury_schema()

    amount = _parse_opening_balance(data.get("amount"))
    opening_balance = int(getattr(company, "opening_balance", 0) or 0)
    if amount <= 0:
        return jsonify({"success": False, "error": "أدخل مبلغ قبض صحيح"}), 400
    if opening_balance <= 0:
        return jsonify({"success": False, "error": "لا يوجد رصيد افتتاحي مستحق على هذه الشركة"}), 400
    if amount > opening_balance:
        return jsonify({
            "success": False,
            "error": f"المبلغ أكبر من الرصيد الافتتاحي المتبقي ({opening_balance:,} د.ع)"
        }), 400

    treasury_account_id = resolve_treasury_account_id(data.get("treasury_account_id"))
    company.opening_balance = opening_balance - amount
    db.session.add(
        ShippingPayment(
            branch_id=company.branch_id,
            shipping_company_id=company.id,
            invoice_id=None,
            amount=amount,
            action="قبض",
            note=(data.get("note") or "قبض من الرصيد الافتتاحي لشركة الشحن").strip(),
            treasury_account_id=treasury_account_id,
        )
    )
    db.session.commit()
    try:
        log_activity(
            "collect",
            "shipping",
            f"قبض من شركة شحن: {company.name} بمبلغ {amount:,} د.ع",
            entity_type="shipping_company",
            entity_id=company.id,
            payload={"amount": amount, "remaining_opening_balance": company.opening_balance},
        )
    except Exception:
        pass
    return jsonify({
        "success": True,
        "remaining_opening_balance": company.opening_balance,
        "message": "تم تسجيل القبض وتحديث الرصيد الافتتاحي"
    })

# =====================================
# Cancel Order (with history)
# =====================================
@shipping_bp.route("/cancel/<int:order_id>", methods=["GET", "POST"])
def cancel_order(order_id):
    order = Invoice.query.get_or_404(order_id)
    before = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
    previous_paid = _effective_paid_amount_inv(order)

    # منع إلغاء طلب مكتمل/مسدد أو مرتجع
    if is_completed(order.status, order.payment_status):
        return jsonify({"success": False, "error": "لا يمكن إلغاء طلب مكتمل/مسدد"}), 400
    if is_returned(order.status, order.payment_status):
        return jsonify({"success": False, "error": "لا يمكن إلغاء طلب مرتجع"}), 400
    if is_canceled(order.status, order.payment_status):
        return jsonify({"success": True, "message": "الطلب ملغي مسبقاً"})

    try:
        process_order_cancel(order)
        append_payment_ledger_delta(
            order.id,
            _effective_paid_amount_inv(order) - previous_paid,
        )
        sync_delivery_expense_for_invoice(order)

        db.session.add(
            ShippingPayment(
                branch_id=order.branch_id,
                shipping_company_id=order.shipping_company_id,
                invoice_id=order.id,
                amount=order.total,
                action="إلغاء"
            )
        )
        db.session.commit()
        log_mutation(
            "update",
            "shipping",
            "invoice",
            order.id,
            before,
            snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
            f"إلغاء الطلب #{order.id} من شركة النقل",
        )
        return jsonify({"success": True})
    except OrderLifecycleError as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": exc.message}), exc.status_code
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# =====================================
# Return Order (with inventory restore)
# =====================================
@shipping_bp.route("/return/<int:order_id>", methods=["GET", "POST"])
def return_order(order_id):
    order = Invoice.query.get_or_404(order_id)
    before = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
    prev_eff = _effective_paid_amount_inv(order)

    data = request.get_json(silent=True) or {}
    scanned_barcode = (data.get("barcode") or request.args.get("barcode") or "").strip()
    if request.method == "GET" and not scanned_barcode:
        return jsonify({"success": False, "error": "يجب مسح باركود الطلب لتأكيد المرتجع"}), 400

    try:
        already_returned, message = process_order_return(
            order,
            scanned_barcode,
            return_branch_id=data.get("return_branch_id"),
        )
        if already_returned:
            return jsonify({"success": True, "message": message})

        db.session.add(
            ShippingPayment(
                branch_id=order.branch_id,
                shipping_company_id=order.shipping_company_id,
                invoice_id=order.id,
                amount=order.total,
                action="ترجيع"
            )
        )
        append_payment_ledger_delta(order.id, _effective_paid_amount_inv(order) - prev_eff)
        sync_delivery_expense_for_invoice(order)
        db.session.commit()
        log_mutation(
            "update",
            "shipping",
            "invoice",
            order.id,
            before,
            snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
            f"ترجيع الطلب #{order.id} من شركة النقل",
        )
        return jsonify({"success": True, "message": message})
    except OrderLifecycleError as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": exc.message}), exc.status_code
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# =====================================
# Shipping History
# =====================================
@shipping_bp.route("/history/<int:id>")
def shipping_history(id):
    logs = ShippingPayment.query.filter_by(
        shipping_company_id=id
    ).order_by(ShippingPayment.created_at.desc()).all()

    return jsonify([
        {
            "invoice": l.invoice_id,
            "amount": l.amount,
            "action": l.action,
            "date": l.created_at.strftime("%Y-%m-%d %H:%M")
        }
        for l in logs
    ])
