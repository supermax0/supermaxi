"""Inventory accounting audit and repair helpers.

The repair is intentionally conservative:
- Every product must have branch_stock rows for branch-scoped inventory.
- Product.quantity is synchronized from the sum of branch_stock.quantity.
- Missing purchase/order branch references are assigned to the default branch.
- Negative quantities are reported, not silently changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import inspect, text

from extensions import db
from models.branch import Branch, BranchStock
from models.product import Product
from models.purchase import Purchase
from models.purchase_item import PurchaseItem
from models.order_item import OrderItem
from utils.branch_migration import ensure_branch_schema, get_default_branch
from utils.branch_stock_service import sync_product_total
from utils.product_schema_guard import ensure_product_schema


@dataclass
class InventoryRepairReport:
    tenant: str | None = None
    dry_run: bool = True
    default_branch_id: int | None = None
    products_checked: int = 0
    branch_rows_created: int = 0
    product_totals_synced: int = 0
    purchases_branch_fixed: int = 0
    invoices_branch_fixed: int = 0
    order_items_branch_fixed: int = 0
    opening_stock_fixed: int = 0
    negative_products: list[dict] = field(default_factory=list)
    negative_branch_rows: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tenant": self.tenant,
            "dry_run": self.dry_run,
            "default_branch_id": self.default_branch_id,
            "products_checked": self.products_checked,
            "branch_rows_created": self.branch_rows_created,
            "product_totals_synced": self.product_totals_synced,
            "purchases_branch_fixed": self.purchases_branch_fixed,
            "invoices_branch_fixed": self.invoices_branch_fixed,
            "order_items_branch_fixed": self.order_items_branch_fixed,
            "opening_stock_fixed": self.opening_stock_fixed,
            "negative_products": self.negative_products,
            "negative_branch_rows": self.negative_branch_rows,
        }


def _ensure_default_branch() -> Branch:
    ensure_branch_schema()
    branch = get_default_branch()
    if branch:
        return branch

    branch = Branch(code="MAIN", name="الفرع الرئيسي", is_active=True, is_default=True)
    db.session.add(branch)
    db.session.flush()
    return branch


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(db.session.get_bind()).get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return column_name in {col["name"] for col in inspect(db.session.get_bind()).get_columns(table_name)}


def _count_null_branch_rows(table_name: str, column_name: str) -> int:
    if not _column_exists(table_name, column_name):
        return 0
    row = db.session.execute(
        text(f"SELECT COUNT(*) FROM {table_name} WHERE {column_name} IS NULL")
    ).scalar()
    return int(row or 0)


def _assign_default_branch(table_name: str, column_name: str, branch_id: int, dry_run: bool) -> int:
    count = _count_null_branch_rows(table_name, column_name)
    if count and not dry_run:
        db.session.execute(
            text(f"UPDATE {table_name} SET {column_name} = :branch_id WHERE {column_name} IS NULL"),
            {"branch_id": branch_id},
        )
    return count


def _assign_order_item_branches(default_branch_id: int, dry_run: bool) -> int:
    if not _column_exists("order_item", "fulfillment_branch_id"):
        return 0
    count = _count_null_branch_rows("order_item", "fulfillment_branch_id")
    if count and not dry_run:
        if _column_exists("invoice", "branch_id"):
            db.session.execute(
                text(
                    """
                    UPDATE order_item
                    SET fulfillment_branch_id = COALESCE(
                        (SELECT invoice.branch_id FROM invoice WHERE invoice.id = order_item.invoice_id),
                        :default_branch_id
                    )
                    WHERE fulfillment_branch_id IS NULL
                    """
                ),
                {"default_branch_id": default_branch_id},
            )
        else:
            db.session.execute(
                text("UPDATE order_item SET fulfillment_branch_id = :branch_id WHERE fulfillment_branch_id IS NULL"),
                {"branch_id": default_branch_id},
            )
    return count


def _product_has_stock_documents(product_id: int) -> bool:
    purchase_items = (
        db.session.query(PurchaseItem.id)
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .filter(PurchaseItem.product_id == product_id)
        .first()
    )
    if purchase_items:
        return True
    legacy_purchase = db.session.query(Purchase.id).filter(Purchase.product_id == product_id).first()
    if legacy_purchase:
        return True
    order_item = db.session.query(OrderItem.id).filter(OrderItem.product_id == product_id).first()
    if order_item:
        return True
    if _table_exists("stock_transfer_line"):
        transfer_line = db.session.execute(
            text("SELECT id FROM stock_transfer_line WHERE product_id = :product_id LIMIT 1"),
            {"product_id": product_id},
        ).first()
        if transfer_line:
            return True
    return False


def audit_and_repair_inventory_accounting(*, tenant: str | None = None, dry_run: bool = True) -> InventoryRepairReport:
    """Audit and optionally repair core inventory accounting consistency."""
    ensure_product_schema()
    default_branch = _ensure_default_branch()
    try:
        from routes.purchases import _ensure_purchase_schema

        _ensure_purchase_schema()
    except Exception:
        db.session.rollback()
    report = InventoryRepairReport(
        tenant=tenant,
        dry_run=dry_run,
        default_branch_id=default_branch.id,
    )

    products = Product.query.order_by(Product.id.asc()).all()
    report.products_checked = len(products)

    for product in products:
        product_qty = int(product.quantity or 0)
        if product_qty < 0:
            report.negative_products.append({"product_id": product.id, "name": product.name, "quantity": product_qty})

        rows = BranchStock.query.filter_by(product_id=product.id).all()
        if not rows:
            report.branch_rows_created += 1
            if not dry_run:
                db.session.add(
                    BranchStock(
                        branch_id=default_branch.id,
                        product_id=product.id,
                        quantity=max(product_qty, 0),
                        opening_stock=max(int(product.opening_stock or 0), 0),
                        low_stock_threshold=int(product.low_stock_threshold or 5),
                    )
                )
                db.session.flush()
            rows = BranchStock.query.filter_by(product_id=product.id).all() if not dry_run else []

        for row in rows:
            row_qty = int(row.quantity or 0)
            if row_qty < 0:
                report.negative_branch_rows.append(
                    {
                        "branch_stock_id": row.id,
                        "branch_id": row.branch_id,
                        "product_id": row.product_id,
                        "quantity": row_qty,
                    }
                )

        if rows and not _product_has_stock_documents(product.id):
            missing_opening_rows = [
                row for row in rows if int(row.quantity or 0) > 0 and int(row.opening_stock or 0) == 0
            ]
            if missing_opening_rows:
                report.opening_stock_fixed += len(missing_opening_rows)
                if not dry_run:
                    for row in missing_opening_rows:
                        row.opening_stock = int(row.quantity or 0)
                    product.opening_stock = sum(int(row.opening_stock or 0) for row in rows)

        if not dry_run:
            total = sync_product_total(product.id)
        else:
            total = (
                db.session.query(db.func.coalesce(db.func.sum(BranchStock.quantity), 0))
                .filter(BranchStock.product_id == product.id)
                .scalar()
                or 0
            )
        if int(total or 0) != product_qty:
            report.product_totals_synced += 1

    report.purchases_branch_fixed = _assign_default_branch("purchase", "branch_id", default_branch.id, dry_run)
    report.invoices_branch_fixed = _assign_default_branch("invoice", "branch_id", default_branch.id, dry_run)
    report.order_items_branch_fixed = _assign_order_item_branches(default_branch.id, dry_run)

    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()

    return report
