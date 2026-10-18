from __future__ import annotations

from flask import g, session
from sqlalchemy import inspect, text

from extensions import db
from modules.installments import models  # noqa: F401


INSTALLMENT_PERMISSIONS = (
    ("view_installments", "عرض نظام الأقساط"),
    ("manage_installment_products", "إدارة منتجات وخطط الأقساط"),
    ("review_installment_applications", "مراجعة طلبات الأقساط"),
    ("approve_installment_applications", "الموافقة على طلبات الأقساط"),
    ("collect_installment_payments", "تحصيل دفعات الأقساط"),
    ("manage_installment_settings", "إدارة إعدادات الأقساط"),
    ("installments.view", "عرض نظام الأقساط"),
    ("installments.products.view", "عرض منتجات الأقساط"),
    ("installments.products.manage", "إدارة منتجات وخطط الأقساط"),
    ("installments.applications.view", "عرض طلبات الأقساط"),
    ("installments.applications.review", "مراجعة طلبات الأقساط"),
    ("installments.applications.approve", "اعتماد ورفض طلبات الأقساط"),
    ("installments.contracts.view", "عرض عقود الأقساط"),
    ("installments.contracts.manage", "إدارة عقود الأقساط"),
    ("installments.payments.view", "عرض دفعات الأقساط"),
    ("installments.payments.create", "تسجيل دفعات الأقساط"),
    ("installments.payments.reverse", "عكس دفعات الأقساط"),
    ("installments.reports.view", "عرض تقارير الأقساط"),
    ("installments.settings.manage", "إدارة إعدادات الأقساط"),
)


# SQLite does not add columns during create_all. Keep this map additive so old
# tenant databases can be upgraded safely whenever the module is opened.
ADDITIVE_COLUMNS = {
    # Compatibility columns used by the current Finora ORM. Some long-lived
    # tenant databases predate these core columns; without them even a narrow
    # Product/Customer/Invoice query cannot be materialized by SQLAlchemy.
    "product": {
        "branch_id": "INTEGER",
        "catalog_group_id": "VARCHAR(36)",
        "exchange_sale_price": "INTEGER",
        "store_visible": "BOOLEAN DEFAULT 1",
        "pos_visible": "BOOLEAN DEFAULT 1",
        "catalog_category": "VARCHAR(120)",
    },
    "customer": {
        "branch_id": "INTEGER",
        "tg_chat_id": "VARCHAR(64)",
        "is_blacklisted": "BOOLEAN NOT NULL DEFAULT 0",
        "blacklist_reason": "TEXT",
        "blacklisted_at": "DATETIME",
    },
    "invoice": {
        "return_branch_id": "INTEGER",
        "agent_note": "TEXT",
        "warehouse_id": "INTEGER",
        "currency": "VARCHAR(10) DEFAULT 'IQD'",
        "exchange_rate": "FLOAT DEFAULT 1.0",
        "payment_currency": "VARCHAR(10)",
        "sale_type": "VARCHAR(30)",
        "is_draft": "BOOLEAN DEFAULT 0",
        "deleted_at": "DATETIME",
        "source_module": "VARCHAR(40)",
        "invoice_no": "VARCHAR(80)",
        "shipping_fee": "INTEGER DEFAULT 0",
    },
    "invoice_payment_ledger": {
        "branch_id": "INTEGER",
        "tenant_id": "INTEGER",
        "currency": "VARCHAR(10)",
        "exchange_rate": "FLOAT",
        "source_module": "VARCHAR(40)",
        "note": "TEXT",
        "payment_method": "VARCHAR(40)",
        "treasury_account_id": "INTEGER",
    },
    "order_item": {
        "discount_value": "INTEGER DEFAULT 0",
        "warehouse_id": "INTEGER",
        "sale_mode": "VARCHAR(20) NOT NULL DEFAULT 'normal'",
        "trade_in_source_product_id": "INTEGER",
        "trade_in_source_product_name": "VARCHAR(150)",
    },
    "installment_applications": {
        "area": "VARCHAR(150)",
        "nearest_landmark": "VARCHAR(250)",
        "internal_notes": "TEXT",
        "assigned_employee_id": "INTEGER",
    },
    "installment_application_items": {
        "product_name_snapshot": "VARCHAR(180) NOT NULL DEFAULT ''",
        "sku_snapshot": "VARCHAR(100)",
        "main_image_snapshot": "VARCHAR(500)",
        "months_snapshot": "INTEGER NOT NULL DEFAULT 1",
        "pricing_mode_snapshot": "VARCHAR(20) NOT NULL DEFAULT 'percentage'",
        "markup_snapshot": "NUMERIC(9, 4)",
    },
    "installment_application_activities": {
        "metadata_json": "TEXT",
    },
    "installment_contracts": {
        "first_due_date": "DATE",
        "financed_amount": "INTEGER NOT NULL DEFAULT 0",
        "number_of_installments": "INTEGER NOT NULL DEFAULT 0",
        "created_by_id": "INTEGER",
        "updated_at": "DATETIME",
    },
    "installment_schedules": {
        "remaining_amount": "INTEGER NOT NULL DEFAULT 0",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
    },
    "installment_payments": {
        "customer_id": "INTEGER",
        "account_id": "INTEGER",
        "paid_at": "DATETIME",
        "created_at": "DATETIME",
    },
    "installment_settings": {
        "logo_path": "VARCHAR(500)",
        "banner_path": "VARCHAR(500)",
        "contact_phone": "VARCHAR(30)",
        "whatsapp": "VARCHAR(30)",
        "address": "VARCHAR(300)",
        "map_url": "VARCHAR(500)",
        "terms": "TEXT",
        "second_phone_required": "BOOLEAN NOT NULL DEFAULT 0",
        "documents_config_json": "TEXT",
        "guarantor_required": "BOOLEAN NOT NULL DEFAULT 0",
        "employment_required": "BOOLEAN NOT NULL DEFAULT 0",
        "allowed_durations_json": "TEXT",
        "minimum_down_payment_percentage": "NUMERIC(6, 3) NOT NULL DEFAULT 0",
        "bank_account_id": "INTEGER",
        "fee_account_id": "INTEGER",
        "reservation_policy": "VARCHAR(30) NOT NULL DEFAULT 'on_approval'",
        "allow_advance_payment": "BOOLEAN NOT NULL DEFAULT 1",
    },
}


def _add_missing_columns(bind) -> None:
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    for table_name, columns in ADDITIVE_COLUMNS.items():
        if table_name not in tables:
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, ddl in columns.items():
            if column_name not in existing:
                db.session.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {ddl}'))

    # Backfill derived values introduced after the first release.
    if "installment_schedules" in tables:
        db.session.execute(text(
            "UPDATE installment_schedules SET remaining_amount = amount - paid_amount "
            "WHERE remaining_amount = 0 AND amount > paid_amount"
        ))
    if "installment_contracts" in tables:
        db.session.execute(text(
            "UPDATE installment_contracts SET financed_amount = remaining_amount + paid_amount "
            "WHERE financed_amount = 0"
        ))
        db.session.execute(text(
            "UPDATE installment_contracts SET updated_at = created_at WHERE updated_at IS NULL"
        ))


def _ensure_local_tenant_row() -> None:
    """Mirror the session tenant id into legacy physical tenant databases.

    Finora routes data to one SQLite file per tenant, while several ORM models
    still carry a foreign key to the local ``tenant`` table. Older files may
    have that table but no row, so inserts would otherwise fail FK checks.
    """
    tenant_id = session.get("tenant_id")
    if not tenant_id:
        return
    from models.tenant import Tenant

    if Tenant.query.filter_by(id=int(tenant_id)).first():
        return
    slug = str(getattr(g, "tenant", None) or session.get("tenant_slug") or f"tenant-{tenant_id}")
    db.session.add(Tenant(
        id=int(tenant_id),
        name=slug,
        business_type=str(session.get("business_type") or "general"),
        plan_key=str(session.get("plan_key") or "basic"),
        plan_name="خطة الشركة",
        monthly_price=0,
        is_active=True,
        subdomain=slug[:100],
    ))
    db.session.flush()


def ensure_installment_schema() -> None:
    """Additive, idempotent migration for the active tenant database."""
    bind = db.session.get_bind()
    models.InstallmentProduct.metadata.create_all(bind=bind, checkfirst=True)
    _add_missing_columns(bind)
    db.session.flush()
    _ensure_local_tenant_row()
    table_names = set(inspect(bind).get_table_names())
    required = {
        "installment_products", "installment_plans", "installment_applications",
        "installment_contracts", "installment_schedules", "installment_payments",
        "installment_settings", "installment_customer_accounts",
    }
    missing = required - table_names
    if missing:
        raise RuntimeError(f"Installment schema migration incomplete: {sorted(missing)}")

    from models.role import Permission, Role

    for name, description in INSTALLMENT_PERMISSIONS:
        if not Permission.query.filter_by(name=name).first():
            db.session.add(Permission(name=name, description=description))
    db.session.flush()
    admin_role = Role.query.filter_by(name="admin").first()
    if admin_role:
        existing = {permission.name for permission in admin_role.permissions}
        for permission in Permission.query.filter(Permission.name.in_([p[0] for p in INSTALLMENT_PERMISSIONS])).all():
            if permission.name not in existing:
                admin_role.permissions.append(permission)
    db.session.commit()
