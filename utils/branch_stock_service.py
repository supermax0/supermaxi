"""Central branch-scoped inventory operations."""
from __future__ import annotations

from typing import Iterable

from extensions import db
from models.branch import Branch, BranchStock
from models.product import Product


class BranchStockError(Exception):
    pass


def _branch_product_id(branch_id: int, product_id: int) -> int:
    """Resolve a shared-catalog product to its local copy in ``branch_id``.

    Independent companies deliberately keep separate products.  Legacy shared
    companies, however, may already contain those copies from an earlier
    migration; using a main-branch ID against the Karrada branch then returns
    a false zero.  Resolve only in shared mode and never create a copy while
    merely reading stock.
    """
    try:
        product = Product.query.execution_options(skip_branch_scope=True).get(int(product_id))
        group_id = str(getattr(product, "catalog_group_id", "") or "").strip() if product else ""
        if not group_id:
            return int(product_id)
        local = (
            Product.query.execution_options(skip_branch_scope=True)
            .filter_by(catalog_group_id=group_id, branch_id=int(branch_id), active=True)
            .first()
        )
        return int(local.id) if local else int(product_id)
    except Exception:
        return int(product_id)


def _catalog_product_ids(product_id: int) -> list[int]:
    """All local copies belonging to one shared catalog product."""
    try:
        product = Product.query.execution_options(skip_branch_scope=True).get(int(product_id))
        group_id = str(getattr(product, "catalog_group_id", "") or "").strip() if product else ""
        if not group_id:
            return [int(product_id)]
        from utils.branch_mode import independent_branches_enabled

        if independent_branches_enabled():
            return [int(product_id)]
        return [
            int(row[0])
            for row in (
                Product.query.execution_options(skip_branch_scope=True)
                .filter(Product.catalog_group_id == group_id)
                .with_entities(Product.id)
                .all()
            )
        ] or [int(product_id)]
    except Exception:
        return [int(product_id)]


def _legacy_product_stock(branch_id: int, product_id: int) -> tuple[int, int]:
    """Return legacy Product stock only for the product's owning branch."""
    try:
        product = Product.query.execution_options(skip_branch_scope=True).get(
            int(product_id)
        )
        if not product:
            return 0, 0
        product_branch_id = getattr(product, "branch_id", None)
        if product_branch_id is None:
            default_branch = Branch.query.filter_by(is_default=True).first()
            product_branch_id = getattr(default_branch, "id", None)
        if not product_branch_id or int(product_branch_id) != int(branch_id):
            return 0, 0
        return int(product.quantity or 0), int(product.opening_stock or 0)
    except Exception:
        return 0, 0


def _audit_change(
    *,
    product_id: int,
    branch_id: int,
    before: int,
    after: int,
    operation: str,
    audit_context=None,
) -> None:
    try:
        from utils.inventory_audit_trail import record_stock_mutation

        record_stock_mutation(
            product_id=product_id,
            branch_id=branch_id,
            before_quantity=before,
            after_quantity=after,
            operation=operation,
            audit_context=audit_context,
        )
    except Exception:
        pass


def get_or_create_branch_stock(branch_id: int, product_id: int) -> BranchStock:
    product_id = _branch_product_id(branch_id, product_id)
    bs = BranchStock.query.filter_by(branch_id=branch_id, product_id=product_id).first()
    if bs:
        return bs
    product = Product.query.execution_options(skip_branch_scope=True).get(product_id)
    legacy_quantity, legacy_opening_stock = _legacy_product_stock(branch_id, product_id)
    bs = BranchStock(
        branch_id=branch_id,
        product_id=product_id,
        quantity=legacy_quantity,
        opening_stock=legacy_opening_stock,
        low_stock_threshold=(product.low_stock_threshold if product else 5) or 5,
    )
    db.session.add(bs)
    db.session.flush()
    return bs


def get_branch_stock(branch_id: int, product_id: int) -> int:
    resolved_product_id = _branch_product_id(branch_id, product_id)
    # A color-managed product has a detailed stock ledger.  That ledger is
    # authoritative; returning an older aggregate BranchStock value is what
    # made different screens show 4 and 5 for the same item.
    try:
        from models.product_color_variant import ProductColorVariant
        from utils.product_color_service import product_has_colors

        resolved_product = Product.query.execution_options(skip_branch_scope=True).get(
            resolved_product_id
        )
        if resolved_product is not None and product_has_colors(resolved_product):
            color_total = (
                db.session.query(db.func.coalesce(db.func.sum(ProductColorVariant.quantity), 0))
                .filter(ProductColorVariant.product_id == resolved_product_id)
                .scalar()
            )
            return int(color_total or 0)
    except Exception:
        pass
    bs = BranchStock.query.filter_by(
        branch_id=branch_id,
        product_id=resolved_product_id,
    ).first()
    if bs:
        return int(bs.quantity or 0)

    # Older products can still have their quantity on Product without a
    # corresponding BranchStock row.  The inventory page already falls back
    # to that value, but order preparation used to return a misleading zero.
    # Only use the fallback for the product's owning/default branch; never
    # copy one branch's quantity into every other branch.
    legacy_quantity, _ = _legacy_product_stock(branch_id, resolved_product_id)
    return legacy_quantity


def get_total_stock(product_id: int) -> int:
    product_ids = _catalog_product_ids(product_id)
    try:
        from models.product_color_variant import ProductColorVariant

        has_color_rows = (
            ProductColorVariant.query.filter(ProductColorVariant.product_id.in_(product_ids)).first()
            is not None
        )
        if has_color_rows:
            total = (
                db.session.query(db.func.coalesce(db.func.sum(ProductColorVariant.quantity), 0))
                .filter(ProductColorVariant.product_id.in_(product_ids))
                .scalar()
            )
            return int(total or 0)
    except Exception:
        pass
    total = (
        db.session.query(db.func.coalesce(db.func.sum(BranchStock.quantity), 0))
        .filter(BranchStock.product_id.in_(product_ids))
        .scalar()
    )
    return int(total or 0)


def sync_product_total(product_id: int) -> int:
    product = Product.query.get(product_id)
    if not product:
        return 0
    total = get_total_stock(product_id)
    # Shared-mode catalog copies represent one sellable product.  Keeping only
    # the touched local copy in sync leaves the representative row showing a
    # stale zero (or an old doubled value) in selectors and reports.
    product_ids = _catalog_product_ids(product_id)
    from utils.desktop_stock_reservations import allow_stock_mirror
    with allow_stock_mirror(product_ids, total):
        Product.query.execution_options(skip_branch_scope=True).filter(
            Product.id.in_(product_ids)
        ).update({Product.quantity: total}, synchronize_session=False)
    return total


def set_branch_stock(branch_id: int, product_id: int, quantity: int, *, sync_product: bool = True, audit_context=None) -> BranchStock:
    product_id = _branch_product_id(branch_id, product_id)
    if quantity < 0:
        raise BranchStockError("الكمية لا يمكن أن تكون سالبة")
    bs = get_or_create_branch_stock(branch_id, product_id)
    before = int(bs.quantity or 0)
    bs.quantity = int(quantity)
    _audit_change(
        product_id=product_id,
        branch_id=branch_id,
        before=before,
        after=int(quantity),
        operation="set_stock",
        audit_context=audit_context,
    )
    if sync_product:
        sync_product_total(product_id)
    return bs


def receive_stock(branch_id: int, product_id: int, qty: int, *, sync_product: bool = True, audit_context=None) -> BranchStock:
    product_id = _branch_product_id(branch_id, product_id)
    qty = int(qty or 0)
    if qty <= 0:
        raise BranchStockError("كمية الاستلام يجب أن تكون أكبر من صفر")
    bs = get_or_create_branch_stock(branch_id, product_id)
    before = int(bs.quantity or 0)
    db.session.query(BranchStock).filter(BranchStock.id == bs.id).update(
        {BranchStock.quantity: BranchStock.quantity + qty}, synchronize_session=False
    )
    db.session.expire(bs)
    _audit_change(
        product_id=product_id,
        branch_id=branch_id,
        before=before,
        after=before + qty,
        operation="receive_stock",
        audit_context=audit_context,
    )
    if sync_product:
        sync_product_total(product_id)
    return bs


def deduct_stock(branch_id: int, product_id: int, qty: int, *, sync_product: bool = True, audit_context=None) -> BranchStock:
    product_id = _branch_product_id(branch_id, product_id)
    qty = int(qty or 0)
    if qty <= 0:
        raise BranchStockError("كمية الخصم يجب أن تكون أكبر من صفر")
    bs = get_or_create_branch_stock(branch_id, product_id)
    # Lock and re-read the row before checking the balance.  This also makes
    # newly-created BranchStock rows reliable in the same transaction (the
    # old bulk UPDATE could report zero affected rows on SQLite after schema
    # guards/savepoints had run).
    bs = (
        BranchStock.query
        .filter(BranchStock.id == bs.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    before = int(bs.quantity or 0)
    from utils.desktop_stock_reservations import reserved_for_stock
    available = max(0, before - reserved_for_stock(bs.id))
    if available < qty:
        branch = Branch.query.get(branch_id)
        branch_name = branch.name if branch else str(branch_id)
        product = Product.query.get(product_id)
        product_name = (product.name if product else None) or f"#{product_id}"
        raise BranchStockError(
            f"المخزون غير كافٍ للمنتج «{product_name}» في {branch_name}. المتاح: {available}"
        )
    updated = db.session.query(BranchStock).filter(
        BranchStock.id == bs.id, BranchStock.quantity >= qty,
    ).update({BranchStock.quantity: BranchStock.quantity - qty}, synchronize_session=False)
    db.session.expire(bs)
    if updated != 1:
        raise BranchStockError("تغيّر المخزون أثناء التسجيل؛ الكمية المطلوبة لم تعد متوفرة")
    before = int(bs.quantity or 0) + qty
    db.session.flush()
    _audit_change(
        product_id=product_id,
        branch_id=branch_id,
        before=before,
        after=before - qty,
        operation="deduct_stock",
        audit_context=audit_context,
    )
    if sync_product:
        sync_product_total(product_id)
    return bs


def validate_branch_sale(branch_id: int, product_id: int, qty: int) -> tuple[bool, str]:
    qty = int(qty or 0)
    if qty <= 0:
        return False, "الكمية غير صالحة"
    available = get_available_branch_stock(branch_id, product_id)
    if available < qty:
        product = Product.query.get(product_id)
        product_name = (product.name if product else None) or f"#{product_id}"
        return False, f"المخزون غير كافٍ للمنتج «{product_name}». المتاح: {available}"
    return True, ""


def get_available_branch_stock(branch_id: int, product_id: int) -> int:
    """Sellable quantity excluding device escrow; reports keep physical totals."""
    from utils.desktop_stock_reservations import reserved_for_stock
    resolved = _branch_product_id(branch_id, product_id)
    stock = BranchStock.query.filter_by(branch_id=branch_id, product_id=resolved).first()
    held = reserved_for_stock(stock.id) if stock else 0
    return max(0, get_branch_stock(branch_id, product_id) - held)


def adjust_branch_stock(branch_id: int, product_id: int, adjustment: int, *, sync_product: bool = True, audit_context=None) -> BranchStock:
    product_id = _branch_product_id(branch_id, product_id)
    bs = get_or_create_branch_stock(branch_id, product_id)
    new_qty = int(bs.quantity or 0) + int(adjustment or 0)
    if new_qty < 0:
        raise BranchStockError(f"المخزون لا يمكن أن يكون سالباً. الحالي: {bs.quantity or 0}")
    bs.quantity = new_qty
    _audit_change(
        product_id=product_id,
        branch_id=branch_id,
        before=int(bs.quantity or 0) - int(adjustment or 0),
        after=new_qty,
        operation="adjust_stock",
        audit_context=audit_context,
    )
    if sync_product:
        sync_product_total(product_id)
    return bs


def set_opening_branch_stock(
    branch_id: int,
    product_id: int,
    opening_stock: int,
    *,
    sync_product: bool = True,
    audit_context=None,
) -> BranchStock:
    product_id = _branch_product_id(branch_id, product_id)
    opening_stock = int(opening_stock or 0)
    bs = get_or_create_branch_stock(branch_id, product_id)
    before = int(bs.quantity or 0)
    bs.opening_stock = opening_stock
    bs.quantity = opening_stock
    _audit_change(
        product_id=product_id,
        branch_id=branch_id,
        before=before,
        after=opening_stock,
        operation="set_opening_stock",
        audit_context=audit_context,
    )
    if sync_product:
        sync_product_total(product_id)
    return bs


def transfer_deduct(from_branch_id: int, lines: Iterable[tuple[int, int]], *, sync_product: bool = True) -> None:
    for product_id, qty in lines:
        deduct_stock(from_branch_id, product_id, qty, sync_product=sync_product)
    if sync_product:
        product_ids = {pid for pid, _ in lines}
        for pid in product_ids:
            sync_product_total(pid)


def transfer_receive(to_branch_id: int, lines: Iterable[tuple[int, int]], *, sync_product: bool = True) -> None:
    for product_id, qty in lines:
        receive_stock(to_branch_id, product_id, qty, sync_product=sync_product)
    if sync_product:
        product_ids = {pid for pid, _ in lines}
        for pid in product_ids:
            sync_product_total(pid)


def branch_stock_map(branch_id: int | None = None) -> dict[int, int]:
    q = BranchStock.query
    if branch_id:
        q = q.filter_by(branch_id=branch_id)
    rows = q.all()
    if not rows:
        return {}

    # In shared-branch companies, the same catalog item can have one local
    # Product row per branch.  The transfer form is allowed to display any
    # of those rows, so expose the branch quantity under every member ID of
    # the shared catalog family.  Previously the map was keyed only by the
    # BranchStock product_id; selecting another local copy consequently
    # showed a false zero even though the branch had stock.
    try:
        from utils.branch_mode import independent_branches_enabled

        shared_mode = not independent_branches_enabled()
    except Exception:
        shared_mode = False
    all_products = Product.query.execution_options(skip_branch_scope=True).all()

    def overlay_color_totals(result: dict[int, int]) -> dict[int, int]:
        try:
            from models.product_color_variant import ProductColorVariant

            color_rows = ProductColorVariant.query.all()
            totals_by_product: dict[int, int] = {}
            product_lookup = {int(product.id): product for product in all_products}
            for color_row in color_rows:
                pid = int(color_row.product_id)
                totals_by_product[pid] = totals_by_product.get(pid, 0) + int(color_row.quantity or 0)
            if branch_id:
                for candidate in all_products:
                    local_id = _branch_product_id(int(branch_id), int(candidate.id))
                    local_product = product_lookup.get(int(local_id))
                    if local_product is not None and getattr(local_product, "branch_id", None):
                        if int(local_product.branch_id) != int(branch_id):
                            continue
                    if local_id in totals_by_product:
                        result[int(candidate.id)] = totals_by_product[local_id]
                return result

            family_color_totals: dict[tuple[str, str], int] = {}
            for pid, total in totals_by_product.items():
                product = product_lookup.get(pid)
                if not product:
                    continue
                group = str(getattr(product, "catalog_group_id", "") or "").strip()
                key = ("group", group) if group else ("id", str(pid))
                family_color_totals[key] = family_color_totals.get(key, 0) + total
            for candidate in all_products:
                group = str(getattr(candidate, "catalog_group_id", "") or "").strip()
                key = ("group", group) if group else ("id", str(candidate.id))
                if key in family_color_totals:
                    result[int(candidate.id)] = family_color_totals[key]
        except Exception:
            pass
        return result

    if not shared_mode:
        if branch_id:
            return overlay_color_totals({r.product_id: int(r.quantity or 0) for r in rows})
        totals: dict[int, int] = {}
        for row in rows:
            totals[row.product_id] = totals.get(row.product_id, 0) + int(row.quantity or 0)
        return overlay_color_totals(totals)

    product_by_id = {int(product.id): product for product in all_products}

    def family_key(product_id: int) -> tuple[str, str]:
        product = product_by_id.get(int(product_id))
        if not product:
            return ("id", str(product_id))
        group_id = str(getattr(product, "catalog_group_id", "") or "").strip()
        if group_id:
            return ("group", group_id)
        barcode = str(getattr(product, "barcode", "") or "").strip()
        if barcode:
            return ("barcode", barcode)
        sku = str(getattr(product, "sku", "") or "").strip()
        return ("sku", sku) if sku else ("id", str(product_id))

    family_totals: dict[tuple[str, str], int] = {}
    for row in rows:
        key = family_key(row.product_id)
        family_totals[key] = family_totals.get(key, 0) + int(row.quantity or 0)

    # Include all known local copies, not just the copy that owns the stock
    # row, so the browser can look up the selected product ID correctly.
    result: dict[int, int] = {}
    for product in all_products:
        result[int(product.id)] = family_totals.get(family_key(product.id), 0)
    for row in rows:
        result.setdefault(int(row.product_id), family_totals.get(family_key(row.product_id), 0))
    return overlay_color_totals(result)
