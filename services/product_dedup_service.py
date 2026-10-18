"""Tenant-safe product duplicate discovery and explicit merge operations."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from sqlalchemy import inspect, or_

from extensions import db
from models.product import Product
from models.branch import BranchStock
from modules.wholesale.models.warehouse import WarehouseStock
from utils.activity_logger import log_activity


def normalize_product_text(value):
    value = unicodedata.normalize("NFKC", str(value or "")).lower()
    value = re.sub(r"[\u064b-\u065f\u0670]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _scope(tenant_id, branch_ids=None):
    q = Product.query.execution_options(skip_branch_scope=True).filter(Product.active.is_(True))
    if tenant_id is not None:
        q = q.filter(or_(Product.tenant_id == tenant_id, Product.tenant_id.is_(None)))
    if branch_ids:
        q = q.filter(or_(Product.branch_id.in_(branch_ids), Product.branch_id.is_(None)))
    return q


def duplicate_groups(tenant_id, branch_ids=None, limit=200):
    groups = defaultdict(list)
    for product in _scope(tenant_id, branch_ids).order_by(Product.id).limit(5000):
        value, kind = (normalize_product_text(product.barcode), "barcode") if product.barcode else (normalize_product_text(product.sku), "sku") if product.sku else (normalize_product_text(product.name), "name")
        if not value:
            continue
        groups[(product.tenant_id, product.branch_id, kind, value)].append(product)
    result = []
    for (effective_tenant, branch_id, kind, value), products in groups.items():
        if len(products) < 2:
            continue
        canonical = sorted(products, key=lambda p: (-(p.quantity or 0), p.created_at or 0, p.id))[0]
        result.append({"key": f"{kind}:{value}", "match_type": kind, "tenant_id": effective_tenant, "branch_id": branch_id, "canonical_id": canonical.id, "products": [{"id": p.id, "name": p.name, "sku": p.sku or "", "barcode": p.barcode or "", "quantity": p.quantity or 0, "buy_price": p.buy_price or 0, "canonical": p.id == canonical.id} for p in products]})
        if len(result) >= limit:
            break
    return result


def merge_products(canonical_id, duplicate_ids, tenant_id, employee_id=None):
    ids = {int(x) for x in duplicate_ids if str(x).isdigit()} - {int(canonical_id)}
    if not ids:
        raise ValueError("اختر منتجاً مكرراً واحداً على الأقل.")
    canonical = Product.query.execution_options(skip_branch_scope=True).filter(Product.id == canonical_id).with_for_update().first()
    duplicates = Product.query.execution_options(skip_branch_scope=True).filter(Product.id.in_(ids)).with_for_update().all()
    if not canonical or len(duplicates) != len(ids) or not canonical.active or any(not p.active for p in duplicates):
        raise ValueError("المنتج غير موجود أو تم دمجه مسبقاً.")
    different_branch = next((p for p in duplicates if p.branch_id is not None and canonical.branch_id is not None and p.branch_id != canonical.branch_id), None)
    if any(p.tenant_id != canonical.tenant_id for p in duplicates) or different_branch or (tenant_id is not None and canonical.tenant_id not in (None, tenant_id)):
        if different_branch:
            raise ValueError(f"لا يمكن الدمج: المنتج {different_branch.id} يتبع الفرع {different_branch.branch_id} بينما المنتج الأساسي يتبع الفرع {canonical.branch_id}.")
        raise ValueError("لا يمكن دمج منتجات من شركة مختلفة.")
    # Aggregate the two stock projections before moving foreign keys.
    for row in BranchStock.query.filter(BranchStock.product_id.in_(ids)).with_for_update().all():
        target = BranchStock.query.filter_by(branch_id=row.branch_id, product_id=canonical.id).with_for_update().first()
        if target:
            target.quantity = (target.quantity or 0) + (row.quantity or 0)
            target.opening_stock = (target.opening_stock or 0) + (row.opening_stock or 0)
            db.session.delete(row)
        else:
            row.product_id = canonical.id
    for row in WarehouseStock.query.filter(WarehouseStock.product_id.in_(ids)).with_for_update().all():
        target = WarehouseStock.query.filter_by(warehouse_id=row.warehouse_id, product_id=canonical.id).with_for_update().first()
        if target:
            for field in ("quantity", "opening_quantity", "reserved_quantity", "in_transit_quantity"):
                if hasattr(row, field) and hasattr(target, field):
                    setattr(target, field, (getattr(target, field) or 0) + (getattr(row, field) or 0))
            db.session.delete(row)
        else:
            row.product_id = canonical.id
    # Repoint every ordinary product reference discovered from the schema.
    tables = []
    for table in db.metadata.sorted_tables:
        if table.name in {"product", "branch_stock", "warehouse_stock"}:
            continue
        for column in table.columns:
            if column.name not in {"product_id", "destination_product_id"}:
                continue
            db.session.execute(table.update().where(column.in_(ids)).values({column.name: canonical.id}))
            tables.append(f"{table.name}.{column.name}")
    canonical.quantity = (canonical.quantity or 0) + sum(p.quantity or 0 for p in duplicates)
    canonical.opening_stock = (canonical.opening_stock or 0) + sum(p.opening_stock or 0 for p in duplicates)
    for duplicate in duplicates:
        duplicate.active = False
        duplicate.store_visible = False
    log_activity("merge", "inventory", "دمج منتجات مكررة", employee=employee_id, entity_type="product", entity_id=canonical.id, payload={"canonical_id": canonical.id, "duplicate_ids": sorted(ids), "updated_references": tables}, commit=False)
    return canonical, sorted(ids)
