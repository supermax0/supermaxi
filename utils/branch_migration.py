"""Schema migration and data backfill for multi-branch support."""
from __future__ import annotations

from sqlalchemy import inspect, text

from extensions import db


_MIGRATION_FLAG = "branch_migration_v1_done"


def _table_exists(name: str) -> bool:
    return name in inspect(db.engine).get_table_names()


def _column_exists(table: str, column: str) -> bool:
    if not _table_exists(table):
        return False
    cols = {c["name"] for c in inspect(db.engine).get_columns(table)}
    return column in cols


def _add_column_if_missing(table: str, column: str, ddl: str) -> None:
    if not _table_exists(table):
        return
    if _column_exists(table, column):
        return
    db.session.execute(text(ddl))
    db.session.commit()


def ensure_branch_schema() -> None:
    """Create branch tables/columns and migrate existing tenant data once."""
    from models.branch import Branch, BranchStock, StockTransfer, StockTransferLine

    Branch.__table__.create(bind=db.engine, checkfirst=True)
    BranchStock.__table__.create(bind=db.engine, checkfirst=True)
    StockTransfer.__table__.create(bind=db.engine, checkfirst=True)
    StockTransferLine.__table__.create(bind=db.engine, checkfirst=True)

    _add_column_if_missing("employee", "branch_id", "ALTER TABLE employee ADD COLUMN branch_id INTEGER")
    _add_column_if_missing("invoice", "branch_id", "ALTER TABLE invoice ADD COLUMN branch_id INTEGER")
    _add_column_if_missing(
        "order_item",
        "fulfillment_branch_id",
        "ALTER TABLE order_item ADD COLUMN fulfillment_branch_id INTEGER",
    )
    _add_column_if_missing("purchase", "branch_id", "ALTER TABLE purchase ADD COLUMN branch_id INTEGER")
    _add_column_if_missing("activity_log", "branch_id", "ALTER TABLE activity_log ADD COLUMN branch_id INTEGER")

    if _migration_data_done():
        return

    _run_data_migration()
    _mark_migration_done()


def _migration_data_done() -> bool:
    from models.system_settings import SystemSettings

    settings = SystemSettings.query.first()
    if settings:
        flags = settings.get_ui_flags()
        if flags.get(_MIGRATION_FLAG):
            return True
    from models.branch import Branch

    return Branch.query.filter_by(is_default=True).count() > 0


def _mark_migration_done() -> None:
    from models.system_settings import SystemSettings

    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    flags[_MIGRATION_FLAG] = True
    settings.set_ui_flags(flags)
    db.session.commit()


def _run_data_migration() -> None:
    from models.branch import Branch, BranchStock
    from models.employee import Employee
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from models.purchase import Purchase

    default_branch = Branch.query.filter_by(is_default=True).first()
    if not default_branch:
        default_branch = Branch.query.filter_by(code="MAIN").first()
    if not default_branch:
        default_branch = Branch(
            code="MAIN",
            name="الفرع الرئيسي",
            is_active=True,
            is_default=True,
        )
        db.session.add(default_branch)
        db.session.flush()

    branch_by_code = {b.code.upper(): b for b in Branch.query.all()}

    for product in Product.query.all():
        bs = BranchStock.query.filter_by(
            branch_id=default_branch.id,
            product_id=product.id,
        ).first()
        if not bs:
            bs = BranchStock(
                branch_id=default_branch.id,
                product_id=product.id,
                quantity=product.quantity or 0,
                opening_stock=product.opening_stock or 0,
                low_stock_threshold=product.low_stock_threshold or 5,
            )
            db.session.add(bs)

    for emp in Employee.query.filter(Employee.branch_id.is_(None)).all():
        emp.branch_id = default_branch.id

    for inv in Invoice.query.filter(Invoice.branch_id.is_(None)).all():
        inv.branch_id = default_branch.id

    for item in OrderItem.query.filter(OrderItem.fulfillment_branch_id.is_(None)).all():
        branch_id = None
        if item.invoice and item.invoice.branch_id:
            branch_id = item.invoice.branch_id
        item.fulfillment_branch_id = branch_id or default_branch.id

    for purchase in Purchase.query.filter(Purchase.branch_id.is_(None)).all():
        code = (purchase.branch_code or "").strip().upper()
        branch = branch_by_code.get(code) if code else None
        purchase.branch_id = (branch or default_branch).id

    db.session.commit()

    for product in Product.query.all():
        total = (
            db.session.query(db.func.coalesce(db.func.sum(BranchStock.quantity), 0))
            .filter(BranchStock.product_id == product.id)
            .scalar()
        )
        product.quantity = int(total or 0)


def get_default_branch():
    from models.branch import Branch

    ensure_branch_schema()
    branch = Branch.query.filter_by(is_default=True, is_active=True).first()
    if branch:
        return branch
    return Branch.query.filter_by(is_active=True).order_by(Branch.id).first()
