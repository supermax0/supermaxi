"""Cross-branch sales: company setting and fulfillment branch selection."""
from __future__ import annotations

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
    return (
        Branch.query.filter_by(is_active=True)
        .order_by(Branch.is_default.desc(), Branch.name.asc())
        .all()
    )


def branches_stock_for_product(product_id: int) -> list[dict]:
    """Active branches with available quantity for a product."""
    rows = (
        BranchStock.query.filter_by(product_id=product_id)
        .join(Branch, Branch.id == BranchStock.branch_id)
        .filter(Branch.is_active.is_(True))
        .all()
    )
    by_id = {int(r.branch_id): int(r.quantity or 0) for r in rows}
    result = []
    for branch in active_branches_for_sales():
        result.append(
            {
                "id": branch.id,
                "name": branch.name,
                "code": branch.code,
                "quantity": by_id.get(branch.id, 0),
            }
        )
    return result


def available_sale_quantity(product_id: int, branch_id: int | None = None) -> int:
    """Quantity available for sale under current company policy."""
    if is_sell_from_all_branches_enabled() and not branch_id:
        from utils.branch_stock_service import get_total_stock

        return get_total_stock(product_id)
    if branch_id:
        return get_branch_stock(branch_id, product_id)
    from models.product import Product

    product = Product.query.get(product_id)
    return int(product.quantity or 0) if product else 0


def pick_fulfillment_branch(
    product_id: int,
    qty: int,
    *,
    preferred_branch_id: int | None = None,
    explicit_branch_id: int | None = None,
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
        branch = Branch.query.filter_by(id=int(explicit_branch_id), is_active=True).first()
        if branch and get_branch_stock(branch.id, product_id) >= qty:
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
        if branch and get_branch_stock(branch.id, product_id) >= qty:
            return branch.id

    candidates = []
    for branch in active_branches_for_sales():
        available = get_branch_stock(branch.id, product_id)
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
        available = get_branch_stock(branch_id, product_id)
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


def reassign_item_fulfillment_branch(item: OrderItem, new_branch_id: int) -> None:
    """Move reserved stock from the item's current branch to another branch."""
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

    product_id = item.product_id
    available = get_branch_stock(new_branch_id, product_id)
    if available < qty:
        raise BranchStockError(
            f"المخزون غير كافٍ في {new_branch.name}. المتاح: {available}"
        )

    if old_branch_id:
        receive_stock(int(old_branch_id), product_id, qty)
    try:
        deduct_stock(new_branch_id, product_id, qty)
    except BranchStockError:
        if old_branch_id:
            deduct_stock(int(old_branch_id), product_id, qty)
        raise

    item.fulfillment_branch_id = new_branch_id


def order_can_edit_fulfillment(order) -> bool:
    status = (getattr(order, "status", None) or "").strip()
    payment = (getattr(order, "payment_status", None) or "").strip()
    if status in ("تم التوصيل", "ملغي", "راجع", "مرتجع", "راجعة"):
        return False
    if payment in ("ملغي", "راجع", "مرتجع", "راجعة"):
        return False
    return True
