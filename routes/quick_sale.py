from __future__ import annotations

from datetime import datetime

from flask import Blueprint, g, jsonify, redirect, render_template, request, session, url_for

from extensions import db
from models.customer import Customer
from models.employee import Employee
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from utils.branch_migration import ensure_branch_schema, get_default_branch
from utils.branch_context import current_branch_id, init_branch_context
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


quick_sale_bp = Blueprint("quick_sale", __name__, url_prefix="/quick-sale")


@quick_sale_bp.before_request
def quick_sale_use_tenant_db():
    if "user_id" not in session:
        return
    tenant_slug = session.get("tenant_slug")
    if tenant_slug:
        g.tenant = tenant_slug
        ensure_product_schema()
        ensure_invoice_schema()
        ensure_customer_blacklist_columns()
        ensure_branch_schema()
        init_branch_context()
        ensure_policy_initialized()


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


def _product_payload(product: Product) -> dict:
    payload = {
        "id": product.id,
        "name": product.name,
        "sku": product.sku or "",
        "barcode": product.barcode or "",
        "price": int(product.sale_price or 0),
        "stock": int(product.quantity or 0),
        "image_url": product.image_url or "",
    }
    payload.update(colors_for_product_dict(product))
    return payload


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
    stock_rows = []
    preferred = current_branch_id() or (get_default_branch().id if get_default_branch() else None)
    for item in items:
        product_id = _safe_int(item.get("product_id"))
        qty = max(1, _safe_int(item.get("qty"), 1))
        if product_id <= 0:
            continue
        product = Product.query.get(product_id)
        if not product or not product.active:
            return jsonify({"success": False, "error": "منتج غير موجود أو غير فعال"}), 400
        variant_color = (item.get("color") or item.get("variant_color") or "").strip()
        if product_has_colors(product) and not variant_color:
            return jsonify({"success": False, "error": f"يجب اختيار لون للمنتج: {product.name}"}), 400
        unit_price = _safe_int(item.get("price"), int(product.sale_price or 0))
        if unit_price <= 0:
            return jsonify({"success": False, "error": f"سعر المنتج {product.name} غير صالح"}), 400
        clean_items.append({
            "product": product,
            "qty": qty,
            "price": unit_price,
            "fulfillment_branch_id": None,
            "variant_color": variant_color or None,
        })
        stock_rows.append({
            "product": product,
            "product_id": product.id,
            "quantity": qty,
            "variant_color": variant_color or None,
        })

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

    stock_check = check_stock_rows(stock_rows, preferred_branch_id=preferred)
    invoice = Invoice(
        customer_id=customer.id,
        customer_name=customer.name,
        employee_id=employee.id if employee else None,
        employee_name=employee.name if employee else None,
        branch_id=preferred,
        total=0,
        paid_amount=0,
        status="تم الطلب" if not stock_check.can_fulfill else "تم التوصيل",
        payment_status="غير مسدد" if not stock_check.can_fulfill else "مسدد",
        note="بيع سريع - مقفل بانتظار توفر المخزون" if not stock_check.can_fulfill else "بيع سريع - تم التسديد والطباعة مباشرة",
        created_at=datetime.utcnow(),
        stock_is_deducted=False,
    )
    db.session.add(invoice)
    db.session.flush()

    total = 0
    for idx, row in enumerate(clean_items):
        product = row["product"]
        qty = int(row["qty"])
        unit_price = int(row["price"])
        line_total = unit_price * qty
        total += line_total
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
        invoice.paid_amount = total
        tenant_id = getattr(customer, "tenant_id", None)
        apply_manual_delivery_fee_on_payment(invoice, delivery_fee, tenant_id)
        if delivery_fee <= 0:
            invoice.paid_amount = total
        append_payment_ledger_delta(invoice.id, int(invoice.paid_amount or 0))
        sync_delivery_expense_for_invoice(invoice)
        ensure_payroll_schema()
        sync_commission_line_for_invoice(invoice)
    else:
        invoice.paid_amount = 0
        if deferred_stock_enabled():
            clear_order_stock_lock(invoice)
        else:
            mark_order_stock_locked(invoice, stock_check.reason_text)

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
