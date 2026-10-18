"""Schema migration and data backfill for multi-branch support."""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import uuid
from datetime import datetime

from flask import current_app, g, has_request_context
from sqlalchemy import and_, case, inspect, text

from extensions import db


_MIGRATION_FLAG = "branch_migration_v1_done"
_SHARED_COMPAT_FLAG = "branch_shared_compat_v1_done"
_SCOPE_V2_FLAG = "branch_scope_v3_done"

_BRANCH_OWNED_TABLES = (
    "product",
    "customer",
    "supplier",
    "expense",
    "treasury_account",
    "delivery_agent",
    "shipping_company",
    "account_transaction",
    "invoice_payment_ledger",
    "purchase_payment",
    "supplier_payment",
    "employee_payment",
    "shipping_payment",
    "shipping_report",
    "treasury_transfer",
    "fixed_asset",
    "trade_in_receipt",
)


def _branch_schema_engine():
    """Use the same database bind as tenant-scoped model queries."""
    tenant_slug = getattr(g, "tenant", None)
    if tenant_slug:
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(tenant_slug)
    bind = db.session.get_bind()
    return bind if bind is not None else db.engine


def _table_exists(engine, name: str) -> bool:
    return name in inspect(engine).get_table_names()


def _column_exists(engine, table: str, column: str) -> bool:
    if not _table_exists(engine, table):
        return False
    cols = {c["name"] for c in inspect(engine).get_columns(table)}
    return column in cols


def _add_column_if_missing(engine, table: str, column: str, ddl: str) -> None:
    if not _table_exists(engine, table):
        return
    if _column_exists(engine, table, column):
        return
    with engine.begin() as conn:
        conn.execute(text(ddl))


def _create_pre_branch_backup(engine) -> str | None:
    """Create one consistent tenant backup before any branch data migration."""
    if engine.dialect.name != "sqlite":
        return None
    from models.system_settings import SystemSettings
    from sqlalchemy.orm import load_only

    settings = SystemSettings.query.options(
        load_only(SystemSettings.id, SystemSettings.ui_flags)
    ).first()
    flags = settings.get_ui_flags() if settings else {}
    existing = str(flags.get("branch_pre_migration_backup") or "").strip()
    if existing:
        existing_path = Path(existing)
        if not existing_path.is_absolute():
            existing_path = Path(current_app.root_path) / existing_path
        if existing_path.is_file():
            return str(existing_path.resolve())

    source_path = Path(str(engine.url.database or "")).resolve()
    if not source_path.is_file():
        return None
    tenant_slug = str(getattr(g, "tenant", None) or source_path.stem)
    # Test databases are disposable and numerous; production tenants always
    # receive the durable pre-migration copy.
    if tenant_slug.startswith("test_") or current_app.config.get("TESTING"):
        return None

    backup_root = (Path(current_app.root_path) / "backups" / "branch-migration").resolve()
    target_dir = (backup_root / tenant_slug).resolve()
    if backup_root not in target_dir.parents:
        raise ValueError("مسار نسخة الفروع غير صالح")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / (
        f"{tenant_slug}.pre-independent-branches-"
        f"{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.db"
    )

    source_connection = sqlite3.connect(str(source_path), timeout=30)
    destination_connection = sqlite3.connect(str(target_path), timeout=30)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()

    if settings:
        flags["branch_pre_migration_backup"] = str(target_path)
        flags["branch_pre_migration_backup_at"] = datetime.utcnow().isoformat()
        settings.set_ui_flags(flags)
        db.session.commit()
    return str(target_path)


def _ensure_product_uniqueness(engine) -> None:
    """Upgrade PostgreSQL's legacy company-wide barcode constraint."""
    if engine.dialect.name != "postgresql" or not _table_exists(engine, "product"):
        return
    constraints = inspect(engine).get_unique_constraints("product")
    by_name = {item.get("name"): item for item in constraints if item.get("name")}
    column_sets = {tuple(item.get("column_names") or []) for item in constraints}
    with engine.begin() as conn:
        if "_product_barcode_tenant_uc" in by_name:
            conn.execute(text('ALTER TABLE product DROP CONSTRAINT "_product_barcode_tenant_uc"'))
        if ("tenant_id", "branch_id", "barcode") not in column_sets:
            conn.execute(text(
                'ALTER TABLE product ADD CONSTRAINT "_product_barcode_tenant_branch_uc" '
                'UNIQUE (tenant_id, branch_id, barcode)'
            ))


def _ensure_branch_indexes(engine) -> None:
    tables = (*_BRANCH_OWNED_TABLES, "employee", "invoice", "purchase", "activity_log", "stock_movement")
    with engine.begin() as conn:
        for table_name in tables:
            if _column_exists(engine, table_name, "branch_id"):
                conn.execute(text(
                    f'CREATE INDEX IF NOT EXISTS "ix_{table_name}_branch_id" '
                    f'ON "{table_name}" (branch_id)'
                ))
        if _column_exists(engine, "product", "catalog_group_id"):
            conn.execute(text(
                'CREATE INDEX IF NOT EXISTS "ix_product_catalog_group_id" '
                'ON product (catalog_group_id)'
            ))


def ensure_branch_schema(*, force_independent: bool = False) -> None:
    """Create branch tables/columns and migrate existing tenant data once."""
    scope_was_ready = bool(getattr(g, "branch_scope_ready", False)) if has_request_context() else False
    if has_request_context():
        g.branch_scope_ready = False
    try:
        engine = _branch_schema_engine()
        datetime_type = "TIMESTAMP" if engine.dialect.name == "postgresql" else "DATETIME"
        from utils.branch_mode import independent_branches_enabled

        full_independence = bool(
            force_independent or independent_branches_enabled()
        )
        if not _scope_v2_data_done():
            _create_pre_branch_backup(engine)

        # Product localization loads complete Product ORM rows.  Bring older
        # databases up to the current product columns first, otherwise one
        # missing optional field aborts the whole branch migration.
        from utils.product_schema_guard import ensure_product_schema
        from utils.invoice_schema_guard import ensure_invoice_schema
        from utils.order_item_schema_guard import ensure_order_item_schema
        from utils.payroll_schema import ensure_payroll_schema
        from utils.team_schema import ensure_delivery_agent_schema
        from modules.wholesale.schema_guard import ensure_wholesale_schema

        ensure_product_schema()
        ensure_invoice_schema()
        ensure_order_item_schema()
        ensure_payroll_schema()
        ensure_wholesale_schema()
        ensure_delivery_agent_schema()

        from models.branch import Branch, BranchStock, StockTransfer, StockTransferLine

        Branch.__table__.create(bind=engine, checkfirst=True)
        BranchStock.__table__.create(bind=engine, checkfirst=True)
        StockTransfer.__table__.create(bind=engine, checkfirst=True)
        StockTransferLine.__table__.create(bind=engine, checkfirst=True)
        from models.branch_profile import BranchProfile

        BranchProfile.__table__.create(bind=engine, checkfirst=True)
        from models.branch_cash_transfer import BranchCashTransfer

        BranchCashTransfer.__table__.create(bind=engine, checkfirst=True)
        from models.branch_assignment import BranchUserAssignment

        BranchUserAssignment.__table__.create(bind=engine, checkfirst=True)

        _add_column_if_missing(engine, "employee", "branch_id", "ALTER TABLE employee ADD COLUMN branch_id INTEGER")
        _add_column_if_missing(
            engine,
            "employee",
            "default_warehouse_id",
            "ALTER TABLE employee ADD COLUMN default_warehouse_id INTEGER",
        )
        _add_column_if_missing(engine, "invoice", "branch_id", "ALTER TABLE invoice ADD COLUMN branch_id INTEGER")
        _add_column_if_missing(
            engine,
            "invoice",
            "return_branch_id",
            "ALTER TABLE invoice ADD COLUMN return_branch_id INTEGER",
        )
        _add_column_if_missing(
            engine,
            "invoice",
            "employee_commission_settled_at",
            f"ALTER TABLE invoice ADD COLUMN employee_commission_settled_at {datetime_type}",
        )
        # The data migration below loads full Invoice ORM rows. Older tenant
        # databases can predate these optional columns, so ensure them before
        # issuing that ORM query instead of failing the entire branch upgrade.
        _add_column_if_missing(
            engine,
            "invoice",
            "agent_note",
            "ALTER TABLE invoice ADD COLUMN agent_note TEXT",
        )
        _add_column_if_missing(
            engine,
            "order_item",
            "fulfillment_branch_id",
            "ALTER TABLE order_item ADD COLUMN fulfillment_branch_id INTEGER",
        )
        _add_column_if_missing(engine, "purchase", "branch_id", "ALTER TABLE purchase ADD COLUMN branch_id INTEGER")
        _add_column_if_missing(engine, "activity_log", "branch_id", "ALTER TABLE activity_log ADD COLUMN branch_id INTEGER")
        _add_column_if_missing(
            engine,
            "stock_transfer_line",
            "variant_color",
            "ALTER TABLE stock_transfer_line ADD COLUMN variant_color VARCHAR(80)",
        )
        _add_column_if_missing(
            engine,
            "stock_transfer_line",
            "destination_product_id",
            "ALTER TABLE stock_transfer_line ADD COLUMN destination_product_id INTEGER",
        )
        for table_name in _BRANCH_OWNED_TABLES:
            _add_column_if_missing(
                engine,
                table_name,
                "branch_id",
                f"ALTER TABLE {table_name} ADD COLUMN branch_id INTEGER",
            )
        _add_column_if_missing(
            engine,
            "product",
            "catalog_group_id",
            "ALTER TABLE product ADD COLUMN catalog_group_id VARCHAR(36)",
        )
        _add_column_if_missing(
            engine,
            "supplier",
            "opening_balance",
            "ALTER TABLE supplier ADD COLUMN opening_balance INTEGER DEFAULT 0",
        )
        _add_column_if_missing(
            engine,
            "supplier",
            "phone2",
            "ALTER TABLE supplier ADD COLUMN phone2 VARCHAR(50)",
        )
        _ensure_product_uniqueness(engine)

        migration_changed = False
        if not _migration_data_done():
            _run_data_migration()
            _mark_migration_done()
            migration_changed = True

        if full_independence and not _scope_v2_data_done():
            before = _verification_snapshot(engine)
            _run_scope_v2_data_migration()
            after = _verification_snapshot(engine)
            if before != after:
                raise RuntimeError(
                    f"Branch migration verification failed: before={before}, after={after}"
                )
            _mark_scope_v2_done({
                "verified": True,
                "verified_at": datetime.utcnow().isoformat(),
                "before": before,
                "after": after,
            })
            migration_changed = True

        # Index DDL uses a separate engine connection. Run it only after a
        # migration commit, never on every request while the request session
        # may already hold a SQLite transaction.
        if migration_changed:
            _ensure_branch_indexes(engine)
    except Exception:
        # Guard route rendering from hard 500 when tenant schema is partially migrated.
        db.session.rollback()
        try:
            current_app.logger.exception("ensure_branch_schema failed")
        except Exception:
            pass
    finally:
        if has_request_context():
            g.branch_scope_ready = scope_was_ready


def _migration_data_done() -> bool:
    from models.system_settings import SystemSettings
    from sqlalchemy.orm import load_only

    settings = SystemSettings.query.options(
        load_only(SystemSettings.id, SystemSettings.ui_flags)
    ).first()
    # Older releases used branch_migration_v1_done before all operational and
    # financial tables received their internal branch owner.  The newer flag
    # forces one safe, idempotent compatibility pass for those tenants.
    return bool(settings and settings.get_ui_flags().get(_SHARED_COMPAT_FLAG, False))


def _mark_migration_done() -> None:
    from models.system_settings import SystemSettings

    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    flags[_MIGRATION_FLAG] = True
    flags[_SHARED_COMPAT_FLAG] = True
    settings.set_ui_flags(flags)
    db.session.commit()


def _scope_v2_data_done() -> bool:
    from models.system_settings import SystemSettings
    from sqlalchemy.orm import load_only

    settings = SystemSettings.query.options(
        load_only(SystemSettings.id, SystemSettings.ui_flags)
    ).first()
    return bool(settings and settings.get_ui_flags().get(_SCOPE_V2_FLAG))


def _mark_scope_v2_done(report: dict) -> None:
    from models.system_settings import SystemSettings

    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    flags[_SCOPE_V2_FLAG] = True
    flags["branch_scope_v3_verification"] = report
    settings.set_ui_flags(flags)
    db.session.commit()


def _verification_snapshot(engine) -> dict[str, int]:
    """Totals that must remain identical while catalog rows are localized."""
    purchase_columns = {
        item["name"] for item in inspect(engine).get_columns("purchase")
    } if _table_exists(engine, "purchase") else set()
    purchase_total_expr = (
        "CASE WHEN grand_total IS NOT NULL AND grand_total != 0 THEN grand_total ELSE total END"
        if "grand_total" in purchase_columns else "total"
    )
    checks = {
        "orders_count": ("invoice", "SELECT COUNT(*) FROM invoice"),
        "sales_total": ("invoice", "SELECT COALESCE(SUM(total), 0) FROM invoice"),
        "purchases_count": ("purchase", "SELECT COUNT(*) FROM purchase"),
        "purchases_total": ("purchase", f"SELECT COALESCE(SUM({purchase_total_expr}), 0) FROM purchase"),
        "expenses_total": ("expense", "SELECT COALESCE(SUM(amount), 0) FROM expense"),
        "supplier_debt": ("supplier", "SELECT COALESCE(SUM(COALESCE(total_debt, 0) - COALESCE(total_paid, 0)), 0) FROM supplier"),
        "stock_quantity": ("branch_stock", "SELECT COALESCE(SUM(quantity), 0) FROM branch_stock"),
        "treasury_balance": ("account_transaction", "SELECT COALESCE(SUM(CASE WHEN type = 'deposit' THEN amount ELSE -amount END), 0) FROM account_transaction"),
    }
    snapshot: dict[str, int] = {}
    for key, (table_name, statement) in checks.items():
        if _table_exists(engine, table_name):
            snapshot[key] = int(db.session.execute(text(statement)).scalar() or 0)
    return snapshot


def _copy_scalar_row(model, source, **overrides):
    values = {}
    for column in model.__table__.columns:
        if column.primary_key:
            continue
        values[column.name] = getattr(source, column.name, None)
    values.update(overrides)
    clone = model(**values)
    db.session.add(clone)
    db.session.flush()
    return clone


def _branch_ids_for_product(product_id: int, default_branch_id: int) -> list[int]:
    from models.branch import BranchStock
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.purchase import Purchase
    from models.purchase_item import PurchaseItem

    branch_ids = {
        int(row[0])
        for row in db.session.query(BranchStock.branch_id)
        .filter(BranchStock.product_id == product_id)
        .distinct()
        .all()
        if row[0]
    }
    branch_ids.update(
        int(row[0])
        for row in db.session.query(Invoice.branch_id)
        .join(OrderItem, OrderItem.invoice_id == Invoice.id)
        .filter(OrderItem.product_id == product_id, Invoice.branch_id.isnot(None))
        .distinct()
        .all()
        if row[0]
    )
    branch_ids.update(
        int(row[0])
        for row in db.session.query(Purchase.branch_id)
        .join(PurchaseItem, PurchaseItem.purchase_id == Purchase.id)
        .filter(PurchaseItem.product_id == product_id, Purchase.branch_id.isnot(None))
        .distinct()
        .all()
        if row[0]
    )
    return sorted(branch_ids or {default_branch_id})


def _localize_products(default_branch_id: int) -> None:
    from models.branch import BranchStock
    from models.order_item import OrderItem
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from models.purchase import Purchase
    from models.purchase_item import PurchaseItem
    from models.stock_movement import StockMovement

    engine = _branch_schema_engine()
    legacy_sqlite_unique = False
    if engine.dialect.name == "sqlite":
        legacy_sqlite_unique = any(
            tuple(item.get("column_names") or []) == ("tenant_id", "barcode")
            for item in inspect(engine).get_unique_constraints("product")
        )
    originals = Product.query.order_by(Product.id).all()
    for product in originals:
        group_id = product.catalog_group_id or str(uuid.uuid4())
        product.catalog_group_id = group_id
        branch_ids = _branch_ids_for_product(product.id, default_branch_id)
        primary_branch_id = int(product.branch_id or branch_ids[0])
        source_variants = ProductColorVariant.query.filter_by(product_id=product.id).all()
        branch_remaining = {
            branch_id: int(
                db.session.query(db.func.coalesce(db.func.sum(BranchStock.quantity), 0))
                .filter(BranchStock.product_id == product.id, BranchStock.branch_id == branch_id)
                .scalar()
                or 0
            )
            for branch_id in branch_ids
        }
        variant_allocations = {branch_id: {} for branch_id in branch_ids}
        for variant in source_variants:
            remaining = int(variant.quantity or 0)
            for branch_id in branch_ids:
                allocated = min(remaining, max(0, branch_remaining[branch_id]))
                variant_allocations[branch_id][variant.id] = allocated
                branch_remaining[branch_id] -= allocated
                remaining -= allocated
            if remaining > 0:
                variant_allocations[primary_branch_id][variant.id] = (
                    variant_allocations[primary_branch_id].get(variant.id, 0) + remaining
                )
        product.branch_id = primary_branch_id
        product.quantity = int(
            db.session.query(db.func.coalesce(db.func.sum(BranchStock.quantity), 0))
            .filter(BranchStock.product_id == product.id, BranchStock.branch_id == primary_branch_id)
            .scalar()
            or 0
        )

        for branch_id in branch_ids:
            if branch_id == primary_branch_id:
                local_product = product
            else:
                local_product = Product.query.filter_by(
                    catalog_group_id=group_id, branch_id=branch_id
                ).first()
                if not local_product:
                    local_product = _copy_scalar_row(
                        Product,
                        product,
                        tenant_id=None if legacy_sqlite_unique else product.tenant_id,
                        branch_id=branch_id,
                        catalog_group_id=group_id,
                        quantity=0,
                        opening_stock=0,
                    )

            if local_product.id == product.id:
                for variant in source_variants:
                    variant.quantity = variant_allocations[branch_id].get(variant.id, 0)
            else:
                for variant in source_variants:
                    local_variant = ProductColorVariant.query.filter_by(
                        product_id=local_product.id,
                        color_name=variant.color_name,
                    ).first()
                    allocated = variant_allocations[branch_id].get(variant.id, 0)
                    if local_variant:
                        local_variant.quantity = allocated
                    else:
                        _copy_scalar_row(
                            ProductColorVariant,
                            variant,
                            product_id=local_product.id,
                            quantity=allocated,
                        )

            stock = BranchStock.query.filter_by(branch_id=branch_id, product_id=product.id).first()
            if stock and local_product.id != product.id:
                duplicate = BranchStock.query.filter_by(
                    branch_id=branch_id, product_id=local_product.id
                ).first()
                if duplicate:
                    duplicate.quantity += int(stock.quantity or 0)
                    duplicate.opening_stock += int(stock.opening_stock or 0)
                    db.session.delete(stock)
                else:
                    stock.product_id = local_product.id
                local_product.quantity = int((duplicate or stock).quantity or 0)

            if local_product.id != product.id:
                OrderItem.query.filter(
                    OrderItem.product_id == product.id,
                    OrderItem.fulfillment_branch_id == branch_id,
                ).update({OrderItem.product_id: local_product.id}, synchronize_session=False)
                purchase_ids = [
                    row[0]
                    for row in db.session.query(Purchase.id).filter(Purchase.branch_id == branch_id).all()
                ]
                if purchase_ids:
                    PurchaseItem.query.filter(
                        PurchaseItem.product_id == product.id,
                        PurchaseItem.purchase_id.in_(purchase_ids),
                    ).update({PurchaseItem.product_id: local_product.id}, synchronize_session=False)
                    Purchase.query.filter(
                        Purchase.id.in_(purchase_ids), Purchase.product_id == product.id
                    ).update({Purchase.product_id: local_product.id}, synchronize_session=False)
                StockMovement.query.filter(
                    StockMovement.product_id == product.id,
                    StockMovement.branch_id == branch_id,
                ).update({StockMovement.product_id: local_product.id}, synchronize_session=False)
    db.session.flush()


def _localize_customers(default_branch_id: int) -> None:
    from models.customer import Customer
    from models.invoice import Invoice

    for customer in Customer.query.order_by(Customer.id).all():
        branch_ids = sorted({
            int(row[0])
            for row in db.session.query(Invoice.branch_id)
            .filter(Invoice.customer_id == customer.id, Invoice.branch_id.isnot(None))
            .distinct().all()
            if row[0]
        } or {default_branch_id})
        primary = int(customer.branch_id or branch_ids[0])
        customer.branch_id = primary
        for branch_id in branch_ids:
            if branch_id == primary:
                continue
            clone = _copy_scalar_row(Customer, customer, branch_id=branch_id)
            Invoice.query.filter(
                Invoice.customer_id == customer.id, Invoice.branch_id == branch_id
            ).update({Invoice.customer_id: clone.id}, synchronize_session=False)


def _localize_suppliers(default_branch_id: int) -> None:
    from models.purchase import Purchase
    from models.supplier import Supplier
    from models.supplier_payment import SupplierPayment

    for supplier in Supplier.query.order_by(Supplier.id).all():
        branch_ids = sorted({
            int(row[0])
            for row in db.session.query(Purchase.branch_id)
            .filter(Purchase.supplier_id == supplier.id, Purchase.branch_id.isnot(None))
            .distinct().all()
            if row[0]
        } or {default_branch_id})
        primary = int(supplier.branch_id or branch_ids[0])
        totals_by_branch = {}
        for branch_id in branch_ids:
            purchase_totals = (
                db.session.query(
                    db.func.coalesce(db.func.sum(
                        case(
                            (and_(Purchase.grand_total.isnot(None), Purchase.grand_total != 0), Purchase.grand_total),
                            else_=Purchase.total,
                        )
                    ), 0),
                    db.func.coalesce(db.func.sum(Purchase.paid_total), 0),
                )
                .filter(Purchase.supplier_id == supplier.id, Purchase.branch_id == branch_id)
                .first()
            )
            totals_by_branch[branch_id] = (int(purchase_totals[0] or 0), int(purchase_totals[1] or 0))
        purchase_debt = sum(value[0] for value in totals_by_branch.values())
        purchase_paid = sum(value[1] for value in totals_by_branch.values())
        extra_debt = int(supplier.total_debt or 0) - purchase_debt
        extra_paid = int(supplier.total_paid or 0) - purchase_paid
        supplier.branch_id = primary
        supplier.total_debt = totals_by_branch[primary][0] + extra_debt
        supplier.total_paid = totals_by_branch[primary][1] + extra_paid
        for branch_id in branch_ids:
            if branch_id == primary:
                continue
            clone = _copy_scalar_row(
                Supplier,
                supplier,
                branch_id=branch_id,
                opening_balance=0,
                total_debt=totals_by_branch[branch_id][0],
                total_paid=totals_by_branch[branch_id][1],
            )
            Purchase.query.filter(
                Purchase.supplier_id == supplier.id, Purchase.branch_id == branch_id
            ).update({Purchase.supplier_id: clone.id}, synchronize_session=False)
        SupplierPayment.query.filter(
            SupplierPayment.supplier_id == supplier.id,
            SupplierPayment.branch_id.is_(None),
        ).update({SupplierPayment.branch_id: primary}, synchronize_session=False)


def _localize_shipping_services(default_branch_id: int) -> None:
    from models.delivery_agent import DeliveryAgent
    from models.invoice import Invoice
    from models.shipping import ShippingCompany

    company_by_branch: dict[tuple[int, int], int] = {}
    for company in ShippingCompany.query.order_by(ShippingCompany.id).all():
        branch_ids = sorted({
            int(row[0])
            for row in db.session.query(Invoice.branch_id)
            .filter(Invoice.shipping_company_id == company.id, Invoice.branch_id.isnot(None))
            .distinct().all()
            if row[0]
        } or {default_branch_id})
        primary = int(company.branch_id or branch_ids[0])
        company.branch_id = primary
        company_by_branch[(company.id, primary)] = company.id
        for branch_id in branch_ids:
            if branch_id == primary:
                continue
            clone = _copy_scalar_row(
                ShippingCompany,
                company,
                branch_id=branch_id,
                access_token=None,
                username=None,
                password=None,
                opening_balance=0,
            )
            company_by_branch[(company.id, branch_id)] = clone.id
            Invoice.query.filter(
                Invoice.shipping_company_id == company.id, Invoice.branch_id == branch_id
            ).update({Invoice.shipping_company_id: clone.id}, synchronize_session=False)

    for agent in DeliveryAgent.query.order_by(DeliveryAgent.id).all():
        branch_ids = sorted({
            int(row[0])
            for row in db.session.query(Invoice.branch_id)
            .filter(Invoice.delivery_agent_id == agent.id, Invoice.branch_id.isnot(None))
            .distinct().all()
            if row[0]
        } or {default_branch_id})
        primary = int(agent.branch_id or branch_ids[0])
        agent.branch_id = primary
        for branch_id in branch_ids:
            if branch_id == primary:
                continue
            destination_company_id = company_by_branch.get(
                (int(agent.shipping_company_id), branch_id)
            ) if agent.shipping_company_id else None
            clone = _copy_scalar_row(
                DeliveryAgent,
                agent,
                branch_id=branch_id,
                shipping_company_id=destination_company_id,
                username=None,
                password=None,
                employee_id=None,
                total_orders=0,
                total_amount=0,
            )
            Invoice.query.filter(
                Invoice.delivery_agent_id == agent.id, Invoice.branch_id == branch_id
            ).update({Invoice.delivery_agent_id: clone.id}, synchronize_session=False)


def _run_scope_v2_data_migration() -> None:
    """Localize legacy rows without changing historical totals."""
    from models.branch import Branch

    default = Branch.query.filter_by(is_default=True).first() or Branch.query.order_by(Branch.id).first()
    if not default:
        return
    default_id = int(default.id)
    engine = _branch_schema_engine()
    from models.employee import Employee

    Employee.query.filter(Employee.role == "admin").update(
        {Employee.branch_id: None}, synchronize_session=False
    )
    Employee.query.filter(
        Employee.role != "admin", Employee.branch_id.is_(None)
    ).update({Employee.branch_id: default_id}, synchronize_session=False)

    # The legacy permission must not grant aggregate visibility to custom roles.
    if all(_table_exists(engine, name) for name in ("role_permissions", "roles", "permissions")):
        db.session.execute(text(
            "DELETE FROM role_permissions "
            "WHERE permission_id IN (SELECT id FROM permissions WHERE name = 'view_all_branches') "
            "AND role_id IN (SELECT id FROM roles WHERE name != 'admin')"
        ))

    # Derive child-ledger branches from their immutable parent document first.
    derived_updates = (
        "UPDATE invoice_payment_ledger SET branch_id = (SELECT branch_id FROM invoice WHERE invoice.id = invoice_payment_ledger.invoice_id) WHERE branch_id IS NULL",
        "UPDATE purchase_payment SET branch_id = (SELECT branch_id FROM purchase WHERE purchase.id = purchase_payment.purchase_id) WHERE branch_id IS NULL",
        "UPDATE shipping_payment SET branch_id = (SELECT branch_id FROM invoice WHERE invoice.id = shipping_payment.invoice_id) WHERE branch_id IS NULL AND invoice_id IS NOT NULL",
        "UPDATE trade_in_receipt SET branch_id = (SELECT branch_id FROM invoice WHERE invoice.id = trade_in_receipt.invoice_id) WHERE branch_id IS NULL",
    )
    for statement in derived_updates:
        table_name = statement.split()[1]
        if _table_exists(engine, table_name):
            db.session.execute(text(statement))

    if _table_exists(engine, "shipping_report"):
        import json
        from models.invoice import Invoice
        from models.shipping_report import ShippingReport

        for report in ShippingReport.query.filter(ShippingReport.branch_id.is_(None)).all():
            branch_id = getattr(getattr(report, "shipping_company", None), "branch_id", None)
            if not branch_id:
                try:
                    rows = json.loads(report.orders_data or "[]")
                except (TypeError, ValueError, json.JSONDecodeError):
                    rows = []
                for row in rows if isinstance(rows, list) else []:
                    raw_id = row.get("order_id") or row.get("id") if isinstance(row, dict) else None
                    if raw_id:
                        invoice_branch = db.session.query(Invoice.branch_id).filter(Invoice.id == raw_id).scalar()
                        if invoice_branch:
                            branch_id = invoice_branch
                            break
            report.branch_id = int(branch_id or default_id)

    _localize_products(default_id)
    _localize_customers(default_id)
    _localize_suppliers(default_id)
    _localize_shipping_services(default_id)

    # Remaining unambiguous/orphan rows belong to the historical default branch.
    for table_name in _BRANCH_OWNED_TABLES:
        if _table_exists(engine, table_name) and _column_exists(engine, table_name, "branch_id"):
            db.session.execute(
                text(f"UPDATE {table_name} SET branch_id = :branch_id WHERE branch_id IS NULL"),
                {"branch_id": default_id},
            )

    # Every branch must have a local cash box before branch mode is enabled.
    from models.treasury_account import TreasuryAccount

    for branch in Branch.query.filter_by(is_active=True).order_by(Branch.id).all():
        account = (
            TreasuryAccount.query.execution_options(skip_branch_scope=True)
            .filter_by(branch_id=branch.id, account_type="cash", is_active=True)
            .first()
        )
        if not account:
            db.session.add(TreasuryAccount(
                branch_id=branch.id,
                name=f"صندوق {branch.name}",
                account_type="cash",
                is_default=True,
                is_active=True,
            ))

    db.session.flush()


def _run_data_migration() -> None:
    from models.branch import Branch, BranchStock
    from models.employee import Employee
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product

    engine = _branch_schema_engine()
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
        # A tenant may already have localized per-branch products from the
        # independent-branch migration while still needing this newer shared
        # compatibility pass.  In that case creating a MAIN row from
        # ``product.quantity`` mirrors the existing branch stock and doubles
        # the shared catalogue total.  Bootstrap only products that have no
        # physical stock row anywhere; an existing row already owns the
        # quantity, even when it belongs to a non-default branch.
        existing_stock = BranchStock.query.filter_by(product_id=product.id).first()
        if existing_stock:
            continue
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

    if _table_exists(engine, "purchase") and _column_exists(engine, "purchase", "branch_id"):
        branch_code_select = "branch_code" if _column_exists(engine, "purchase", "branch_code") else "NULL AS branch_code"
        purchases = db.session.execute(
            text(f"SELECT id, {branch_code_select} FROM purchase WHERE branch_id IS NULL")
        ).mappings()
        for purchase in purchases:
            code = (purchase.get("branch_code") or "").strip().upper()
            branch = branch_by_code.get(code) if code else None
            db.session.execute(
                text("UPDATE purchase SET branch_id = :branch_id WHERE id = :purchase_id"),
                {
                    "branch_id": (branch or default_branch).id,
                    "purchase_id": purchase["id"],
                },
            )

    # Legacy shared mode still needs a stable internal owner branch because
    # financial validation now requires branch_id.  Reads remain unscoped in
    # that mode, so this backfill does not isolate or hide any records.
    for table_name in _BRANCH_OWNED_TABLES:
        if _table_exists(engine, table_name) and _column_exists(engine, table_name, "branch_id"):
            db.session.execute(
                text(f'UPDATE "{table_name}" SET branch_id = :branch_id WHERE branch_id IS NULL'),
                {"branch_id": int(default_branch.id)},
            )

    db.session.commit()

    for product in Product.query.all():
        total = (
            db.session.query(db.func.coalesce(db.func.sum(BranchStock.quantity), 0))
            .filter(BranchStock.product_id == product.id)
            .scalar()
        )
        product.quantity = int(total or 0)

    db.session.commit()
def get_default_branch():
    from models.branch import Branch

    # Schema initialization must not commit a partly posted financial command.
    if not getattr(g,"finance_operation",False):
        ensure_branch_schema()
    branch = Branch.query.filter_by(is_default=True, is_active=True).first()
    if branch:
        return branch
    return Branch.query.filter_by(is_active=True).order_by(Branch.id).first()
