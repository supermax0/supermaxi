from __future__ import annotations

from datetime import datetime

from flask import Blueprint, g, jsonify, redirect, render_template, request, session, url_for

from extensions import db
from models.customer import Customer
from models.employee import Employee
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from utils.inventory_movements import validate_sale_quantity
from utils.payment_ledger import append_payment_ledger_delta
from utils.product_schema_guard import ensure_customer_blacklist_columns, ensure_product_schema


quick_sale_bp = Blueprint("quick_sale", __name__, url_prefix="/quick-sale")


@quick_sale_bp.before_request
def quick_sale_use_tenant_db():
    if "user_id" not in session:
        return
    tenant_slug = session.get("tenant_slug")
    if tenant_slug:
        g.tenant = tenant_slug
        ensure_product_schema()
        ensure_customer_blacklist_columns()


def _current_employee():
    if "user_id" not in session:
        return None
    return Employee.query.get(session["user_id"])


def _can_use_quick_sale(employee: Employee | None) -> bool:
    if not employee or not employee.is_active:
        return False
    if employee.role in {"admin", "cashier"}:
        return True
    try:
        return employee.has_permission("use_pos")
    except Exception:
        return False


def _safe_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _product_payload(product: Product) -> dict:
    return {
        "id": product.id,
        "name": product.name,
        "sku": product.sku or "",
        "barcode": product.barcode or "",
        "price": int(product.sale_price or 0),
        "stock": int(product.quantity or 0),
        "image_url": product.image_url or "",
    }


@quick_sale_bp.route("/")
def page():
    employee = _current_employee()
    if not _can_use_quick_sale(employee):
        return redirect("/pos")
    return render_template("quick_sale.html")


@quick_sale_bp.route("/products")
def products():
    employee = _current_employee()
    if not _can_use_quick_sale(employee):
        return jsonify({"success": False, "error": "غير مصرح"}), 403

    q = (request.args.get("q") or "").strip()
    query = Product.query.filter(Product.active == True)  # noqa: E712
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
    rows = query.order_by(Product.name.asc()).limit(24).all()
    return jsonify({"success": True, "products": [_product_payload(p) for p in rows]})


@quick_sale_bp.route("/execute", methods=["POST"])
def execute():
    employee = _current_employee()
    if not _can_use_quick_sale(employee):
        return jsonify({"success": False, "error": "غير مصرح"}), 403

    data = request.get_json(force=True) or {}
    customer_data = data.get("customer") or {}
    phone = str(customer_data.get("phone") or "").strip()
    city = str(customer_data.get("city") or "بغداد").strip() or "بغداد"
    name = str(customer_data.get("name") or "").strip() or "زبون سريع"
    items = data.get("items") or []

    if not phone:
        return jsonify({"success": False, "error": "رقم الهاتف مطلوب"}), 400
    if not items:
        return jsonify({"success": False, "error": "أضف منتج واحد على الأقل"}), 400

    clean_items = []
    for item in items:
        product_id = _safe_int(item.get("product_id"))
        qty = max(1, _safe_int(item.get("qty"), 1))
        if product_id <= 0:
            continue
        product = Product.query.get(product_id)
        if not product or not product.active:
            return jsonify({"success": False, "error": "منتج غير موجود أو غير فعال"}), 400
        validation = validate_sale_quantity(product.id, qty)
        if not validation.get("valid"):
            return jsonify({"success": False, "error": validation.get("message") or "الكمية غير متوفرة"}), 400
        clean_items.append({"product": product, "qty": qty})

    if not clean_items:
        return jsonify({"success": False, "error": "لا توجد منتجات صالحة"}), 400

    customer = Customer.query.filter_by(phone=phone).first()
    if customer:
        customer.name = name or customer.name
        customer.city = city
    else:
        customer = Customer(
            name=name,
            phone=phone,
            city=city,
            tenant_id=getattr(clean_items[0]["product"], "tenant_id", None),
        )
        db.session.add(customer)
        db.session.flush()

    invoice = Invoice(
        customer_id=customer.id,
        customer_name=customer.name,
        employee_id=employee.id if employee else None,
        employee_name=employee.name if employee else None,
        total=0,
        paid_amount=0,
        status="تم الطلب",
        payment_status="مسدد",
        note="بيع سريع - تم التسديد والطباعة مباشرة",
        created_at=datetime.utcnow(),
    )
    db.session.add(invoice)
    db.session.flush()

    total = 0
    for row in clean_items:
        product = row["product"]
        qty = int(row["qty"])
        line_total = int(product.sale_price or 0) * qty
        total += line_total
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=qty,
                price=int(product.sale_price or 0),
                cost=int(product.buy_price or 0),
                total=line_total,
            )
        )
        product.quantity = int(product.quantity or 0) - qty

    invoice.total = total
    invoice.paid_amount = total
    append_payment_ledger_delta(invoice.id, total)

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 500

    return jsonify(
        {
            "success": True,
            "invoice_id": invoice.id,
            "total": total,
            "print_url": url_for("orders.invoice_page", order_id=invoice.id),
        }
    )
