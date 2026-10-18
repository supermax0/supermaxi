"""Read authoritative on-hand balances; never subtract sale/device reservations."""
import json

from sqlalchemy import func, inspect

from extensions import db
from models.branch import Branch, BranchStock
from models.inventory_audit import InventoryQuantityAudit
from models.product import Product
from models.product_color_variant import ProductColorVariant
from models.stock_movement import StockMovement
from utils.branch_mode import independent_branches_enabled
from utils.branch_stock_service import get_branch_stock
from utils.product_color_service import product_has_colors
from .common import AuditError, fingerprint, integer, visible_branches


def locations(kind):
    branches = Branch.query.filter(Branch.id.in_(visible_branches()), Branch.is_active.is_(True)).all()
    if kind == "branch":
        return [{"key": f"branch:{row.id}", "branch_id": row.id, "warehouse_id": None,
                 "name": row.name, "branch_name": row.name} for row in branches]
    if kind != "warehouse":
        raise AuditError("اختر مصدر مخزون صحيحاً")
    if not inspect(db.session.connection()).has_table("warehouse"):
        return []
    from modules.wholesale.models.warehouse import Warehouse
    return [{"key": f"warehouse:{row.id}", "branch_id": row.branch_id, "warehouse_id": row.id,
             "name": row.name, "branch_name": next(b.name for b in branches if b.id == row.branch_id)}
            for row in Warehouse.query.filter(Warehouse.branch_id.in_([b.id for b in branches]),
                Warehouse.is_active.is_(True), Warehouse.deleted_at.is_(None)).all()]


def scope_locations(kind, keys):
    if not isinstance(keys, list) or not keys or len(keys) > 100 or any(not isinstance(k, str) for k in keys):
        raise AuditError("اختر موقعاً واحداً على الأقل، وبحد أقصى 100 موقع")
    if len(keys) != len(set(keys)):
        raise AuditError("الموقع مكرر في نطاق الجلسة")
    allowed = {row["key"]: row for row in locations(kind)}
    if any(key not in allowed for key in keys):
        raise AuditError("الموقع غير موجود أو خارج الفروع المسموحة", "forbidden", 403)
    return [allowed[key] for key in keys]


def product_identity(product):
    # A barcode/SKU match alone does not prove that two independent catalogs are identical.
    return str(product.catalog_group_id or f"product:{product.id}")


def planned_products(location, kind):
    products = Product.query.execution_options(skip_branch_scope=True).filter(Product.active.is_(True)).order_by(Product.id).all()
    if kind == "warehouse":
        from modules.wholesale.models.warehouse import WarehouseStock
        stocked_ids = {row.product_id for row in WarehouseStock.query.filter_by(warehouse_id=location["warehouse_id"])}
        return [(p, []) for p in products if p.id in stocked_ids]
    default = Branch.query.filter_by(is_default=True).first()
    branch_id = location["branch_id"]
    if independent_branches_enabled():
        products = [p for p in products if (p.branch_id or (default.id if default else None)) == branch_id]
    else:
        grouped = {}
        for product in products:
            key = product_identity(product)
            old = grouped.get(key)
            if old is None or (product.branch_id == branch_id and old.branch_id != branch_id):
                grouped[key] = product
        products = list(grouped.values())
    result = []
    for product in products:
        if product_has_colors(product):
            # Variants belong to the local copy, never duplicate another branch's colors.
            if product.branch_id and product.branch_id != branch_id:
                continue
            variants = ProductColorVariant.query.filter_by(product_id=product.id).order_by(ProductColorVariant.id).all()
            if not variants:
                continue
        else:
            variants = []
        result.append((product, variants))
    return result


def stock_state(line, *, lock=False):
    product = Product.query.execution_options(skip_branch_scope=True).filter_by(id=line.product_id)
    product = (product.with_for_update() if lock else product).populate_existing().first()
    if not product or not product.active:
        raise AuditError("الصنف لم يعد متاحاً؛ راجع الجلسة ولا ترحّل رصيداً قديماً", "source_changed", 409)
    branch = db.session.get(Branch, line.branch_id)
    if not branch or not branch.is_active or product_identity(product) != line.catalog_key:
        raise AuditError("تغيّر الفرع أو هوية الكتالوج؛ راجع نطاق الجرد", "source_changed", 409)
    if not line.warehouse_id and independent_branches_enabled() and product.branch_id and product.branch_id != line.branch_id:
        raise AuditError("الصنف لم يعد في موقع الجرد؛ راجع نقله قبل العد", "source_changed", 409)
    identity = {"product": product.id, "catalog": product.catalog_group_id, "branch": product.branch_id,
                "meta": product.meta_json, "active": product.active, "price": product.buy_price}
    if line.warehouse_id:
        from modules.wholesale.models.warehouse import Warehouse, WarehouseStock, WarehouseMovement
        warehouse = db.session.get(Warehouse, line.warehouse_id)
        if not warehouse or not warehouse.is_active or warehouse.deleted_at or warehouse.branch_id != line.branch_id:
            raise AuditError("المخزن تغيّر؛ راجع نطاق الجلسة", "source_changed", 409)
        query = WarehouseStock.query.filter_by(warehouse_id=line.warehouse_id, product_id=line.product_id)
        row = (query.with_for_update() if lock else query).populate_existing().first()
        quantity = int(row.quantity or 0) if row else 0
        marker = db.session.query(func.max(WarehouseMovement.id)).filter_by(
            warehouse_id=line.warehouse_id, product_id=line.product_id).scalar() or 0
        identity.update(quantity=quantity, movement=marker, transit=int(row.in_transit_quantity or 0) if row else 0)
        return quantity, fingerprint(identity)
    if line.variant_id:
        query = ProductColorVariant.query.filter_by(id=line.variant_id, product_id=line.product_id,
                                                    color_name=line.variant_name)
        row = (query.with_for_update() if lock else query).populate_existing().first()
        if not row or (product.branch_id and product.branch_id != line.branch_id):
            raise AuditError("خيار الصنف أو موقعه تغيّر؛ أعد العد", "source_changed", 409)
        quantity = int(row.quantity or 0)
        identity.update(variant=row.id, variant_price=row.buy_price, variant_name=row.color_name)
    else:
        if product_has_colors(product):
            raise AuditError("صار الصنف يدار بخيارات؛ ابدأ جلسة جديدة حسب الخيارات", "source_changed", 409)
        query = BranchStock.query.filter_by(branch_id=line.branch_id, product_id=line.product_id)
        if lock:
            query.with_for_update().populate_existing().first()
        quantity = get_branch_stock(line.branch_id, line.product_id)
    movement = db.session.query(func.max(StockMovement.id)).execution_options(skip_branch_scope=True).filter(
        StockMovement.product_id == line.product_id, StockMovement.branch_id == line.branch_id).scalar() or 0
    audit = db.session.query(func.max(InventoryQuantityAudit.id)).filter(
        InventoryQuantityAudit.product_id == line.product_id, InventoryQuantityAudit.branch_id == line.branch_id).scalar() or 0
    identity.update(quantity=quantity, movement=movement, audit=audit)
    return quantity, fingerprint(identity)


def product_data(line, *, show_cost=False, saved=True):
    if saved and line.product_snapshot_json != "{}":
        result = json.loads(line.product_snapshot_json)
        product = Product.query.execution_options(skip_branch_scope=True).filter_by(id=line.product_id).first()
        if product:
            result.update(current_barcode=product.barcode or "", current_sku=product.sku or "")
        if not show_cost:
            result.pop("unit_cost", None)
        return result
    product = Product.query.execution_options(skip_branch_scope=True).filter_by(id=line.product_id).first()
    if not product:
        raise AuditError("الصنف غير موجود", "not_found", 404)
    try:
        meta = json.loads(product.meta_json or "{}")
    except (ValueError, TypeError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    image = product.image_url or ""
    if line.variant_name:
        from utils.product_color_media import color_image_map
        image = color_image_map(product.id).get(line.variant_name) or image
    result = {"id": product.id, "name": product.name, "sku": product.sku or "", "barcode": product.barcode or "",
              "image_url": image, "model": str(meta.get("model") or ""),
              "current_barcode": product.barcode or "", "current_sku": product.sku or "",
              "variant_id": line.variant_id, "variant_name": line.variant_name, "unit": str(meta.get("unit") or "قطعة")}
    if show_cost:
        variant = db.session.get(ProductColorVariant, line.variant_id) if line.variant_id else None
        result["unit_cost"] = int(variant.buy_price if variant and variant.buy_price is not None else product.buy_price or 0)
    return result
