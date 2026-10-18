from __future__ import annotations

import json
from datetime import datetime

from flask import g, has_request_context

from extensions import db
from models.branch import Branch, BranchStock
from models.order_item import OrderItem
from models.product import Product
from models.trade_in_receipt import TradeInReceipt
from utils.branch_stock_service import (
    BranchStockError,
    deduct_stock,
    receive_stock,
)
from utils.tenant_feature_flags import tenant_feature_enabled


SALE_MODE_NORMAL = "normal"
SALE_MODE_EXCHANGE = "exchange"
VALID_SALE_MODES = {SALE_MODE_NORMAL, SALE_MODE_EXCHANGE}

REPLACEMENT_PRODUCT_NAME = "استبدال"
REPLACEMENT_PRODUCT_BARCODE = "__FINORA_TRADE_IN_REPLACEMENT__"
REPLACEMENT_PRODUCT_INITIAL_SALE_PRICE = 15_000


class TradeInError(ValueError):
    pass


def _clean_mode(value) -> str:
    mode = str(value or SALE_MODE_NORMAL).strip().lower()
    aliases = {
        "بيع": SALE_MODE_NORMAL,
        "عادي": SALE_MODE_NORMAL,
        "بيع عادي": SALE_MODE_NORMAL,
        "استبدال": SALE_MODE_EXCHANGE,
        "بيع استبدال": SALE_MODE_EXCHANGE,
        "trade_in": SALE_MODE_EXCHANGE,
        "trade-in": SALE_MODE_EXCHANGE,
    }
    return aliases.get(mode, mode)


def product_sale_options(product: Product) -> dict:
    exchange_price = int(getattr(product, "exchange_sale_price", 0) or 0)
    feature_enabled = tenant_feature_enabled("trade_in_sales", default=False)
    exchange_enabled = feature_enabled and exchange_price > 0
    return {
        "exchange_sale_price": exchange_price if exchange_enabled else None,
        "has_exchange_sale": exchange_enabled,
        "trade_in_sales_enabled": feature_enabled,
        "sale_options": [
            {
                "mode": SALE_MODE_NORMAL,
                "label": "بيع",
                "price": int(product.sale_price or 0),
            },
            *(
                [
                    {
                        "mode": SALE_MODE_EXCHANGE,
                        "label": "استبدال",
                        "price": exchange_price,
                    }
                ]
                if exchange_enabled
                else []
            ),
        ],
    }


def resolve_sale_selection(
    product: Product,
    raw: dict,
    *,
    allow_custom_price: bool = False,
    customer_city: str | None = None,
) -> tuple[str, int, Product | None]:
    from utils.product_region_pricing import resolve_region_sale_price

    mode = _clean_mode(raw.get("sale_mode") or raw.get("sale_type"))
    if mode not in VALID_SALE_MODES:
        raise TradeInError("نوع العملية غير صالح")

    source_product = None
    variant_color = (raw.get("color") or raw.get("variant_color") or "").strip() or None
    from utils.product_options import option_config, validate_selection
    if option_config(product).get("axes"):
        from utils.product_color_service import ProductColorError
        try:
            variant_color = validate_selection(product, variant_color or "", raw.get("variant_id"))
        except ProductColorError as exc:
            raise TradeInError(str(exc)) from exc
    if mode == SALE_MODE_EXCHANGE:
        if not tenant_feature_enabled("trade_in_sales", default=False):
            raise TradeInError("ميزة الاستبدال غير مفعّلة لهذه الشركة")
        exchange_price = int(getattr(product, "exchange_sale_price", 0) or 0)
        if exchange_price <= 0:
            raise TradeInError(f"الاستبدال غير مفعّل للمنتج: {product.name}")
        price = exchange_price
    else:
        price = resolve_region_sale_price(
            product,
            customer_city,
            color_name=variant_color,
        )

    if allow_custom_price:
        try:
            custom_price = int(float(raw.get("price") or 0))
        except (TypeError, ValueError):
            custom_price = 0
        if custom_price > 0:
            price = custom_price
    if price <= 0:
        raise TradeInError(f"سعر المنتج غير صالح: {product.name}")
    return mode, price, source_product


def is_replacement_product(product: Product | None) -> bool:
    if not product:
        return False
    if (product.barcode or "") == REPLACEMENT_PRODUCT_BARCODE:
        return True
    try:
        meta = json.loads(product.meta_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        meta = {}
    return bool(isinstance(meta, dict) and meta.get("trade_in_replacement_product"))


def employee_can_access_replacement_product(employee, product: Product | None) -> bool:
    """The internal replacement stock item is visible and sellable by admins only."""
    return not is_replacement_product(product) or (
        employee is not None and getattr(employee, "role", None) == "admin"
    )


def _merge_replacement_product_duplicates(session_obj, products: list[Product]) -> Product:
    """Keep one system product and fold duplicate stock into it without deleting audit data."""
    canonical = sorted(
        products,
        key=lambda row: (not bool(getattr(row, "active", False)), int(row.id or 0)),
    )[0]
    duplicates = [row for row in products if row.id != canonical.id]
    if not duplicates:
        return canonical

    product_ids = [row.id for row in products if row.id]
    stock_rows = (
        session_obj.query(BranchStock)
        .filter(BranchStock.product_id.in_(product_ids))
        .all()
    )
    rows_by_product: dict[int, list[BranchStock]] = {}
    for row in stock_rows:
        rows_by_product.setdefault(int(row.product_id), []).append(row)

    branch_totals: dict[int, int] = {}
    branch_opening: dict[int, int] = {}
    unassigned_quantity = 0
    total_product_quantity = sum(max(0, int(row.quantity or 0)) for row in products)
    for product in products:
        rows = rows_by_product.get(int(product.id), [])
        row_total = sum(max(0, int(row.quantity or 0)) for row in rows)
        for row in rows:
            branch_id = int(row.branch_id)
            branch_totals[branch_id] = branch_totals.get(branch_id, 0) + max(
                0, int(row.quantity or 0)
            )
            branch_opening[branch_id] = branch_opening.get(branch_id, 0) + max(
                0, int(row.opening_stock or 0)
            )
        unassigned_quantity += max(0, int(product.quantity or 0) - row_total)

    if unassigned_quantity:
        default_branch = (
            session_obj.query(Branch)
            .order_by(Branch.is_default.desc(), Branch.id.asc())
            .first()
        )
        if default_branch:
            branch_totals[int(default_branch.id)] = (
                branch_totals.get(int(default_branch.id), 0) + unassigned_quantity
            )

    canonical_stock_by_branch = {
        int(row.branch_id): row
        for row in rows_by_product.get(int(canonical.id), [])
    }
    for branch_id, quantity in branch_totals.items():
        target = canonical_stock_by_branch.get(branch_id)
        if target is None:
            target = BranchStock(
                branch_id=branch_id,
                product_id=canonical.id,
                quantity=0,
                opening_stock=0,
                low_stock_threshold=int(canonical.low_stock_threshold or 0),
            )
            session_obj.add(target)
            canonical_stock_by_branch[branch_id] = target
        target.quantity = quantity
        target.opening_stock = branch_opening.get(branch_id, 0)

    duplicate_ids = [row.id for row in duplicates if row.id]
    if duplicate_ids:
        session_obj.query(TradeInReceipt).filter(
            TradeInReceipt.replacement_product_id.in_(duplicate_ids)
        ).update(
            {TradeInReceipt.replacement_product_id: canonical.id},
            synchronize_session=False,
        )

    for duplicate in duplicates:
        for row in rows_by_product.get(int(duplicate.id), []):
            session_obj.delete(row)
        duplicate.quantity = 0
        duplicate.active = False
        duplicate.barcode = f"{REPLACEMENT_PRODUCT_BARCODE}__ARCHIVED__{duplicate.id}"

    if branch_totals:
        canonical.quantity = sum(branch_totals.values())
    else:
        canonical.quantity = total_product_quantity
    session_obj.flush()
    return canonical


def ensure_replacement_product_with_session(
    session_obj,
    *,
    tenant_id: int | None = None,
    branch_id: int | None = None,
) -> Product:
    query = session_obj.query(Product).execution_options(skip_branch_scope=True).filter_by(barcode=REPLACEMENT_PRODUCT_BARCODE)
    if tenant_id is not None:
        query = query.filter(Product.tenant_id == tenant_id)
    if branch_id is not None:
        # Legacy system products may be unassigned while their real stock is
        # already owned by this branch. Reuse that evidence, not a new SKU.
        recorded_stock = session_obj.query(BranchStock.id).filter(
            BranchStock.product_id == Product.id, BranchStock.branch_id == int(branch_id)
        ).exists()
        unlocated = db.and_(Product.branch_id.is_(None), recorded_stock)
        active_branches = session_obj.query(Branch.id).filter(Branch.is_active.is_(True)).all()
        if len(active_branches) == 1 and active_branches[0].id == int(branch_id):
            # Before branch stock existed, the sole branch owned the legacy
            # system product. With multiple branches, require recorded stock.
            any_stock = session_obj.query(BranchStock.id).filter(
                BranchStock.product_id == Product.id
            ).exists()
            unlocated = db.and_(Product.branch_id.is_(None), db.or_(recorded_stock, ~any_stock))
        query = query.filter(db.or_(Product.branch_id == int(branch_id),
                                   unlocated))
    products = query.order_by(Product.id.asc()).all()
    product = (
        _merge_replacement_product_duplicates(session_obj, products)
        if products
        else None
    )
    if product:
        if product.name != REPLACEMENT_PRODUCT_NAME:
            product.name = REPLACEMENT_PRODUCT_NAME
        product.active = True
        product.store_visible = False
        return product
    product = Product(
        tenant_id=tenant_id,
        branch_id=branch_id,
        name=REPLACEMENT_PRODUCT_NAME,
        barcode=REPLACEMENT_PRODUCT_BARCODE,
        buy_price=0,
        sale_price=REPLACEMENT_PRODUCT_INITIAL_SALE_PRICE,
        exchange_sale_price=None,
        opening_stock=0,
        quantity=0,
        active=True,
        store_visible=False,
        low_stock_threshold=0,
        description="منتج نظامي ثابت لتجميع الكميات المستلمة من عمليات الاستبدال.",
        meta_json=json.dumps(
            {
                "trade_in_replacement_product": True,
                "internal_only": True,
            },
            ensure_ascii=False,
        ),
    )
    session_obj.add(product)
    session_obj.flush()
    return product


def get_or_create_replacement_product(*, tenant_id: int | None = None, branch_id: int | None = None) -> Product:
    return ensure_replacement_product_with_session(
        db.session,
        tenant_id=tenant_id,
        branch_id=branch_id,
    )


def ensure_pending_receipt(order_item: OrderItem) -> TradeInReceipt | None:
    if _clean_mode(getattr(order_item, "sale_mode", None)) != SALE_MODE_EXCHANGE:
        return None
    receipt = TradeInReceipt.query.filter_by(order_item_id=order_item.id).first()
    if receipt:
        return receipt
    receipt = TradeInReceipt(
        invoice_id=order_item.invoice_id,
        order_item_id=order_item.id,
        source_product_id=None,
        source_product_name=REPLACEMENT_PRODUCT_NAME,
        branch_id=getattr(getattr(order_item, "invoice", None), "branch_id", None),
        quantity=max(1, int(order_item.quantity or 1)),
        status="pending",
    )
    db.session.add(receipt)
    db.session.flush()
    return receipt


def sync_trade_in_receipts(invoice, *, paid_override: bool = False) -> int:
    """Create pending records and receive them exactly once when fully paid."""
    if not invoice or not getattr(invoice, "id", None):
        return 0
    items = OrderItem.query.filter_by(invoice_id=invoice.id).all()
    receipts = [
        receipt
        for receipt in (ensure_pending_receipt(item) for item in items)
        if receipt is not None
    ]
    if not paid_override and (getattr(invoice, "payment_status", None) or "").strip() != "مسدد":
        return 0

    tenant_id = getattr(invoice, "tenant_id", None)
    if tenant_id is None and getattr(invoice, "customer", None) is not None:
        tenant_id = getattr(invoice.customer, "tenant_id", None)
    # A tenant database already isolates the company and stores this system
    # product with tenant_id=NULL. Reusing the invoice tenant id here created
    # extra replacement products instead of incrementing the existing one.
    replacement_tenant_id = (
        None
        if has_request_context() and getattr(g, "tenant", None)
        else tenant_id
    )
    branch_id = getattr(invoice, "branch_id", None)
    if not branch_id:
        # Migrations run at tenant initialization, never inside a partially
        # posted payment. Resolving a legacy invoice's default is read-only.
        default_branch = Branch.query.filter_by(is_default=True, is_active=True).first()
        if not default_branch:
            default_branch = Branch.query.filter_by(is_active=True).order_by(Branch.id).first()
        branch_id = default_branch.id if default_branch else None
    replacement = get_or_create_replacement_product(
        tenant_id=replacement_tenant_id,
        branch_id=branch_id,
    )
    received = 0
    for receipt in receipts:
        changed = (
            db.session.query(TradeInReceipt)
            .filter(
                TradeInReceipt.id == receipt.id,
                TradeInReceipt.status == "pending",
            )
            .update(
                {
                    TradeInReceipt.status: "received",
                    TradeInReceipt.replacement_product_id: replacement.id,
                    TradeInReceipt.branch_id: branch_id,
                    TradeInReceipt.received_at: datetime.utcnow(),
                    TradeInReceipt.reversed_at: None,
                },
                synchronize_session=False,
            )
        )
        if changed != 1:
            continue
        qty = max(1, int(receipt.quantity or 1))
        if branch_id:
            receive_stock(int(branch_id), replacement.id, qty, audit_context={
                "source_type": "trade_in_receipt", "source_id": receipt.id,
                "source_line_id": receipt.order_item_id, "invoice_id": invoice.id,
                "reason": "استلام قطع الاستبدال بعد تسديد الفاتورة",
            })
        else:
            replacement.quantity = int(replacement.quantity or 0) + qty
        received += qty
    db.session.flush()
    return received


def reverse_trade_in_receipt(receipt: TradeInReceipt) -> int:
    """Explicitly return an old item to the customer and reverse its stock."""
    if not receipt:
        raise TradeInError("سجل الاستبدال غير مستلم أو تم عكسه مسبقاً")
    reversed_at = datetime.utcnow()
    changed = (
        db.session.query(TradeInReceipt)
        .filter(
            TradeInReceipt.id == receipt.id,
            TradeInReceipt.status == "received",
        )
        .update(
            {
                TradeInReceipt.status: "reversed",
                TradeInReceipt.reversed_at: reversed_at,
            },
            synchronize_session=False,
        )
    )
    if changed != 1:
        raise TradeInError("سجل الاستبدال غير مستلم أو تم عكسه مسبقاً")
    replacement = Product.query.get(receipt.replacement_product_id)
    if not replacement:
        raise TradeInError("منتج الاستبدال النظامي غير موجود")
    qty = max(1, int(receipt.quantity or 1))
    try:
        if receipt.branch_id:
            deduct_stock(int(receipt.branch_id), replacement.id, qty, audit_context={
                "source_type": "trade_in_reversal", "source_id": receipt.id,
                "source_line_id": receipt.order_item_id, "invoice_id": receipt.invoice_id,
                "reason": "إرجاع قطع الاستبدال للعميل",
            })
        else:
            available = int(replacement.quantity or 0)
            if available < qty:
                raise TradeInError(
                    f"مخزون استبدال غير كافٍ للعكس. المتاح: {available}"
                )
            replacement.quantity = available - qty
    except BranchStockError as exc:
        raise TradeInError(str(exc)) from exc
    db.session.flush()
    return qty
