from __future__ import annotations

import json

from extensions import db
from models.product import Product
from models.product_color_variant import ProductColorVariant


class ProductColorError(Exception):
    pass


def _normalize_color(color: str | None) -> str:
    return (color or "").strip()


def _shared_catalog_product_ids(product_id: int) -> list[int]:
    """Return local copies of a product when the company uses shared branches."""
    try:
        from utils.branch_mode import independent_branches_enabled

        if independent_branches_enabled():
            return [int(product_id)]
        product = Product.query.execution_options(skip_branch_scope=True).get(int(product_id))
        if not product:
            return [int(product_id)]
        group_id = str(getattr(product, "catalog_group_id", "") or "").strip()
        barcode = str(getattr(product, "barcode", "") or "").strip()
        sku = str(getattr(product, "sku", "") or "").strip()
        identity_filters = []
        if group_id:
            identity_filters.append(Product.catalog_group_id == group_id)
        # Some old shared records were created before catalog_group_id was
        # propagated.  Barcode/SKU is the safe compatibility identity for
        # those copies and prevents a real color balance from appearing as 0.
        if barcode:
            identity_filters.append(Product.barcode == barcode)
        if sku:
            identity_filters.append(Product.sku == sku)
        if not identity_filters:
            return [int(product_id)]
        ids = [
            int(row[0])
            for row in (
                Product.query.execution_options(skip_branch_scope=True)
                .filter(db.or_(*identity_filters))
                .with_entities(Product.id)
                .all()
            )
        ]
        return ids or [int(product_id)]
    except Exception:
        return [int(product_id)]


def _safe_price(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _parse_color_row_extended(row) -> tuple[str, int, int | None, int | None, int | None]:
    if isinstance(row, dict):
        name = row.get("name") or row.get("color_name") or ""
        qty = row.get("qty", row.get("quantity", 0))
        buy = row.get("buy_price", row.get("buy"))
        sale = row.get("sale_price", row.get("sale"))
        gov = row.get("governorate_sale_price", row.get("gov_sale"))
        return (
            _normalize_color(name),
            max(0, int(qty or 0)),
            _safe_price(buy),
            _safe_price(sale),
            _safe_price(gov),
        )
    if isinstance(row, (list, tuple)):
        name = row[0] if len(row) > 0 else ""
        qty = row[1] if len(row) > 1 else 0
        buy = row[2] if len(row) > 2 else None
        sale = row[3] if len(row) > 3 else None
        gov = row[4] if len(row) > 4 else None
        return (
            _normalize_color(str(name)),
            max(0, int(qty or 0)),
            _safe_price(buy),
            _safe_price(sale),
            _safe_price(gov),
        )
    return "", 0, None, None, None


def _parse_color_row(row) -> tuple[str, int, int | None, int | None]:
    """Backward-compatible public parser used by older callers and tests."""
    name, qty, buy, sale, _governorate = _parse_color_row_extended(row)
    return name, qty, buy, sale


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
    from utils.card_batch import current

    batch = current()
    if batch and int(product.id) in batch.get("colors", {}):
        return batch["colors"][int(product.id)]
    product_ids = _shared_catalog_product_ids(product.id)
    return (
        ProductColorVariant.query
        .filter(ProductColorVariant.product_id.in_(product_ids))
        .count()
        > 0
    )


def effective_color_buy_price(product: Product | None, color_name: str | None = None, *, variant: ProductColorVariant | None = None) -> int:
    product_buy = int(getattr(product, "buy_price", 0) or 0) if product else 0
    row = variant
    if row is None and product is not None and color_name:
        color = _normalize_color(color_name)
        if color:
            row = ProductColorVariant.query.filter_by(product_id=product.id, color_name=color).first()
    if row is not None and getattr(row, "buy_price", None) is not None:
        return int(row.buy_price or 0)
    return product_buy


def effective_color_sale_price(product: Product | None, color_name: str | None = None, *, variant: ProductColorVariant | None = None) -> int:
    product_sale = int(getattr(product, "sale_price", 0) or 0) if product else 0
    row = variant
    if row is None and product is not None and color_name:
        color = _normalize_color(color_name)
        if color:
            row = ProductColorVariant.query.filter_by(product_id=product.id, color_name=color).first()
    if row is not None and getattr(row, "sale_price", None) is not None:
        return int(row.sale_price or 0)
    return product_sale


def effective_color_governorate_sale_price(
    product: Product | None,
    color_name: str | None = None,
    *,
    variant: ProductColorVariant | None = None,
) -> int | None:
    """Governorate sell price for a color; falls back to product-level governorate price."""
    product_gov = None
    if product is not None:
        raw = getattr(product, "governorate_sale_price", None)
        if raw is not None and raw != "":
            try:
                product_gov = int(raw)
            except (TypeError, ValueError):
                product_gov = None
            if product_gov is not None and product_gov <= 0:
                product_gov = None
    row = variant
    if row is None and product is not None and color_name:
        color = _normalize_color(color_name)
        if color:
            row = ProductColorVariant.query.filter_by(product_id=product.id, color_name=color).first()
    if row is not None and getattr(row, "governorate_sale_price", None) is not None:
        try:
            value = int(row.governorate_sale_price)
        except (TypeError, ValueError):
            value = None
        if value is not None and value > 0:
            return value
    return product_gov


def get_product_colors(product_id: int) -> list[dict]:
    from utils.product_color_media import color_image_map
    images = color_image_map(product_id)
    product = Product.query.get(product_id)
    product_ids = _shared_catalog_product_ids(product_id)
    rows = (
        ProductColorVariant.query.filter(ProductColorVariant.product_id.in_(product_ids))
        .order_by(ProductColorVariant.color_name.asc())
        .all()
    )
    grouped: dict[str, dict] = {}
    for r in rows:
        name = _normalize_color(r.color_name)
        if not name:
            continue
        item = grouped.setdefault(name, {
            "id": r.id,
            "name": name,
            "qty": 0,
            "buy_price": None,
            "sale_price": None,
            "governorate_sale_price": None,
            "buy_price_set": False,
            "sale_price_set": False,
            "governorate_sale_price_set": False,
        })
        item["qty"] += int(r.quantity or 0)
        if r.buy_price is not None and not item["buy_price_set"]:
            item["buy_price"] = int(r.buy_price)
            item["buy_price_set"] = True
        if r.sale_price is not None and not item["sale_price_set"]:
            item["sale_price"] = int(r.sale_price)
            item["sale_price_set"] = True
        if getattr(r, "governorate_sale_price", None) is not None and not item["governorate_sale_price_set"]:
            item["governorate_sale_price"] = int(r.governorate_sale_price)
            item["governorate_sale_price_set"] = True
    from utils.desktop_stock_reservations import DesktopStockAllocation, reservation_tables_exist
    held_by_name = {}
    if rows and reservation_tables_exist():
        held_by_name = dict(db.session.query(ProductColorVariant.color_name, db.func.sum(
            DesktopStockAllocation.quantity - DesktopStockAllocation.consumed - DesktopStockAllocation.returned))
            .join(DesktopStockAllocation, DesktopStockAllocation.variant_id == ProductColorVariant.id)
            .filter(ProductColorVariant.product_id.in_(product_ids))
            .group_by(ProductColorVariant.color_name).all())
    result = []
    for item in sorted(grouped.values(), key=lambda row: row["name"]):
        if item["buy_price"] is None:
            item["buy_price"] = effective_color_buy_price(product, color_name=item["name"])
        if item["sale_price"] is None:
            item["sale_price"] = effective_color_sale_price(product, color_name=item["name"])
        if item["governorate_sale_price"] is None:
            item["governorate_sale_price"] = effective_color_governorate_sale_price(
                product, color_name=item["name"]
            )
        item["image_url"] = images.get(item["name"], "")
        item["available_qty"] = max(0, item["qty"] - int(held_by_name.get(item["name"]) or 0))
        result.append(item)
    from utils.product_options import describe_options
    return describe_options(product, result)


def colors_quantity_total(colors: list[dict] | None) -> int:
    """Total on-hand quantity represented by color payload rows."""
    total = 0
    for color in colors or []:
        if not isinstance(color, dict):
            continue
        try:
            total += max(0, int(color.get("qty", color.get("quantity", 0)) or 0))
        except (TypeError, ValueError):
            continue
    return total


def color_stock_total(product: Product | None) -> int | None:
    """Return color-stock total when a product is color-managed."""
    if product is None or not product_has_colors(product):
        return None
    return colors_quantity_total(get_product_colors(product.id))


def get_color_quantity(product_id: int, color_name: str) -> int:
    color = _normalize_color(color_name)
    if not color:
        return 0
    return int(
        db.session.query(db.func.coalesce(db.func.sum(ProductColorVariant.quantity), 0))
        .filter(
            ProductColorVariant.product_id.in_(_shared_catalog_product_ids(product_id)),
            ProductColorVariant.color_name == color,
        )
        .scalar()
        or 0
    )


def get_available_color_quantity(product_id: int, color_name: str) -> int:
    """Color balance available for new sales after subtracting device grants."""
    from utils.desktop_stock_reservations import DesktopStockAllocation, reservation_tables_exist
    physical = get_color_quantity(product_id, color_name)
    if not reservation_tables_exist():
        return physical
    variants = db.session.query(ProductColorVariant.id).filter(
        ProductColorVariant.product_id.in_(_shared_catalog_product_ids(product_id)),
        ProductColorVariant.color_name == _normalize_color(color_name))
    held = db.session.query(db.func.coalesce(db.func.sum(
        DesktopStockAllocation.quantity - DesktopStockAllocation.consumed - DesktopStockAllocation.returned), 0)
    ).filter(DesktopStockAllocation.variant_id.in_(variants)).scalar()
    return max(0, physical - int(held or 0))


def sync_product_total_from_colors(product_id: int, *, branch_id: int | None = None) -> int:
    """Synchronize aggregate stock from the exact product's color rows."""
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
        from utils.desktop_stock_reservations import allow_stock_mirror
        with allow_stock_mirror([product_id], total):
            product.quantity = total
        stock_branch_id = int(branch_id or getattr(product, "branch_id", 0) or 0)
        if stock_branch_id:
            from utils.branch_stock_service import set_branch_stock

            set_branch_stock(
                stock_branch_id,
                product_id,
                total,
                audit_context={
                    "source_type": "color_stock_sync",
                    "source_id": product_id,
                    "reason": "مزامنة الرصيد الإجمالي مع أرصدة الألوان",
                },
            )
    return total


def get_branch_product_colors(product_id: int, branch_id: int) -> list[dict]:
    """Return color balances for the local product copy of one branch."""
    from utils.branch_stock_service import _branch_product_id

    local_product_id = int(_branch_product_id(int(branch_id), int(product_id)))
    product = Product.query.execution_options(skip_branch_scope=True).get(local_product_id)
    # If a shared catalogue has no local copy for this branch, _branch_product_id
    # falls back to the representative product.  Do not repeat that one color
    # balance under every branch.
    if product is not None and getattr(product, "branch_id", None):
        if int(product.branch_id) != int(branch_id):
            return []
    rows = (
        ProductColorVariant.query.filter_by(product_id=local_product_id)
        .order_by(ProductColorVariant.color_name.asc())
        .all()
    )
    return [
        {
            "name": _normalize_color(row.color_name),
            "qty": int(row.quantity or 0),
            "buy_price": effective_color_buy_price(product, variant=row),
            "sale_price": effective_color_sale_price(product, variant=row),
            "governorate_sale_price": effective_color_governorate_sale_price(product, variant=row),
        }
        for row in rows
        if _normalize_color(row.color_name)
    ]


def adjust_color_stock(
    product_id: int,
    color_name: str,
    adjustment: int,
    *,
    branch_id: int | None = None,
) -> tuple[int, int, int]:
    """Adjust one color and return (before, after, new branch total)."""
    color = _normalize_color(color_name)
    if not color:
        raise ProductColorError("يجب اختيار اللون عند تعديل مخزون منتج ملوّن")
    local_product_id = int(product_id)
    if branch_id:
        from utils.branch_stock_service import _branch_product_id

        local_product_id = int(_branch_product_id(int(branch_id), int(product_id)))
    variant = ProductColorVariant.query.filter_by(
        product_id=local_product_id,
        color_name=color,
    ).with_for_update().first()
    if not variant:
        raise ProductColorError(f"اللون ({color}) غير معرّف لهذا المنتج في الفرع المختار")
    before = int(variant.quantity or 0)
    after = before + int(adjustment or 0)
    if after < 0:
        raise ProductColorError(f"مخزون اللون لا يمكن أن يكون سالباً. الحالي: {before}")
    variant.quantity = after
    total = (
        sync_product_total_from_colors(local_product_id, branch_id=branch_id)
        if branch_id
        else sync_product_total_from_colors(local_product_id)
    )
    db.session.flush()
    return before, after, total


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


def save_product_colors(product_id: int, color_rows: list) -> list[ProductColorVariant]:
    """Replace color variants for a product.

    Each row may be (name, qty), (name, qty, buy_price, sale_price), or a dict.
    """
    product = Product.query.get(product_id)
    if not product:
        raise ProductColorError("المنتج غير موجود")

    cleaned: dict[str, tuple[int, int | None, int | None, int | None]] = {}
    for row in color_rows:
        color, qty, buy, sale, gov = _parse_color_row_extended(row)
        if not color:
            continue
        cleaned[color] = (qty, buy, sale, gov)

    existing = {
        v.color_name: v
        for v in ProductColorVariant.query.filter_by(product_id=product_id).all()
    }

    for color, variant in list(existing.items()):
        if color not in cleaned:
            db.session.delete(variant)

    saved: list[ProductColorVariant] = []
    default_buy = int(product.buy_price or 0)
    default_sale = int(product.sale_price or 0)
    default_gov = getattr(product, "governorate_sale_price", None)
    try:
        default_gov = int(default_gov) if default_gov is not None else None
    except (TypeError, ValueError):
        default_gov = None
    if default_gov is not None and default_gov <= 0:
        default_gov = None
    for color, (qty, buy, sale, gov) in cleaned.items():
        variant = existing.get(color)
        if variant:
            variant.quantity = qty
            if buy is not None:
                variant.buy_price = buy
            elif variant.buy_price is None:
                variant.buy_price = default_buy
            if sale is not None:
                variant.sale_price = sale
            elif variant.sale_price is None:
                variant.sale_price = default_sale
            if gov is not None:
                variant.governorate_sale_price = gov
            elif getattr(variant, "governorate_sale_price", None) is None and default_gov is not None:
                variant.governorate_sale_price = default_gov
        else:
            variant = ProductColorVariant(
                product_id=product_id,
                color_name=color,
                quantity=qty,
                buy_price=default_buy if buy is None else buy,
                sale_price=default_sale if sale is None else sale,
                governorate_sale_price=default_gov if gov is None else gov,
            )
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

    # Always own a row on the requested product.  Reusing a sibling catalog
    # copy caused transfers to keep crediting the source branch color balance.
    variant = ProductColorVariant.query.filter_by(
        product_id=int(product_id),
        color_name=color,
    ).first()
    if not variant:
        sibling = (
            ProductColorVariant.query.filter(
                ProductColorVariant.product_id.in_(_shared_catalog_product_ids(product_id)),
                ProductColorVariant.color_name == color,
            )
            .order_by(ProductColorVariant.quantity.desc())
            .first()
        )
        buy = int(product.buy_price or 0)
        sale = int(product.sale_price or 0)
        gov = getattr(product, "governorate_sale_price", None)
        if sibling is not None:
            if sibling.buy_price is not None:
                buy = int(sibling.buy_price or 0)
            if sibling.sale_price is not None:
                sale = int(sibling.sale_price or 0)
            if getattr(sibling, "governorate_sale_price", None) is not None:
                gov = sibling.governorate_sale_price
        variant = ProductColorVariant(
            product_id=int(product_id),
            color_name=color,
            quantity=max(0, int(initial_qty or 0)),
            buy_price=buy,
            sale_price=sale,
            governorate_sale_price=gov,
        )
        db.session.add(variant)
    _set_has_colors_flag(product, True)
    db.session.flush()
    return variant


def update_color_buy_price(product_id: int, color_name: str, buy_price: int) -> ProductColorVariant | None:
    color = _normalize_color(color_name)
    if not color:
        return None
    variant = ensure_color_variant(product_id, color)
    variant.buy_price = max(0, int(buy_price or 0))
    db.session.flush()
    return variant


def update_color_sale_price(product_id: int, color_name: str, sale_price: int) -> ProductColorVariant | None:
    color = _normalize_color(color_name)
    if not color:
        return None
    variant = ensure_color_variant(product_id, color)
    variant.sale_price = max(0, int(sale_price or 0))
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


def deduct_color_stock(
    product_id: int,
    color_name: str,
    qty: int,
    *,
    branch_id: int | None = None,
) -> ProductColorVariant | None:
    product = Product.query.get(product_id)
    if not product or not product_has_colors(product):
        return None
    color = _normalize_color(color_name)
    if not color:
        raise ProductColorError("اسم اللون مطلوب")
    qty = int(qty or 0)
    if qty <= 0:
        raise ProductColorError("الكمية غير صالحة")

    local_product_id = int(product_id)
    if branch_id:
        from utils.branch_stock_service import _branch_product_id

        local_product_id = int(_branch_product_id(int(branch_id), int(product_id)))
    variant = ProductColorVariant.query.filter_by(product_id=local_product_id, color_name=color).first()
    if not variant:
        raise ProductColorError(f"اللون ({color}) غير معرّف لهذا المنتج")
    from utils.desktop_stock_reservations import reserved_for_stock
    available = max(0, int(variant.quantity or 0) - reserved_for_stock(0, variant.id))
    if available < qty:
        raise ProductColorError(f"مخزون اللون ({color}) المتاح غير كافٍ. المتاح: {available}")
    updated = (
        db.session.query(ProductColorVariant)
        .filter(ProductColorVariant.id == variant.id, ProductColorVariant.quantity >= qty)
        .update(
            {ProductColorVariant.quantity: ProductColorVariant.quantity - qty},
            synchronize_session=False,
        )
    )
    if updated != 1:
        db.session.expire(variant)
        available = int(variant.quantity or 0)
        raise ProductColorError(f"مخزون اللون ({color}) غير كافٍ. المتاح: {available}")
    db.session.expire(variant)
    if branch_id:
        sync_product_total_from_colors(local_product_id, branch_id=branch_id)
    else:
        sync_product_total_from_colors(local_product_id)
    db.session.flush()
    return variant


def receive_color_stock(
    product_id: int,
    color_name: str,
    qty: int,
    *,
    branch_id: int | None = None,
) -> ProductColorVariant:
    qty = int(qty or 0)
    if qty <= 0:
        raise ProductColorError("الكمية يجب أن تكون أكبر من صفر")
    color = _normalize_color(color_name)
    # Credit the explicit product only.  Shared-catalog "highest qty" lookup
    # used to put transferred color stock back onto the source branch copy.
    local_product_id = int(product_id)
    if branch_id:
        from utils.branch_stock_service import _branch_product_id

        local_product_id = int(_branch_product_id(int(branch_id), int(product_id)))
    variant = ensure_color_variant(local_product_id, color, initial_qty=0)
    db.session.query(ProductColorVariant).filter(ProductColorVariant.id == variant.id).update(
        {ProductColorVariant.quantity: ProductColorVariant.quantity + qty},
        synchronize_session=False,
    )
    db.session.expire(variant)
    if branch_id:
        sync_product_total_from_colors(local_product_id, branch_id=branch_id)
    else:
        sync_product_total_from_colors(local_product_id)
    db.session.flush()
    return variant


def restore_color_stock(
    product_id: int,
    color_name: str,
    qty: int,
    *,
    branch_id: int | None = None,
) -> ProductColorVariant | None:
    color = _normalize_color(color_name)
    if not color or int(qty or 0) <= 0:
        return None
    return receive_color_stock(product_id, color, int(qty), branch_id=branch_id)


def colors_for_product_dict(product: Product) -> dict:
    """Bootstrap/search payload for a product."""
    from utils.product_region_pricing import region_pricing_payload

    has_colors = product_has_colors(product)
    colors = [row for row in get_product_colors(product.id) if row.get("active", True)] if has_colors else []
    payload = {
        "has_colors": has_colors,
        "colors": colors,
    }
    from utils.product_options import option_config
    payload["option_axes"] = option_config(product)["axes"]
    payload.update(region_pricing_payload(product))
    return payload
