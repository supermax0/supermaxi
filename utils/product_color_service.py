from __future__ import annotations

import json

from extensions import db
from models.product import Product
from models.product_color_variant import ProductColorVariant


class ProductColorError(Exception):
    pass


def _normalize_color(color: str | None) -> str:
    return (color or "").strip()


def product_has_colors(product: Product | None) -> bool:
    if product is None:
        return False
    meta = {}
    raw = (getattr(product, "meta_json", None) or "").strip()
    if raw:
        try:
            meta = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (TypeError, ValueError, json.JSONDecodeError):
            meta = {}
    if meta.get("has_colors"):
        return True
    return ProductColorVariant.query.filter_by(product_id=product.id).count() > 0


def get_product_colors(product_id: int) -> list[dict]:
    rows = (
        ProductColorVariant.query.filter_by(product_id=product_id)
        .order_by(ProductColorVariant.color_name.asc())
        .all()
    )
    return [{"name": r.color_name, "qty": int(r.quantity or 0)} for r in rows]


def get_color_quantity(product_id: int, color_name: str) -> int:
    color = _normalize_color(color_name)
    if not color:
        return 0
    row = ProductColorVariant.query.filter_by(product_id=product_id, color_name=color).first()
    return int(row.quantity or 0) if row else 0


def sync_product_total_from_colors(product_id: int) -> int:
    product = Product.query.get(product_id)
    if not product:
        return 0
    total = (
        db.session.query(db.func.coalesce(db.func.sum(ProductColorVariant.quantity), 0))
        .filter(ProductColorVariant.product_id == product_id)
        .scalar()
    )
    total = int(total or 0)
    if product_has_colors(product):
        product.quantity = total
        product.opening_stock = total
    return total


def _set_has_colors_flag(product: Product, enabled: bool) -> None:
    meta = {}
    raw = (product.meta_json or "").strip()
    if raw:
        try:
            meta = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            meta = {}
    if enabled:
        meta["has_colors"] = True
    else:
        meta.pop("has_colors", None)
    product.meta_json = json.dumps(meta, ensure_ascii=False) if meta else None


def save_product_colors(product_id: int, color_rows: list[tuple[str, int]]) -> list[ProductColorVariant]:
    """Replace color variants for a product. Each row is (color_name, quantity)."""
    product = Product.query.get(product_id)
    if not product:
        raise ProductColorError("المنتج غير موجود")

    cleaned: dict[str, int] = {}
    for name, qty in color_rows:
        color = _normalize_color(name)
        if not color:
            continue
        cleaned[color] = max(0, int(qty or 0))

    existing = {
        v.color_name: v
        for v in ProductColorVariant.query.filter_by(product_id=product_id).all()
    }

    for color, variant in list(existing.items()):
        if color not in cleaned:
            db.session.delete(variant)

    saved: list[ProductColorVariant] = []
    for color, qty in cleaned.items():
        variant = existing.get(color)
        if variant:
            variant.quantity = qty
        else:
            variant = ProductColorVariant(product_id=product_id, color_name=color, quantity=qty)
            db.session.add(variant)
        saved.append(variant)

    if cleaned:
        _set_has_colors_flag(product, True)
        sync_product_total_from_colors(product_id)
    else:
        _set_has_colors_flag(product, False)

    db.session.flush()
    return saved


def ensure_color_variant(product_id: int, color_name: str, *, initial_qty: int = 0) -> ProductColorVariant:
    color = _normalize_color(color_name)
    if not color:
        raise ProductColorError("اسم اللون مطلوب")
    product = Product.query.get(product_id)
    if not product:
        raise ProductColorError("المنتج غير موجود")

    variant = ProductColorVariant.query.filter_by(product_id=product_id, color_name=color).first()
    if not variant:
        variant = ProductColorVariant(
            product_id=product_id,
            color_name=color,
            quantity=max(0, int(initial_qty or 0)),
        )
        db.session.add(variant)
    _set_has_colors_flag(product, True)
    db.session.flush()
    return variant


def validate_color_sale(product_id: int, color_name: str, qty: int) -> tuple[bool, str]:
    product = Product.query.get(product_id)
    if not product:
        return False, "المنتج غير موجود"
    if not product_has_colors(product):
        return True, ""
    color = _normalize_color(color_name)
    if not color:
        return False, f"يجب اختيار لون للمنتج: {product.name}"
    available = get_color_quantity(product_id, color)
    qty = int(qty or 0)
    if qty <= 0:
        return False, "الكمية غير صالحة"
    if available < qty:
        return False, f"مخزون اللون ({color}) غير كافٍ. المتاح: {available}"
    return True, ""


def deduct_color_stock(product_id: int, color_name: str, qty: int) -> ProductColorVariant | None:
    product = Product.query.get(product_id)
    if not product or not product_has_colors(product):
        return None
    color = _normalize_color(color_name)
    if not color:
        raise ProductColorError("اسم اللون مطلوب")
    qty = int(qty or 0)
    if qty <= 0:
        raise ProductColorError("الكمية غير صالحة")

    variant = ProductColorVariant.query.filter_by(product_id=product_id, color_name=color).first()
    if not variant:
        raise ProductColorError(f"اللون ({color}) غير معرّف لهذا المنتج")
    available = int(variant.quantity or 0)
    if available < qty:
        raise ProductColorError(f"مخزون اللون ({color}) غير كافٍ. المتاح: {available}")
    variant.quantity = available - qty
    sync_product_total_from_colors(product_id)
    db.session.flush()
    return variant


def receive_color_stock(product_id: int, color_name: str, qty: int) -> ProductColorVariant:
    qty = int(qty or 0)
    if qty <= 0:
        raise ProductColorError("الكمية يجب أن تكون أكبر من صفر")
    variant = ensure_color_variant(product_id, color_name, initial_qty=0)
    variant.quantity = int(variant.quantity or 0) + qty
    sync_product_total_from_colors(product_id)
    db.session.flush()
    return variant


def restore_color_stock(product_id: int, color_name: str, qty: int) -> ProductColorVariant | None:
    color = _normalize_color(color_name)
    if not color or int(qty or 0) <= 0:
        return None
    return receive_color_stock(product_id, color, int(qty))


def colors_for_product_dict(product: Product) -> dict:
    """Bootstrap/search payload for a product."""
    has_colors = product_has_colors(product)
    colors = get_product_colors(product.id) if has_colors else []
    return {
        "has_colors": has_colors,
        "colors": colors,
    }
