"""Append branch-local colors without replacing existing quantities or prices."""
import json

from sqlalchemy import text

from extensions import db
from models.product_color_variant import ProductColorVariant
from utils.product_color_service import ProductColorError, sync_product_total_from_colors


def local_color_rows(product_id):
    from utils.product_color_media import color_image_map
    from utils.product_options import describe_options
    from models.product import Product
    images = color_image_map(product_id)
    return describe_options(db.session.get(Product, product_id), [{"id": row.id, "name": row.color_name, "qty": int(row.quantity or 0), "image_url": images.get(row.color_name, ""),
             "buy_price": row.buy_price, "sale_price": row.sale_price, "governorate_sale_price": row.governorate_sale_price} for row in
            ProductColorVariant.query.filter_by(product_id=product_id)
            .order_by(ProductColorVariant.color_name).all()])


def lock_color_product(product):
    # FOR UPDATE protects the product on row-locking engines. SQLite needs to
    # acquire its write lock before reading balances; the no-op never changes stock.
    if db.session.get_bind().dialect.name == "sqlite":
        db.session.execute(text("UPDATE product SET quantity=quantity WHERE id=:id"), {"id": product.id})
    db.session.refresh(product)


def append_product_colors(product, raw_names, expected_stock, current_stock):
    try:
        names = json.loads(raw_names)
    except (ValueError, TypeError):
        raise ProductColorError("قائمة الألوان غير صحيحة")
    if not isinstance(names, list) or not names or len(names) > 40:
        raise ProductColorError("أضف من 1 إلى 40 لوناً")
    if any(not isinstance(name, str) or not name.strip() or len(name.strip()) > 80 for name in names):
        raise ProductColorError("اسم اللون يجب أن يكون من 1 إلى 80 حرفاً")
    names = [name.strip() for name in names]
    existing = local_color_rows(product.id)
    keys = [row["name"].strip().casefold() for row in existing] + [name.casefold() for name in names]
    if len(keys) != len(set(keys)):
        raise ProductColorError("هذا اللون مضاف مسبقاً؛ أعد تحميل المنتج")
    if len(keys) > 40:
        raise ProductColorError("الحد الأقصى 40 لوناً للمنتج")
    # Do not assign a stale balance after a concurrent sale. Existing color
    # balances never arrive from the client and are never overwritten here.
    if not existing:
        try:
            valid = int(expected_stock) == current_stock and current_stock >= 0
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ProductColorError("تغيّر المخزون؛ أعد تحميل المنتج قبل إضافة اللون الأول")
    for index, name in enumerate(names):
        db.session.add(ProductColorVariant(
            product_id=product.id, color_name=name,
            quantity=current_stock if not existing and index == 0 else 0,
            buy_price=int(product.buy_price or 0), sale_price=int(product.sale_price or 0),
            governorate_sale_price=getattr(product, "governorate_sale_price", None),
        ))
    meta = json.loads(product.meta_json or "{}")
    if not meta.get("has_colors"):
        meta["has_colors"] = True
        product.meta_json = json.dumps(meta, ensure_ascii=False)
    db.session.flush()
    sync_product_total_from_colors(product.id, branch_id=product.branch_id)
