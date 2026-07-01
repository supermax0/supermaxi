from flask import Blueprint, render_template, request, jsonify
from extensions import db
from models.shipping import ShippingCompany
from models.invoice import Invoice
from models.shipping_payment import ShippingPayment
from models.order_item import OrderItem
from models.product import Product
from datetime import datetime
import secrets

from utils.payment_ledger import append_payment_ledger_delta
from utils.permission_checks import guard_permission
from utils.activity_logger import log_activity
from utils.treasury_helpers import resolve_treasury_account_id, treasury_choices_for_form
from utils.treasury_calculations import assert_sufficient_balance, InsufficientTreasuryBalance
from utils.treasury_schema_guard import ensure_treasury_schema

shipping_bp = Blueprint("shipping", __name__, url_prefix="/shipping")

_SHIPPING_WRITE_ENDPOINTS = {
    "shipping.add_company",
    "shipping.delete_company",
    "shipping.settle_order",
    "shipping.cancel_order",
    "shipping.return_order",
}


@shipping_bp.before_request
def _shipping_permission_guard():
    from flask import session
    if "user_id" not in session:
        return None
    perm = "manage_shipping" if request.endpoint in _SHIPPING_WRITE_ENDPOINTS else "view_shipping"
    return guard_permission(perm)

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

    if payment_status == "مسدد" or status == "مسدد":
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

    companies = ShippingCompany.query.all()
    result = []

    for c in companies:
        orders = Invoice.query.filter_by(shipping_company_id=c.id).all()
        opening_balance = int(getattr(c, "opening_balance", 0) or 0)

        orders_due = sum(
            remaining_amount(o) for o in orders
            if o.payment_status != "مرتجع"
            and o.status not in (CANCELED_STATUSES + RETURN_STATUSES)
        )

        result.append({
            "id": c.id,
            "name": c.name,
            "orders_count": len(orders),
            "opening_balance": opening_balance,
            "orders_due": orders_due,
            "due": opening_balance + orders_due,
            "access_token": c.access_token,
            "public_url": f"/delivery/public/{c.access_token}" if c.access_token else None
        })

    return render_template("shipping.html", companies=result, treasury_choices=treasury_choices_for_form())

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
# Delete Company
# =====================================
@shipping_bp.route("/delete/<int:id>")
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
    data = request.get_json(silent=True) or {}
    ensure_treasury_schema()
    treasury_account_id = resolve_treasury_account_id(data.get("treasury_account_id"))

    amount = int(order.total or 0)
    try:
        assert_sufficient_balance(treasury_account_id, amount)
    except InsufficientTreasuryBalance as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    prev_eff = _effective_paid_amount_inv(order)
    order.payment_status = "مسدد"
    order.paid_amount = order.total

    db.session.add(
        ShippingPayment(
            shipping_company_id=order.shipping_company_id,
            invoice_id=order.id,
            amount=order.total,
            action="تسديد",
            treasury_account_id=treasury_account_id,
        )
    )

    append_payment_ledger_delta(order.id, _effective_paid_amount_inv(order) - prev_eff)
    db.session.commit()
    return jsonify({"success": True})

# =====================================
# Cancel Order (with history)
# =====================================
@shipping_bp.route("/cancel/<int:order_id>", methods=["GET", "POST"])
def cancel_order(order_id):
    order = Invoice.query.get_or_404(order_id)

    # منع إلغاء طلب مكتمل/مسدد أو مرتجع
    if is_completed(order.status, order.payment_status):
        return jsonify({"success": False, "error": "لا يمكن إلغاء طلب مكتمل/مسدد"}), 400
    if is_returned(order.status, order.payment_status):
        return jsonify({"success": False, "error": "لا يمكن إلغاء طلب مرتجع"}), 400
    if is_canceled(order.status, order.payment_status):
        return jsonify({"success": True, "message": "الطلب ملغي مسبقاً"})

    try:
        process_order_cancel(order)

        db.session.add(
            ShippingPayment(
                shipping_company_id=order.shipping_company_id,
                invoice_id=order.id,
                amount=order.total,
                action="إلغاء"
            )
        )
        db.session.commit()
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
    prev_eff = _effective_paid_amount_inv(order)

    data = request.get_json(silent=True) or {}
    scanned_barcode = (data.get("barcode") or request.args.get("barcode") or "").strip()
    if request.method == "GET" and not scanned_barcode:
        return jsonify({"success": False, "error": "يجب مسح باركود الطلب لتأكيد المرتجع"}), 400

    try:
        already_returned, message = process_order_return(order, scanned_barcode)
        if already_returned:
            return jsonify({"success": True, "message": message})

        db.session.add(
            ShippingPayment(
                shipping_company_id=order.shipping_company_id,
                invoice_id=order.id,
                amount=order.total,
                action="ترجيع"
            )
        )
        append_payment_ledger_delta(order.id, _effective_paid_amount_inv(order) - prev_eff)
        db.session.commit()
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
