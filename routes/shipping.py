from flask import Blueprint, render_template, request, jsonify
from extensions import db
from models.shipping import ShippingCompany
from models.invoice import Invoice
from models.shipping_payment import ShippingPayment
from models.order_item import OrderItem
from models.product import Product
from datetime import datetime
import secrets

shipping_bp = Blueprint("shipping", __name__, url_prefix="/shipping")

# حالات مساعدة لتوحيد المنطق مع الدفع الجزئي
RETURN_STATUSES = ["مرتجع", "راجع", "راجعة"]
CANCELED_STATUSES = ["ملغي"]
from utils.order_status import is_canceled, is_returned, is_completed
from utils.cash_calculations import _effective_paid_amount as _effective_paid_amount_inv
from utils.payment_ledger import append_payment_ledger_delta


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

    companies = ShippingCompany.query.all()
    result = []

    for c in companies:
        orders = Invoice.query.filter_by(shipping_company_id=c.id).all()

        # المستحقات = الطلبات المستحقة الدفع فقط
        # تصحيح محاسبي: دعم الدفع الجزئي (المستحق = المتبقي)
        # استبعاد: الملغاة والمرتجعة
        due = sum(
            remaining_amount(o) for o in orders
            if o.payment_status != "مرتجع"
            and o.status not in (CANCELED_STATUSES + RETURN_STATUSES)
        )

        result.append({
            "id": c.id,
            "name": c.name,
            "orders_count": len(orders),
            "due": due,
            "access_token": c.access_token,
            "public_url": f"/delivery/public/{c.access_token}" if c.access_token else None
        })

    return render_template("shipping.html", companies=result)

# =====================================
# Add Shipping Company
# =====================================
@shipping_bp.route("/add", methods=["POST"])
def add_company():
    data = request.json
    name = data.get("name")

    if not name:
        return jsonify({"error": "name required"}), 400

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
        access_token=access_token,
        username=username,
        password=password
    )
    db.session.add(company)
    db.session.commit()
    
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

    has_orders = Invoice.query.filter_by(shipping_company_id=id).first()
    if has_orders:
        return jsonify({"error": "company has orders"}), 400

    db.session.delete(company)
    db.session.commit()
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
@shipping_bp.route("/settle/<int:order_id>")
def settle_order(order_id):
    order = Invoice.query.get_or_404(order_id)

    prev_eff = _effective_paid_amount_inv(order)
    order.payment_status = "مسدد"
    order.paid_amount = order.total

    db.session.add(
        ShippingPayment(
            shipping_company_id=order.shipping_company_id,
            invoice_id=order.id,
            amount=order.total,
            action="تسديد"
        )
    )

    append_payment_ledger_delta(order.id, _effective_paid_amount_inv(order) - prev_eff)
    db.session.commit()
    return jsonify({"success": True})

# =====================================
# Cancel Order (with history)
# =====================================
@shipping_bp.route("/cancel/<int:order_id>")
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
        # استرجاع الكمية للمخزون (مرة واحدة فقط)
        items = OrderItem.query.filter_by(invoice_id=order.id).all()
        for item in items:
            product = Product.query.get(item.product_id)
            if product:
                product.quantity += int(item.quantity or 0)

        order.status = "ملغي"
        order.payment_status = "ملغي"

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
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# =====================================
# Return Order (with inventory restore)
# =====================================
@shipping_bp.route("/return/<int:order_id>")
def return_order(order_id):
    order = Invoice.query.get_or_404(order_id)
    prev_eff = _effective_paid_amount_inv(order)

    # التحقق من أن الطلب لم يكن مرتجعاً من قبل
    was_returned = is_returned(order.status, order.payment_status)
    if is_canceled(order.status, order.payment_status):
        return jsonify({"success": False, "error": "لا يمكن ترجيع طلب ملغي"}), 400
    if was_returned:
        return jsonify({"success": True, "message": "الطلب مرتجع مسبقاً"})
    
    # تغيير حالة الطلب إلى "راجع"
    order.status = "راجع"
    order.payment_status = "مرتجع"
    order.paid_amount = 0

    # إرجاع الكميات للمخزون فقط إذا لم يكن الطلب مرتجعاً من قبل
    try:
        items = OrderItem.query.filter_by(invoice_id=order.id).all()
        for item in items:
            product = Product.query.get(item.product_id)
            if product:
                product.quantity += int(item.quantity or 0)
    
        # إضافة سجل في تاريخ الشحن
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
        return jsonify({"success": True, "message": "تم ترجيع الطلب وإرجاع الكمية للمخزون"})
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
