"""Central branch-scoped inventory operations."""
from __future__ import annotations

from typing import Iterable

from extensions import db
from models.branch import Branch, BranchStock
from models.product import Product


class BranchStockError(Exception):
    pass


def get_or_create_branch_stock(branch_id: int, product_id: int) -> BranchStock:
    bs = BranchStock.query.filter_by(branch_id=branch_id, product_id=product_id).first()
    if bs:
        return bs
    product = Product.query.get(product_id)
    bs = BranchStock(
        branch_id=branch_id,
        product_id=product_id,
        quantity=0,
        opening_stock=0,
        low_stock_threshold=(product.low_stock_threshold if product else 5) or 5,
    )
    db.session.add(bs)
    db.session.flush()
    return bs


def get_branch_stock(branch_id: int, product_id: int) -> int:
    bs = BranchStock.query.filter_by(branch_id=branch_id, product_id=product_id).first()
    return int(bs.quantity if bs else 0)


def get_total_stock(product_id: int) -> int:
    total = (
        db.session.query(db.func.coalesce(db.func.sum(BranchStock.quantity), 0))
        .filter(BranchStock.product_id == product_id)
        .scalar()
    )
    return int(total or 0)


def sync_product_total(product_id: int) -> int:
    product = Product.query.get(product_id)
    if not product:
        return 0
    total = get_total_stock(product_id)
    product.quantity = total
    return total


def set_branch_stock(branch_id: int, product_id: int, quantity: int, *, sync_product: bool = True) -> BranchStock:
    if quantity < 0:
        raise BranchStockError("الكمية لا يمكن أن تكون سالبة")
    bs = get_or_create_branch_stock(branch_id, product_id)
    bs.quantity = int(quantity)
    if sync_product:
        sync_product_total(product_id)
    return bs


def receive_stock(branch_id: int, product_id: int, qty: int, *, sync_product: bool = True) -> BranchStock:
    qty = int(qty or 0)
    if qty <= 0:
        raise BranchStockError("كمية الاستلام يجب أن تكون أكبر من صفر")
    bs = get_or_create_branch_stock(branch_id, product_id)
    db.session.query(BranchStock).filter(BranchStock.id == bs.id).update(
        {BranchStock.quantity: BranchStock.quantity + qty}, synchronize_session=False
    )
    db.session.expire(bs)
    if sync_product:
        sync_product_total(product_id)
    return bs


def deduct_stock(branch_id: int, product_id: int, qty: int, *, sync_product: bool = True) -> BranchStock:
    qty = int(qty or 0)
    if qty <= 0:
        raise BranchStockError("كمية الخصم يجب أن تكون أكبر من صفر")
    bs = get_or_create_branch_stock(branch_id, product_id)
    # Conditional UPDATE prevents two concurrent order transitions from both
    # consuming the same last unit (works on SQLite and PostgreSQL).
    updated = (
        db.session.query(BranchStock)
        .filter(BranchStock.id == bs.id, BranchStock.quantity >= qty)
        .update({BranchStock.quantity: BranchStock.quantity - qty}, synchronize_session=False)
    )
    if updated != 1:
        db.session.expire(bs)
        available = int(bs.quantity or 0)
        branch = Branch.query.get(branch_id)
        branch_name = branch.name if branch else str(branch_id)
        product = Product.query.get(product_id)
        product_name = (product.name if product else None) or f"#{product_id}"
        raise BranchStockError(
            f"المخزون غير كافٍ للمنتج «{product_name}» في {branch_name}. المتاح: {available}"
        )
    db.session.expire(bs)
    if sync_product:
        sync_product_total(product_id)
    return bs


def validate_branch_sale(branch_id: int, product_id: int, qty: int) -> tuple[bool, str]:
    qty = int(qty or 0)
    if qty <= 0:
        return False, "الكمية غير صالحة"
    available = get_branch_stock(branch_id, product_id)
    if available < qty:
        product = Product.query.get(product_id)
        product_name = (product.name if product else None) or f"#{product_id}"
        return False, f"المخزون غير كافٍ للمنتج «{product_name}». المتاح: {available}"
    return True, ""


def adjust_branch_stock(branch_id: int, product_id: int, adjustment: int, *, sync_product: bool = True) -> BranchStock:
    bs = get_or_create_branch_stock(branch_id, product_id)
    new_qty = int(bs.quantity or 0) + int(adjustment or 0)
    if new_qty < 0:
        raise BranchStockError(f"المخزون لا يمكن أن يكون سالباً. الحالي: {bs.quantity or 0}")
    bs.quantity = new_qty
    if sync_product:
        sync_product_total(product_id)
    return bs


def set_opening_branch_stock(
    branch_id: int,
    product_id: int,
    opening_stock: int,
    *,
    sync_product: bool = True,
) -> BranchStock:
    opening_stock = int(opening_stock or 0)
    bs = get_or_create_branch_stock(branch_id, product_id)
    bs.opening_stock = opening_stock
    bs.quantity = opening_stock
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
    if branch_id:
        return {r.product_id: int(r.quantity or 0) for r in rows}
    totals: dict[int, int] = {}
    for row in rows:
        totals[row.product_id] = totals.get(row.product_id, 0) + int(row.quantity or 0)
    return totals
