"""Shared helpers for delivery fees on invoices.

رسوم الشحن تُحفظ داخلياً للتسوية كمصروف عند التسديد.
لا تُضاف إلى إجمالي الفاتورة ولا تُخصم من أسعار المنتجات.
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


def _deductible_product_items(items) -> list:
    result = []
    for item in items:
        if is_shipping_item(item):
            continue
        name = (getattr(item, "product_name", None) or "").strip()
        if name in ("خصم كوبون",):
            continue
        if _safe_int(getattr(item, "total", 0)) <= 0:
            continue
        result.append(item)
    return result


def _deduct_fee_from_product_items(product_items, fee: int) -> int:
    """Reduce product line totals by fee (proportional). Returns applied amount."""
    fee = max(0, _safe_int(fee))
    if fee <= 0 or not product_items:
        return 0

    products_total = sum(_safe_int(i.total) for i in product_items)
    if products_total <= 0:
        return 0

    fee = min(fee, products_total)
    remaining = fee
    for idx, item in enumerate(product_items):
        line_total = _safe_int(item.total)
        if idx == len(product_items) - 1:
            share = remaining
        else:
            share = int(round(fee * (line_total / float(products_total))))
            share = min(max(0, share), remaining, line_total)
        remaining -= share
        new_total = max(0, line_total - share)
        qty = max(1, _safe_int(getattr(item, "quantity", 1), 1))
        item.total = new_total
        item.price = int(round(new_total / qty)) if qty else new_total
    return fee


def add_shipping_line_item(invoice, shipping_fee: int, tenant_id: int | None = None) -> int:
    """
    تسجيل رسوم الشحن داخلياً بدون إضافتها للإجمالي وبدون خصمها من المنتجات.
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
    للفواتير القديمة التي أُضيف فيها الشحن فوق السعر، يُخصم من المنتجات للعرض فقط.
    يُرجع (printable_items, display_total).
    """
    items = list(items or [])
    product_items = []
    legacy_added_fee = 0

    for item in items:
        if is_shipping_item(item):
            total = _safe_int(getattr(item, "total", 0))
            if total > 0:
                legacy_added_fee += total
            continue
        product_items.append(item)

    if legacy_added_fee <= 0:
        printable = [
            SimpleNamespace(
                product_name=getattr(i, "product_name", "") or "",
                quantity=_safe_int(getattr(i, "quantity", 1), 1),
                price=_safe_int(getattr(i, "price", 0)),
                total=_safe_int(getattr(i, "total", 0)),
                product=getattr(i, "product", None),
            )
            for i in product_items
        ]
        display_total = sum(i.total for i in printable)
        return printable, display_total

    # فواتير قديمة: الشحن كان مضافاً — نخصمه من العرض فقط
    products_total = sum(_safe_int(i.total) for i in product_items)
    fee = min(legacy_added_fee, products_total) if products_total > 0 else 0
    remaining = fee
    printable = []
    for idx, item in enumerate(product_items):
        line_total = _safe_int(item.total)
        qty = max(1, _safe_int(getattr(item, "quantity", 1), 1))
        if fee > 0 and products_total > 0:
            if idx == len(product_items) - 1:
                share = remaining
            else:
                share = int(round(fee * (line_total / float(products_total))))
                share = min(max(0, share), remaining, line_total)
            remaining -= share
            new_total = max(0, line_total - share)
        else:
            new_total = line_total
        printable.append(
            SimpleNamespace(
                product_name=getattr(item, "product_name", "") or "",
                quantity=qty,
                price=int(round(new_total / qty)) if qty else new_total,
                total=new_total,
                product=getattr(item, "product", None),
            )
        )
    display_total = sum(i.total for i in printable)
    return printable, display_total
