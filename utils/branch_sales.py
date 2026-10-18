"""Cross-branch sales: company setting and fulfillment branch selection."""
from __future__ import annotations

from uuid import uuid4

from models.branch import Branch, BranchStock
from models.order_item import OrderItem
from utils.branch_migration import get_default_branch
from utils.branch_stock_service import (
    BranchStockError,
    deduct_stock,
    get_branch_stock,
    receive_stock,
)


def is_sell_from_all_branches_enabled() -> bool:
    try:
        from models.system_settings import SystemSettings

        settings = SystemSettings.get_settings()
        flags = settings.get_ui_flags() if settings else {}
        return bool(flags.get("sell_from_all_branches"))
    except Exception:
        return False


def set_sell_from_all_branches(enabled: bool) -> None:
    from models.system_settings import SystemSettings
    from extensions import db
    from datetime import datetime

    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    flags["sell_from_all_branches"] = bool(enabled)
    settings.set_ui_flags(flags)
    settings.updated_at = datetime.utcnow()
    db.session.add(settings)


def active_branches_for_sales():
    """Return every active company branch available for cross-branch sales.

    The dashboard branch scope controls which orders and inventory rows are
    displayed.  It must not narrow the explicit fulfillment-branch picker;
    otherwise selecting a dashboard branch makes every other branch disappear
    from the preparation/agent modal even when cross-branch sales is enabled.
    """
    return (
        Branch.query.filter_by(is_active=True)
        .order_by(Branch.is_default.desc(), Branch.name.asc())
        .all()
    )


def available_fulfillment_qty(
    branch_id: int,
    product_id: int,
    variant_color: str | None = None,
) -> int:
    """Branch stock capped by color balance when the line has a color.

    Prefer the local product-color row for this branch.  Falling back to the
    company-wide color sum only covers legacy catalogues that still keep a
    single shared color row.
    """
    from utils.branch_stock_service import get_available_branch_stock
    branch_qty = int(get_available_branch_stock(int(branch_id), int(product_id)) or 0)
    color = (variant_color or "").strip()
    from modules.inventory_locations.lots import partitioned,available
    from utils.branch_stock_service import _branch_product_id
    if partitioned(branch_id,_branch_product_id(branch_id,product_id)):
        branch_qty=min(branch_qty,available(product_id,branch_id,color or None,None,automatic=True))
    if not color:
        return branch_qty
    from models.product_color_variant import ProductColorVariant
    from utils.branch_stock_service import _branch_product_id
    from utils.product_color_service import get_available_color_quantity

    local_product_id = int(_branch_product_id(int(branch_id), int(product_id)))
    local_variant = (
        ProductColorVariant.query.filter_by(
            product_id=local_product_id,
            color_name=color,
        ).first()
    )
    if local_variant is not None:
        from utils.desktop_stock_reservations import reserved_for_stock
        color_qty = max(0, int(local_variant.quantity or 0) - reserved_for_stock(0, local_variant.id))
    else:
        color_qty = int(get_available_color_quantity(int(product_id), color) or 0)
    return max(0, min(branch_qty, color_qty))


def branches_stock_for_product(
    product_id: int,
    variant_color: str | None = None,
) -> list[dict]:
    """Active branches with available quantity for a product (and color)."""
    result = []
    for branch in active_branches_for_sales():
        result.append(
            {
                "id": branch.id,
                "name": branch.name,
                "code": branch.code,
                # get_branch_stock resolves the matching local product copy
                # when the company uses the legacy shared catalogue.
                "quantity": available_fulfillment_qty(
                    branch.id, product_id, variant_color
                ),
            }
        )
    return result


def available_sale_quantity(
    product_id: int,
    branch_id: int | None = None,
    variant_color: str | None = None,
) -> int:
    """Quantity available for sale under current company policy."""
    color = (variant_color or "").strip()
    if is_sell_from_all_branches_enabled() and not branch_id:
        from utils.branch_stock_service import get_total_stock

        total = int(get_total_stock(product_id) or 0)
        if not color:
            return total
        from utils.product_color_service import get_color_quantity

        return max(0, min(total, int(get_color_quantity(product_id, color) or 0)))
    if branch_id:
        return available_fulfillment_qty(branch_id, product_id, color or None)
    from models.product import Product

    product = Product.query.get(product_id)
    total = int(product.quantity or 0) if product else 0
    if not color:
        return total
    from utils.product_color_service import get_color_quantity

    return max(0, min(total, int(get_color_quantity(product_id, color) or 0)))


def pick_fulfillment_branch(
    product_id: int,
    qty: int,
    *,
    preferred_branch_id: int | None = None,
    explicit_branch_id: int | None = None,
    variant_color: str | None = None,
) -> int | None:
    """
    Choose which branch to deduct from.

    When sell_from_all_branches is on:
    - honor explicit branch if it has enough stock
    - prefer preferred branch if it has enough stock
    - otherwise pick any active branch with enough stock (most stock first)

    When off: explicit → preferred → default branch only.
    """
    qty = int(qty or 0)
    if qty <= 0:
        return explicit_branch_id or preferred_branch_id or (
            get_default_branch().id if get_default_branch() else None
        )

    if explicit_branch_id:
        allowed_ids = {int(branch.id) for branch in active_branches_for_sales()}
        if int(explicit_branch_id) not in allowed_ids:
            return None
        branch = Branch.query.filter_by(id=int(explicit_branch_id), is_active=True).first()
        if branch and available_fulfillment_qty(branch.id, product_id, variant_color) >= qty:
            return branch.id
        if not is_sell_from_all_branches_enabled():
            return branch.id if branch else None

    if not is_sell_from_all_branches_enabled():
        if preferred_branch_id:
            branch = Branch.query.filter_by(id=int(preferred_branch_id), is_active=True).first()
            if branch:
                return branch.id
        default = get_default_branch()
        return default.id if default else None

    if preferred_branch_id:
        branch = Branch.query.filter_by(id=int(preferred_branch_id), is_active=True).first()
        if branch and available_fulfillment_qty(branch.id, product_id, variant_color) >= qty:
            return branch.id

    candidates = []
    for branch in active_branches_for_sales():
        available = available_fulfillment_qty(branch.id, product_id, variant_color)
        if available >= qty:
            candidates.append((available, branch.id))
    if not candidates:
        return None
    candidates.sort(key=lambda row: (-row[0], row[1]))
    return candidates[0][1]


def resolve_sale_fulfillment(
    product_id: int,
    qty: int,
    *,
    preferred_branch_id: int | None = None,
    explicit_branch_id: int | None = None,
    variant_color: str | None = None,
) -> tuple[int | None, dict]:
    """
    Resolve fulfillment branch and validate stock.
    Returns (branch_id, validation_dict).
    """
    from utils.inventory_movements import validate_sale_quantity

    sell_all = is_sell_from_all_branches_enabled()
    branch_id = pick_fulfillment_branch(
        product_id,
        qty,
        preferred_branch_id=preferred_branch_id,
        explicit_branch_id=explicit_branch_id,
        variant_color=variant_color,
    )

    if sell_all:
        validation = validate_sale_quantity(product_id, qty, None)
        if not validation["valid"]:
            return None, validation
        if not branch_id:
            return None, {
                "valid": False,
                "available": validation["available"],
                "message": (
                    f"لا يوجد فرع واحد فيه الكمية المطلوبة ({qty}). "
                    f"المتاح الإجمالي: {validation['available']}"
                ),
            }
        available = available_fulfillment_qty(branch_id, product_id, variant_color)
        if available < qty:
            return None, {
                "valid": False,
                "available": available,
                "message": (
                    f"الكمية المتوفرة في الفرع المختار ({available}) "
                    f"أقل من المطلوب ({qty})"
                ),
            }
        return branch_id, {"valid": True, "available": available, "message": ""}

    validation = validate_sale_quantity(product_id, qty, branch_id)
    if not validation["valid"]:
        return branch_id, validation
    return branch_id, validation


def reassign_item_fulfillment_branch(
    item: OrderItem,
    new_branch_id: int,
    *,
    inventory_is_deducted: bool,
) -> None:
    """Select or move an item's fulfillment branch without double deduction.

    A deferred order has no reserved physical stock yet, even when its line
    already carries a fulfillment branch.  In that state this function only
    changes the selected branch.  Physical stock is moved between branches
    only after the invoice-level ``stock_is_deducted`` guard says that the
    order actually owns deducted stock.

    ``inventory_is_deducted`` is deliberately mandatory so a new caller
    cannot accidentally turn branch selection into an untracked deduction.
    """
    new_branch_id = int(new_branch_id)
    new_branch = Branch.query.filter_by(id=new_branch_id, is_active=True).first()
    if not new_branch:
        raise BranchStockError("الفرع غير موجود أو غير نشط")

    qty = int(item.quantity or 0)
    if qty <= 0:
        raise BranchStockError("كمية الصنف غير صالحة")

    old_branch_id = item.fulfillment_branch_id
    if old_branch_id and int(old_branch_id) == new_branch_id:
        return

    product_id = int(item.product_id)
    destination_product_id = product_id
    from models.product import Product
    from utils.branch_product_service import product_for_branch
    from flask import has_app_context

    source_product = getattr(item, "product", None)
    if source_product is None and has_app_context():
        source_product = (
            Product.query.execution_options(skip_branch_scope=True)
            .filter_by(id=product_id)
            .first()
        )
    # ``branch_id IS NULL`` is a legacy shared-catalog row. Keep supporting it
    # until the migration localizes it; all newly-created products are local.
    if source_product is not None and source_product.branch_id is not None:
        try:
            destination_product = product_for_branch(source_product, new_branch_id)
        except ValueError as exc:
            raise BranchStockError(str(exc)) from exc
        destination_product_id = int(destination_product.id)

    variant_color = (getattr(item, "variant_color", None) or "").strip() or None
    # Color stock is deducted only when the order locks inventory.  Until then
    # the fulfillment picker must respect the color balance, not the mixed
    # product total (white+silver) sitting on the branch row.
    available = (
        available_fulfillment_qty(new_branch_id, destination_product_id, variant_color)
        if not inventory_is_deducted
        else get_branch_stock(new_branch_id, destination_product_id)
    )
    if available < qty:
        product_name = (
            getattr(item, "product_name", None)
            or (item.product.name if getattr(item, "product", None) else None)
            or f"#{product_id}"
        )
        color_note = f" / {variant_color}" if variant_color and not inventory_is_deducted else ""
        raise BranchStockError(
            f"المخزون غير كافٍ للمنتج «{product_name}{color_note}» في {new_branch.name}. المتاح: {available}"
        )

    if not inventory_is_deducted:
        item.product_id = destination_product_id
        item.fulfillment_branch_id = new_branch_id
        return

    invoice_id = int(getattr(item, "invoice_id", 0) or 0)
    item_id = int(getattr(item, "id", 0) or 0)
    if not invoice_id or not item_id:
        raise BranchStockError("لا يمكن نقل مخزون سطر طلب بدون رقم حركة معروف")

    from utils.stock_movement_guard import claim_stock_movement

    move_token = uuid4().hex
    if old_branch_id:
        claim_stock_movement(
            f"order:{invoice_id}:item:{item_id}:move:{move_token}:release",
            movement_type="order_branch_release",
            direction="in",
            product_id=product_id,
            branch_id=int(old_branch_id),
            quantity=qty,
            unit_cost=int(getattr(item, "cost", 0) or 0),
            source_type="invoice",
            source_id=invoice_id,
            source_line_id=item_id,
            details={"to_branch_id": new_branch_id},
        )
        receive_stock(int(old_branch_id), product_id, qty)
    try:
        claim_stock_movement(
            f"order:{invoice_id}:item:{item_id}:move:{move_token}:reserve",
            movement_type="order_branch_reserve",
            direction="out",
            product_id=destination_product_id,
            branch_id=new_branch_id,
            quantity=qty,
            unit_cost=int(getattr(item, "cost", 0) or 0),
            source_type="invoice",
            source_id=invoice_id,
            source_line_id=item_id,
            details={"from_branch_id": int(old_branch_id) if old_branch_id else None},
        )
        deduct_stock(new_branch_id, destination_product_id, qty)
    except BranchStockError:
        if old_branch_id:
            deduct_stock(int(old_branch_id), product_id, qty)
        raise

    item.product_id = destination_product_id
    item.fulfillment_branch_id = new_branch_id


def preserved_deducted_fulfillment_branch(
    items,
    *,
    inventory_is_deducted: bool,
    preserve_deducted: bool,
) -> tuple[bool, int | None]:
    """Return whether agent preparation must keep an existing reservation."""
    if not preserve_deducted or not inventory_is_deducted:
        return False, None

    branch_ids = {
        int(item.fulfillment_branch_id)
        for item in items
        if getattr(item, "fulfillment_branch_id", None)
    }
    branch_id = next(iter(branch_ids)) if len(branch_ids) == 1 else None
    return True, branch_id


def order_can_edit_fulfillment(order) -> bool:
    status = (getattr(order, "status", None) or "").strip()
    payment = (getattr(order, "payment_status", None) or "").strip()
    if status in ("تم التوصيل", "ملغي", "راجع", "مرتجع", "راجعة"):
        return False
    if payment in ("ملغي", "راجع", "مرتجع", "راجعة"):
        return False
    return True
