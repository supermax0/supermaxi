"""Branch-local product catalog helpers.

Products in different branches intentionally share only ``catalog_group_id``.
Their prices, metadata, variants and future edits stay independent.
"""
from __future__ import annotations

import uuid

from extensions import db
from models.product import Product
from models.product_color_variant import ProductColorVariant


def barcode_conflict(branch_id: int, barcode: str | None, *, exclude_product_id: int | None = None) -> Product | None:
    normalized = str(barcode or "").strip()
    if not normalized:
        return None
    query = (
        Product.query.execution_options(skip_branch_scope=True)
        .filter(Product.branch_id == int(branch_id), Product.barcode == normalized)
    )
    if exclude_product_id:
        query = query.filter(Product.id != int(exclude_product_id))
    return query.first()


def product_for_branch(source: Product, branch_id: int, *, create: bool = True) -> Product | None:
    """Return the local catalog copy for ``branch_id``, cloning when requested."""
    branch_id = int(branch_id)
    if int(getattr(source, "branch_id", 0) or 0) == branch_id:
        return source

    group_id = source.catalog_group_id or str(uuid.uuid4())
    source.catalog_group_id = group_id
    existing = (
        Product.query.execution_options(skip_branch_scope=True)
        .filter_by(catalog_group_id=group_id, branch_id=branch_id)
        .first()
    )
    if existing or not create:
        return existing

    duplicate_barcode = barcode_conflict(branch_id, source.barcode)
    if duplicate_barcode:
        raise ValueError(
            f"الباركود «{source.barcode}» مستخدم لمنتج آخر في الفرع المستلم"
        )

    values = {}
    excluded = {"id", "branch_id", "quantity", "opening_stock", "created_at"}
    for column in Product.__table__.columns:
        if column.name not in excluded:
            values[column.name] = getattr(source, column.name, None)
    values.update(
        branch_id=branch_id,
        catalog_group_id=group_id,
        quantity=0,
        opening_stock=0,
    )
    # Older SQLite tenant files may still carry the former
    # UNIQUE(tenant_id, barcode) index, which SQLite cannot drop in place.
    # Tenant isolation is database-level there, so a null legacy tenant key is
    # safe while branch_id remains the authoritative owner.
    try:
        from sqlalchemy import inspect

        bind = db.session.get_bind()
        if bind.dialect.name == "sqlite" and any(
            tuple(item.get("column_names") or []) == ("tenant_id", "barcode")
            for item in inspect(bind).get_unique_constraints("product")
        ):
            values["tenant_id"] = None
    except Exception:
        pass
    clone = Product(**values)
    db.session.add(clone)
    db.session.flush()

    variants = (
        ProductColorVariant.query
        .filter_by(product_id=source.id)
        .order_by(ProductColorVariant.id.asc())
        .all()
    )
    for variant in variants:
        db.session.add(
            ProductColorVariant(
                product_id=clone.id,
                color_name=variant.color_name,
                quantity=0,
                buy_price=variant.buy_price,
                sale_price=variant.sale_price,
            )
        )
    db.session.flush()
    return clone
