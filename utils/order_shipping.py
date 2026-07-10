"""Shared helpers for delivery fees on invoices.

أجرة التوصيل لا تُحسب ولا تُخصم تلقائياً عند إنشاء الطلب.
تُدخل يدوياً عند التسديد فقط، ثم تُحفظ داخلياً وتُسجّل كمصروف.
لا تُنقص إيراد الفاتورة ولا تُغيّر أسعار بنود المنتجات.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from extensions import db
from models.order_item import OrderItem
from models.product import Product

SHIPPING_BARCODE = "__SF_SHIPPING__"
SHIPPING_PRODUCT_NAME = "رسوم الشحن"


def _safe_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_or_create_shipping_product(tenant_id: int | None = None) -> Product:
    product = Product.query.filter_by(barcode=SHIPPING_BARCODE, tenant_id=tenant_id).first()
    if product:
        return product
    product = Product(
        name=SHIPPING_PRODUCT_NAME,
        barcode=SHIPPING_BARCODE,
        buy_price=0,
        sale_price=0,
        quantity=0,
        active=False,
        tenant_id=tenant_id,
        description="منتج نظامي لرسوم التوصيل — لا يظهر في الكتالوج",
        meta_json=json.dumps({"system_service": True, "delivery_fee_service": True}, ensure_ascii=False),
    )
    db.session.add(product)
    db.session.flush()
    return product


def order_item_display_name(item) -> str:
    """اسم المنتج للعرض: الاسم الحالي من المخزون إن وُجد، وإلا اللقطة المحفوظة."""
    product = getattr(item, "product", None)
    if product is not None:
        live = (getattr(product, "name", None) or "").strip()
        if live:
            name = live
        else:
            name = (getattr(item, "product_name", None) or "").strip() or "منتج"
    else:
        name = (getattr(item, "product_name", None) or "").strip() or "منتج"
    color = (getattr(item, "variant_color", None) or "").strip()
    if color:
        return f"{name} — {color}"
    return name


def sync_product_name_to_order_items(product_id: int, new_name: str) -> int:
    """تحديث اسم المنتج في كل بنود الطلبات المرتبطة."""
    name = (new_name or "").strip()
    if not product_id or not name:
        return 0
    return OrderItem.query.filter_by(product_id=product_id).update(
        {OrderItem.product_name: name},
        synchronize_session=False,
    )


def is_shipping_item(item) -> bool:
    if item is None:
        return False
    name = (getattr(item, "product_name", None) or "").strip()
    if name == SHIPPING_PRODUCT_NAME:
        return True
    product = getattr(item, "product", None)
    barcode = getattr(product, "barcode", None) if product else None
    return barcode == SHIPPING_BARCODE


def _shipping_fee_from_item(item) -> int:
    """Legacy lines store fee in total; new lines store fee in cost with total=0."""
    total = _safe_int(getattr(item, "total", 0))
    if total > 0:
        return total
    return max(0, _safe_int(getattr(item, "cost", 0)))


def get_shipping_fee_from_invoice(invoice) -> int:
    if invoice is None:
        return 0
    items = getattr(invoice, "order_items", None)
    if items is None:
        items = OrderItem.query.filter_by(invoice_id=invoice.id).all()
    for item in items:
        if is_shipping_item(item):
            return _shipping_fee_from_item(item)
    return 0


def net_total_after_shipping(total: int, shipping_fee: int) -> int:
    return max(0, _safe_int(total, 0) - max(0, _safe_int(shipping_fee, 0)))


def _invoice_items(invoice) -> list:
    if invoice is None:
        return []
    items = getattr(invoice, "order_items", None)
    if items is None:
        items = getattr(invoice, "items", None)
    if items is not None:
        try:
            return list(items)
        except TypeError:
            pass
    if getattr(invoice, "id", None) is None:
        return []
    return OrderItem.query.filter_by(invoice_id=invoice.id).all()


def non_shipping_items_total(invoice) -> int:
    return sum(
        _safe_int(getattr(item, "total", 0))
        for item in _invoice_items(invoice)
        if not is_shipping_item(item)
    )


def is_shipping_fee_deducted_from_invoice(invoice) -> bool:
    fee = get_shipping_fee_from_invoice(invoice)
    if fee <= 0 or invoice is None:
        return False
    invoice_total = _safe_int(getattr(invoice, "total", 0))
    return invoice_total == net_total_after_shipping(non_shipping_items_total(invoice), fee)


def apply_manual_delivery_fee_on_payment(invoice, delivery_fee: int, tenant_id: int | None = None) -> int:
    """يُستدعى يدوياً عند التسديد فقط: يحفظ الأجرة كبند داخلي بدون إنقاص إيراد الفاتورة."""
    fee = max(0, _safe_int(delivery_fee, 0))
    if fee <= 0 or invoice is None:
        return 0
    return add_shipping_line_item(invoice, fee, tenant_id)


def apply_shipping_fee_on_paid_invoice(invoice) -> int:
    """Legacy helper: deduct a saved delivery fee from invoice.total for old repair flows only."""
    if invoice is None:
        return 0

    fee = get_shipping_fee_from_invoice(invoice)
    if fee <= 0 or is_shipping_fee_deducted_from_invoice(invoice):
        return 0

    gross_total = non_shipping_items_total(invoice)
    if gross_total <= 0:
        return 0

    net_total = net_total_after_shipping(gross_total, fee)
    old_total = _safe_int(getattr(invoice, "total", 0))
    invoice.total = net_total

    payment_status = (getattr(invoice, "payment_status", None) or "").strip()
    status = (getattr(invoice, "status", None) or "").strip()
    if payment_status == "\u0645\u0633\u062f\u062f" or status == "\u0645\u0633\u062f\u062f":
        invoice.paid_amount = net_total

    return max(0, old_total - net_total)


def add_shipping_line_item(invoice, shipping_fee: int, tenant_id: int | None = None) -> int:
    """
    تسجيل رسوم الشحن داخلياً بدون إضافتها للإجمالي وبدون خصمها من المنتجات أو الإيراد.
    يُرجع مبلغ رسوم الشحن المحفوظ للتسوية عند الدفع.
    """
    fee = max(0, _safe_int(shipping_fee, 0))
    if fee <= 0 or invoice is None:
        return 0

    items = OrderItem.query.filter_by(invoice_id=invoice.id).all()
    # إزالة أي بند شحن سابق لنفس الفاتورة
    for item in list(items):
        if is_shipping_item(item):
            db.session.delete(item)
    db.session.flush()

    shipping_product = get_or_create_shipping_product(tenant_id)
    db.session.add(
        OrderItem(
            invoice_id=invoice.id,
            product_id=shipping_product.id,
            product_name=SHIPPING_PRODUCT_NAME,
            quantity=1,
            price=0,
            cost=fee,
            total=0,
        )
    )
    db.session.flush()
    return fee


def prepare_invoice_items_for_print(items):
    """
    عناصر الطباعة: بدون بند الشحن.
    الشحن لا يُضاف ولا يُخصم من المنتجات في الفاتورة المطبوعة.
    يُرجع (printable_items, display_total).
    """
    items = list(items or [])
    printable = [
        SimpleNamespace(
            product_name=order_item_display_name(i),
            quantity=_safe_int(getattr(i, "quantity", 1), 1),
            price=_safe_int(getattr(i, "price", 0)),
            total=_safe_int(getattr(i, "total", 0)),
            product=getattr(i, "product", None),
        )
        for i in items
        if not is_shipping_item(i)
    ]
    display_total = sum(i.total for i in printable)
    return printable, display_total


def _coupon_discount_from_items(items) -> int:
    coupon_discount = 0
    for item in items or []:
        if is_shipping_item(item):
            continue
        name = (getattr(item, "product_name", None) or "").strip()
        line_total = _safe_int(getattr(item, "total", 0))
        if name == "خصم كوبون" or line_total < 0:
            coupon_discount += abs(line_total)
    return coupon_discount


def invoice_display_amounts(order, raw_items, print_total: int) -> dict:
    """Compute subtotal/discount/net totals for invoice rendering."""
    print_total = max(0, _safe_int(print_total, 0))
    pos_discount = max(0, _safe_int(getattr(order, "discount_amount", 0), 0))
    coupon_discount = _coupon_discount_from_items(raw_items)

    if pos_discount > 0:
        total_before_discount = print_total
        discount_amount = pos_discount + coupon_discount
        net_total = max(0, total_before_discount - pos_discount)
    else:
        discount_amount = coupon_discount
        net_total = max(0, _safe_int(getattr(order, "total", 0), 0) or print_total)
        total_before_discount = net_total + coupon_discount

    return {
        "total_before_discount": total_before_discount,
        "discount_amount": discount_amount,
        "total": net_total,
    }


def invoice_print_amounts(order, total: int) -> dict:
    """مبالغ الفاتورة للطباعة: الإجمالي، المدفوع، والمتبقي."""
    total = int(total or 0)
    payment_status = (getattr(order, "payment_status", None) or "").strip()
    paid = min(max(int(getattr(order, "paid_amount", None) or 0), 0), total)

    if payment_status == "مسدد":
        paid = total
        due = total
        is_partial = False
    elif payment_status == "جزئي":
        due = max(total - paid, 0)
        is_partial = paid > 0 and due > 0
    else:
        due = max(total - paid, 0) if paid > 0 else total
        is_partial = paid > 0 and due > 0

    return {
        "total": total,
        "paid_amount": paid,
        "due": due,
        "is_partial": is_partial,
    }
