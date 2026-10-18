"""POS catalog search and product-card serialization (shared by web POS and API)."""
from __future__ import annotations

import json

from models.customer import Customer
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from utils.branch_context import current_branch_id
from utils.branch_migration import get_default_branch
from utils.branch_mode import independent_branches_enabled
from utils.branch_stock_service import get_branch_stock, get_total_stock
from utils.cash_calculations import _effective_paid_amount
from utils.order_shipping import is_shipping_item
from utils.product_color_service import colors_for_product_dict, colors_quantity_total
from utils.product_schema_guard import ensure_customer_blacklist_columns
from utils.trade_in_service import employee_can_access_replacement_product, product_sale_options


def shared_catalog_mode() -> bool:
    return not independent_branches_enabled()


def parse_product_meta(product) -> dict:
    raw = getattr(product, "meta_json", None)
    if not raw:
        return {}
    try:
        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def product_bootstrap_dict(product) -> dict:
    from models.branch import BranchStock

    meta = parse_product_meta(product)
    branch_total = get_total_stock(product.id)
    has_branch_stock = BranchStock.query.filter_by(product_id=product.id).first() is not None
    total_qty = branch_total if has_branch_stock else int(product.quantity or 0)
    product_branch_id = int(product.branch_id) if product.branch_id else None
    stock_branch_id = product_branch_id or current_branch_id()
    if not stock_branch_id:
        default_branch = get_default_branch()
        stock_branch_id = default_branch.id if default_branch else None
    display_qty = get_branch_stock(stock_branch_id, product.id) if has_branch_stock and stock_branch_id else total_qty
    color_payload = colors_for_product_dict(product)
    if color_payload.get("has_colors"):
        display_qty = colors_quantity_total(color_payload.get("colors"))
        total_qty = display_qty
    payload = {
        "id": product.id,
        "catalog_group_id": product.catalog_group_id or "",
        "branch_id": product_branch_id,
        "name": product.name,
        "sku": product.sku or "",
        "barcode": product.barcode or "",
        "sale_price": product.sale_price or 0,
        "price": product.sale_price or 0,
        "quantity": display_qty,
        "total_quantity": total_qty,
        "image_url": product.image_url or "",
        "low_stock_threshold": product.low_stock_threshold or 5,
        "category": (meta.get("category") or "").strip(),
        "store_badge": (meta.get("store_badge") or "").strip(),
        "sell_from_all_branches": False,
    }
    payload.update(color_payload)
    payload.update(product_sale_options(product))
    return payload


def catalog_key(product) -> str:
    """Legacy barcode/SKU identity used alongside the stable catalog group.

    Prefer barcode/SKU over ``catalog_group_id``: some legacy migrations assigned
    each branch copy a different group id, which made the same product appear
    once per branch when group was preferred first.
    """
    barcode = str(getattr(product, "barcode", "") or "").strip().casefold()
    if barcode:
        return f"barcode:{barcode}"
    sku = str(getattr(product, "sku", "") or "").strip().casefold()
    if sku:
        return f"sku:{sku}"
    group_id = str(getattr(product, "catalog_group_id", "") or "").strip()
    if group_id:
        return f"group:{group_id}"
    return f"product:{int(getattr(product, 'id', 0) or 0)}"


def shared_catalog_groups(products) -> list[list[Product]]:
    """Keep linked branch copies together even when one copy's barcode changes.

    Group IDs are stable across edits. A legacy barcode/SKU can link families
    only when their branches do not overlap. Reused barcodes must never hide
    different products in the same branch or combine their stock.
    """
    products = list(products or [])
    parents = list(range(len(products)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    stable = {}
    legacy = {}
    for index, product in enumerate(products):
        group_id = str(getattr(product, "catalog_group_id", "") or "").strip()
        if group_id:
            if group_id in stable:
                parents[root(index)] = root(stable[group_id])
            else:
                stable[group_id] = index
        key = catalog_key(product)
        if key.startswith(("barcode:", "sku:")):
            legacy.setdefault(key, []).append(index)

    # Establish explicit families first, then evaluate the whole legacy bucket.
    # Pairwise matching could otherwise merge two products through a third copy.
    family_members = {}
    for index in range(len(products)):
        family_members.setdefault(root(index), []).append(index)
    for key, indices in sorted(legacy.items()):
        candidates = {root(index) for index in indices}
        if len(candidates) < 2:
            continue
        branch_owners = {}
        skus = set()
        ambiguous = False
        for family in candidates:
            for index in family_members[family]:
                product = products[index]
                branch = getattr(product, "branch_id", None)
                if branch in branch_owners and branch_owners[branch] != family:
                    ambiguous = True
                    break
                branch_owners[branch] = family
                sku = str(getattr(product, "sku", "") or "").strip().casefold()
                if sku:
                    skus.add(sku)
            if ambiguous:
                break
        if ambiguous or (key.startswith("barcode:") and len(skus) > 1):
            continue
        representative = min(candidates)
        for family in candidates:
            parents[family] = representative
            if family != representative:
                family_members[representative].extend(family_members.pop(family))
    groups = {}
    for index, product in enumerate(products):
        groups.setdefault(root(index), []).append(product)
    return list(groups.values())


def shared_catalog_products(products: list[Product]) -> list[dict]:
    from models.branch import BranchStock

    rows: list[dict] = []
    for members in shared_catalog_groups(products):
        members.sort(key=lambda p: (int(p.branch_id or 0), int(p.id)))
        representative = members[0]
        row = product_bootstrap_dict(representative)
        member_ids = [int(p.id) for p in members]
        stock_rows = BranchStock.query.filter(BranchStock.product_id.in_(member_ids)).all()
        total_qty = sum(int(stock.quantity or 0) for stock in stock_rows)
        if not stock_rows:
            total_qty = sum(int(product.quantity or 0) for product in members)
        if row.get("has_colors"):
            total_qty = colors_quantity_total(row.get("colors"))
        branch_products: dict[str, int] = {}
        for product in members:
            if product.branch_id:
                branch_products[str(int(product.branch_id))] = int(product.id)
        for stock in stock_rows:
            branch_products.setdefault(str(int(stock.branch_id)), int(stock.product_id))
        row.update(
            quantity=total_qty,
            total_quantity=total_qty,
            catalog_group_id=representative.catalog_group_id or "",
            branch_products=branch_products,
        )
        rows.append(row)
    return sorted(rows, key=lambda row: (str(row.get("name") or "").casefold(), int(row["id"])))


def pos_catalog_products(products: list[Product]) -> list[dict]:
    return shared_catalog_products(products)


def catalog_family(product: Product) -> list[Product]:
    group_id = str(product.catalog_group_id or "").strip()
    if not group_id:
        return [product]
    return (
        Product.query.execution_options(skip_branch_scope=True)
        .filter(Product.catalog_group_id == group_id, Product.active.is_(True))
        .order_by(Product.id)
        .all()
    )


def search_pos_customers(employee, query: str, *, branch_id=None, limit: int = 15, _snapshot=False) -> list[dict]:
    q = (query or "").strip()
    if not q and not _snapshot:
        return []
    ensure_customer_blacklist_columns()
    customer_query = Customer.query
    if employee and employee.role == "admin":
        customer_query = customer_query.execution_options(skip_branch_scope=True)
    filters = [] if _snapshot else [
        Customer.name.contains(q) | Customer.phone.contains(q) | Customer.phone2.contains(q)
    ]
    if not shared_catalog_mode() and branch_id:
        filters.insert(0, Customer.branch_id == branch_id)
    customer_query = customer_query.filter(*filters).order_by(Customer.id)
    customers = customer_query.all() if _snapshot else customer_query.limit(max(1, min(int(limit or 15), 50))).all()
    msg = "هذا الزبون في القائمة السوداء — لا يُسمح بالتعامل معه."
    return [
        {
            "id": c.id,
            "name": c.name,
            "phone": c.phone,
            "phone2": c.phone2 or "",
            "city": c.city or "بغداد",
            "province": c.city or "",
            "address": c.address or "",
            "blacklisted": bool(getattr(c, "is_blacklisted", False)),
            "blacklist_message": msg if getattr(c, "is_blacklisted", False) else "",
            "branch_id": c.branch_id,
        }
        for c in customers
    ]


def search_pos_products(employee, query: str, *, branch_id=None, limit: int = 20) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []
    product_query = Product.query
    if employee and employee.role == "admin":
        product_query = product_query.execution_options(skip_branch_scope=True)
    barcode_filters = [
        Product.barcode == q,
        Product.active.is_(True),
        Product.pos_visible.isnot(False),
    ]
    if not shared_catalog_mode() and branch_id:
        barcode_filters.insert(0, Product.branch_id == branch_id)
    barcode_products = product_query.filter(*barcode_filters).all()
    if barcode_products:
        products = {}
        for product in barcode_products:
            if employee_can_access_replacement_product(employee, product):
                for member in catalog_family(product):
                    products[member.id] = member
        rows = pos_catalog_products(list(products.values()))
        for row in rows:
            # A shared legacy barcode requires a product choice, not auto-add.
            row["is_barcode"] = len(rows) == 1
        return rows

    name_filters = [
        Product.active.is_(True),
        Product.pos_visible.isnot(False),
        Product.name.contains(q),
    ]
    if not shared_catalog_mode() and branch_id:
        name_filters.insert(0, Product.branch_id == branch_id)
    products = product_query.filter(*name_filters).limit(max(1, min(int(limit or 20), 50))).all()
    products = [
        product
        for product in products
        if employee_can_access_replacement_product(employee, product)
    ]
    rows = []
    for row in pos_catalog_products(products):
        row["is_barcode"] = False
        rows.append(row)
    return rows


def _invoice_items_summary(invoice: Invoice, *, max_items: int = 8) -> list[dict]:
    rows = []
    for item in OrderItem.query.filter_by(invoice_id=invoice.id).all():
        if is_shipping_item(item):
            continue
        rows.append(
            {
                "product_id": item.product_id,
                "name": item.product_name,
                "quantity": int(item.quantity or 0),
                "unit_price": int(item.price or 0),
                "line_total": int(item.total or 0),
            }
        )
        if len(rows) >= max_items:
            break
    return rows


def serialize_pos_order(invoice: Invoice, *, include_items: bool = True) -> dict:
    customer = getattr(invoice, "customer", None)
    paid = int(_effective_paid_amount(invoice) or 0)
    total = int(invoice.total or 0)
    payload = {
        "id": invoice.id,
        "order_id": invoice.id,
        "customer_id": invoice.customer_id,
        "customer_name": invoice.customer_name,
        "phone": getattr(customer, "phone", "") or "",
        "province": getattr(customer, "city", "") or "",
        "address": getattr(customer, "address", "") or "",
        "status": invoice.status,
        "payment_status": invoice.payment_status,
        "total": total,
        "paid": paid,
        "remaining": max(0, total - paid),
        "branch_id": invoice.branch_id,
        "date": invoice.created_at.strftime("%Y-%m-%d %H:%M") if invoice.created_at else "",
        "note": invoice.note or "",
    }
    if include_items:
        payload["items"] = _invoice_items_summary(invoice)
    return payload


def recent_pos_orders(employee, *, limit: int = 20) -> list[dict]:
    query = Invoice.query
    if employee and employee.role == "admin":
        query = query.execution_options(skip_branch_scope=True)
    rows = query.order_by(Invoice.created_at.desc()).limit(max(1, min(int(limit or 20), 50))).all()
    return [serialize_pos_order(row) for row in rows]
