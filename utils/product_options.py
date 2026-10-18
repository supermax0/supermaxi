"""Optional product attributes over the existing, history-safe variant ledger.

The persisted color_name is an immutable, readable selection key. Existing
orders, transfers and device allocations keep using it; variant ids identify
rows when editing. No quantities are replaced by catalog edits.
"""
import json

from extensions import db
from models.product_color_variant import ProductColorVariant
from utils.product_color_service import ProductColorError


def option_config(product):
    try:
        raw = getattr(product, "meta_json", None)
        meta = json.loads(raw or "{}") if isinstance(raw, (str, type(None))) else raw
    except (ValueError, TypeError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    config = meta.get("product_options")
    if not isinstance(config, dict) or not isinstance(config.get("axes"), list) or not isinstance(config.get("rows"), dict):
        return {"axes": [], "rows": {}}
    return config


def option_description(product, name):
    config = option_config(product)
    data = config.get("rows", {}).get(name)
    if data is None:
        # Legacy colors remain selectable, including copies in other branches.
        from utils.product_color_service import _shared_catalog_product_ids
        from models.product import Product
        for pid in _shared_catalog_product_ids(product.id):
            if pid != product.id:
                sibling = Product.query.execution_options(skip_branch_scope=True).get(pid)
                if sibling:
                    data = option_config(sibling).get("rows", {}).get(name)
                    if data is not None:
                        break
    return data or {"attributes": {"اللون": name}, "active": True}


def describe_options(product, rows):
    for row in rows:
        row.update(option_description(product, row["name"]))
    return rows


def validate_selection(product, name, variant_id=None, *, allow_archived=False):
    """Validate a new transaction without creating an unknown option."""
    from utils.product_color_service import _shared_catalog_product_ids, product_has_colors
    if variant_id is not None:
        if isinstance(variant_id, bool):
            raise ProductColorError("الخيار المختار غير صحيح")
        try:
            row = db.session.get(ProductColorVariant, int(variant_id))
        except (ValueError, TypeError):
            row = None
        if not row or row.product_id not in _shared_catalog_product_ids(product.id):
            raise ProductColorError("الخيار المختار لا يخص هذا المنتج")
        if name and name != row.color_name:
            raise ProductColorError("بيانات الخيار غير متطابقة؛ أعد اختيار المنتج")
        name = row.color_name
    if not product_has_colors(product):
        if name:
            raise ProductColorError("هذا المنتج لا يحتوي على خيارات")
        return ""
    if not name:
        raise ProductColorError(f"اختر خيار المنتج: {product.name}")
    exists = ProductColorVariant.query.filter(
        ProductColorVariant.product_id.in_(_shared_catalog_product_ids(product.id)),
        ProductColorVariant.color_name == name,
    ).first()
    if not exists or (not allow_archived and not option_description(product, name).get("active", True)):
        raise ProductColorError(f"الخيار غير متاح للمنتج: {product.name}")
    return name


def _integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 2_000_000_000:
        raise ProductColorError(f"{label} يجب أن يكون عدداً صحيحاً غير سالب")
    return value


def apply_product_options(product, raw, *, creating=False, current_stock=0, can_edit_price=False):
    from utils.product_color_service import sync_product_total_from_colors
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        raise ProductColorError("بيانات خيارات المنتج غير صحيحة")
    if not isinstance(payload, dict):
        raise ProductColorError("بيانات خيارات المنتج غير صحيحة")
    axes, drafts = payload.get("axes"), payload.get("rows")
    if not isinstance(axes, list) or not 1 <= len(axes) <= 4:
        raise ProductColorError("أضف من صفة واحدة إلى أربع صفات")
    if any(not isinstance(axis, str) or not axis.strip() or len(axis.strip()) > 24 or "|" in axis for axis in axes):
        raise ProductColorError("اسم الصفة يجب أن يكون من 1 إلى 24 حرفاً")
    axes = [axis.strip() for axis in axes]
    if len(set(axis.casefold() for axis in axes)) != len(axes):
        raise ProductColorError("لا تكرر اسم الصفة")
    if not isinstance(drafts, list) or not 1 <= len(drafts) <= 40:
        raise ProductColorError("أضف من خيار واحد إلى 40 خياراً")
    existing = {row.color_name: row for row in ProductColorVariant.query.filter_by(product_id=product.id).with_for_update().all()}
    old_config = option_config(product)
    prepared, names, combinations = [], set(), set()
    for draft in drafts:
        if not isinstance(draft, dict):
            raise ProductColorError("بيانات الخيار غير صحيحة")
        attrs = draft.get("attributes")
        if not isinstance(attrs, dict) or set(attrs) != set(axes):
            raise ProductColorError("أدخل قيمة لكل صفة في الخيار")
        if any(not isinstance(v, str) or not v.strip() or len(v.strip()) > 32 or "|" in v for v in attrs.values()):
            raise ProductColorError("قيمة الصفة يجب أن تكون من 1 إلى 32 حرفاً")
        attrs = {axis: attrs[axis].strip() for axis in axes}
        name = draft.get("name") or " / ".join(f"{axis}: {attrs[axis]}" for axis in axes)
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or "|" in name:
            raise ProductColorError("اسم الخيار طويل أو غير صحيح؛ اختصر قيم الصفات")
        name = name.strip()
        canonical = attrs[axes[0]] if axes == ["اللون"] else " / ".join(f"{axis}: {attrs[axis]}" for axis in axes)
        if (not existing.get(name) or creating) and name != canonical:
            raise ProductColorError("اسم الخيار لا يطابق صفاته؛ أعد إضافة الخيار")
        combination = tuple(attrs[axis].casefold() for axis in axes)
        if name.casefold() in names or combination in combinations:
            raise ProductColorError("هذه التركيبة مضافة مسبقاً")
        names.add(name.casefold())
        combinations.add(combination)
        row = existing.get(name)
        if row and not creating and draft.get("id") != row.id:
            raise ProductColorError("تغيّرت الخيارات؛ أعد تحميل المنتج")
        if not row and draft.get("id") is not None:
            raise ProductColorError("لا يمكن تغيير هوية خيار محفوظ؛ أضف خياراً جديداً")
        old_attrs = old_config.get("rows", {}).get(name, {}).get("attributes")
        if row and old_attrs is not None and (any(attrs.get(k) != v for k, v in old_attrs.items()) or
                any(v != "غير محدد" for k, v in attrs.items() if k not in old_attrs)):
            raise ProductColorError("صفات الخيار المحفوظ ثابتة لحماية الفواتير؛ أضف خياراً جديداً وأوقف القديم")
        qty = _integer(draft.get("qty", 0), "الكمية")
        active = draft.get("active", True)
        if not isinstance(active, bool):
            raise ProductColorError("حالة الخيار غير صحيحة")
        prices = {}
        for key in ("buy_price", "sale_price", "governorate_sale_price"):
            if key not in draft:
                continue
            value = draft[key]
            if value is not None:
                value = _integer(value, "السعر")
            old = getattr(row, key) if row else None
            base = getattr(product, key, None)
            if not creating and not can_edit_price and value != old and (row or value not in (None, base)):
                raise ProductColorError("ليست لديك صلاحية تعديل أسعار الخيارات")
            prices[key] = value
        source = draft.get("source_id")
        if source is not None:
            source = _integer(source, "مصدر توزيع المخزون")
            if row or source not in {v.id for v in existing.values()}:
                raise ProductColorError("اختر خياراً محفوظاً كمصدر توزيع المخزون")
        prepared.append((name, row, attrs, qty, active, prices, source))
    # Omitted rows are never deleted: history and device allocations refer to them.
    if set(existing) - {item[0] for item in prepared}:
        raise ProductColorError("لا تحذف خياراً محفوظاً؛ أوقف عرضه بدلاً من الحذف")
    new_qty = sum(item[3] for item in prepared if not item[1])
    if not existing and not creating:
        if _integer(payload.get("expected_stock"), "المخزون المتوقع") != current_stock or new_qty != current_stock:
            raise ProductColorError("وزّع المخزون الحالي بالكامل على الخيارات؛ أعد التحميل إذا تغيّر الرصيد")
    elif new_qty and not creating:
        if any(item[3] and not item[1] and item[6] is None for item in prepared):
            raise ProductColorError("اختر مصدر توزيع الكمية أو ابدأ بصفر وأضف المخزون بالمشتريات")
        from utils.desktop_stock_reservations import reserved_for_stock
        for source in existing.values():
            moved = sum(item[3] for item in prepared if item[6] == source.id)
            if moved > int(source.quantity or 0) - reserved_for_stock(0, source.id):
                raise ProductColorError("كمية التوزيع أكبر من المخزون المتاح؛ أعد تحميل المنتج")
            source.quantity -= moved
    config_rows = {}
    for name, row, attrs, qty, active, prices, source in prepared:
        if row is None:
            row = ProductColorVariant(product_id=product.id, color_name=name, quantity=qty)
            db.session.add(row)
        for key, value in prices.items():
            setattr(row, key, value)
        config_rows[name] = {"attributes": attrs, "active": active}
    meta = json.loads(product.meta_json or "{}")
    meta["product_options"] = {"axes": axes, "rows": config_rows}
    meta["has_colors"] = True
    product.meta_json = json.dumps(meta, ensure_ascii=False)
    db.session.flush()
    sync_product_total_from_colors(product.id, branch_id=product.branch_id)
