"""Shared helpers for delivery fee line items on invoices."""

from __future__ import annotations

import json

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


def add_shipping_line_item(invoice, shipping_fee: int, tenant_id: int | None = None) -> int:
    fee = max(0, _safe_int(shipping_fee, 0))
    if fee <= 0 or invoice is None:
        return 0
    shipping_product = get_or_create_shipping_product(tenant_id)
    db.session.add(
        OrderItem(
            invoice_id=invoice.id,
            product_id=shipping_product.id,
            product_name=SHIPPING_PRODUCT_NAME,
            quantity=1,
            price=fee,
            cost=0,
            total=fee,
        )
    )
    return fee


def get_shipping_fee_from_invoice(invoice) -> int:
    if invoice is None:
        return 0
    items = getattr(invoice, "order_items", None) or []
    for item in items:
        product = getattr(item, "product", None)
        barcode = getattr(product, "barcode", None) if product else None
        name = (getattr(item, "product_name", None) or "").strip()
        if barcode == SHIPPING_BARCODE or name == SHIPPING_PRODUCT_NAME:
            return max(0, _safe_int(getattr(item, "total", 0), 0))
    return 0
