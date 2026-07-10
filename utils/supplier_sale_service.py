"""خدمة بيع للمورد — خصم مخزون وتسوية دين المورد."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import inspect, text
from sqlalchemy.sql import func

from extensions import db
from models.employee import Employee
from models.product import Product
from models.supplier import Supplier
from models.supplier_payment import SupplierPayment
from models.supplier_sale import SupplierSale
from models.supplier_sale_item import SupplierSaleItem
from utils.branch_context import current_branch_id
from utils.branch_migration import ensure_branch_schema, get_default_branch
from utils.branch_stock_service import BranchStockError, deduct_stock, receive_stock
from utils.inventory_movements import validate_sale_quantity
from utils.product_color_service import (
    ProductColorError,
    deduct_color_stock,
    receive_color_stock,
)


class SupplierSaleError(Exception):
    pass


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def ensure_supplier_sale_schema() -> None:
    """Create supplier_sale tables and extend supplier_payment if needed."""
    bind = db.session.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())

    if "supplier_sale" not in tables:
        SupplierSale.__table__.create(bind, checkfirst=True)
    if "supplier_sale_item" not in tables:
        SupplierSaleItem.__table__.create(bind, checkfirst=True)

    if "supplier_payment" in tables:
        cols = {c["name"] for c in insp.get_columns("supplier_payment")}
        if "payment_method" not in cols:
            db.session.execute(
                text("ALTER TABLE supplier_payment ADD COLUMN payment_method VARCHAR(20) DEFAULT 'cash'")
            )
        if "supplier_sale_id" not in cols:
            db.session.execute(
                text("ALTER TABLE supplier_payment ADD COLUMN supplier_sale_id INTEGER")
            )
        db.session.commit()


def _next_supplier_sale_invoice_no() -> str:
    today = datetime.utcnow().strftime("%Y%m%d")
    count_today = (
        SupplierSale.query.filter(func.date(SupplierSale.created_at) == date.today()).count()
    )
    return f"SS-{today}-{count_today + 1:04d}"


def _resolve_branch_id() -> int | None:
    ensure_branch_schema()
    branch_id = current_branch_id()
    if branch_id:
        return int(branch_id)
    default_branch = get_default_branch()
    return int(default_branch.id) if default_branch else None


def _deduct_sale_item_stock(
    product: Product,
    qty: int,
    branch_id: int | None,
    variant_color: str | None = None,
) -> None:
    if qty <= 0:
        raise SupplierSaleError("الكمية يجب أن تكون أكبر من صفر")
    validation = validate_sale_quantity(product.id, qty)
    if not validation.get("valid"):
        raise SupplierSaleError(validation.get("message") or "كمية غير متاحة")

    if branch_id:
        try:
            deduct_stock(branch_id, product.id, qty)
        except BranchStockError as exc:
            raise SupplierSaleError(str(exc)) from exc
    else:
        current_qty = _safe_int(product.quantity, 0)
        if current_qty < qty:
            raise SupplierSaleError(
                f"الكمية المتوفرة ({current_qty}) أقل من المطلوب ({qty}) للمنتج {product.name}"
            )
        product.quantity = current_qty - qty

    color = (variant_color or "").strip()
    if color:
        try:
            deduct_color_stock(product.id, color, qty)
        except ProductColorError as exc:
            raise SupplierSaleError(str(exc)) from exc


def _restore_sale_item_stock(item: SupplierSaleItem) -> None:
    if not item.product_id:
        return
    product = Product.query.get(item.product_id)
    if not product:
        return
    qty = _safe_int(item.quantity, 0)
    if qty <= 0:
        return

    branch_id = item.fulfillment_branch_id
    if branch_id:
        receive_stock(branch_id, product.id, qty)
    else:
        product.quantity = _safe_int(product.quantity, 0) + qty

    color = (item.variant_color or "").strip()
    if color:
        try:
            receive_color_stock(product.id, color, qty)
        except ProductColorError as exc:
            raise SupplierSaleError(str(exc)) from exc


def supplier_sale_summary(sale: SupplierSale) -> dict:
    items = list(sale.items or [])
    if items:
        item_count = len(items)
        names = [it.product_name or "—" for it in items[:3]]
        products_label = "، ".join(names)
        if item_count > 3:
            products_label += f" (+{item_count - 3})"
    else:
        item_count = 0
        products_label = "—"

    return {
        "id": sale.id,
        "invoice_no": sale.invoice_no or f"SS-{sale.id}",
        "item_count": item_count,
        "products_label": products_label,
        "grand_total": _safe_int(sale.grand_total),
        "sale_date": sale.sale_date,
        "status": sale.status or "confirmed",
        "notes": sale.notes or "",
    }


def create_supplier_sale(
    supplier: Supplier,
    items_payload: list[dict],
    *,
    note: str = "",
    employee: Employee | None = None,
) -> SupplierSale:
    ensure_supplier_sale_schema()

    if not items_payload:
        raise SupplierSaleError("أضف منتجاً واحداً على الأقل")

    branch_id = _resolve_branch_id()
    parsed_lines: list[dict] = []

    for row in items_payload:
        product = Product.query.get(_safe_int(row.get("product_id"), 0))
        if not product:
            raise SupplierSaleError("منتج غير موجود")
        qty = max(1, _safe_int(row.get("qty") or row.get("quantity"), 1))
        custom_price = row.get("price") or row.get("unit_price")
        if custom_price and _safe_int(custom_price) > 0:
            unit_price = _safe_int(custom_price)
        else:
            unit_price = _safe_int(product.sale_price, 0)
        if unit_price <= 0:
            raise SupplierSaleError(f"سعر البيع غير صالح للمنتج {product.name}")
        variant_color = (row.get("variant_color") or "").strip() or None
        parsed_lines.append(
            {
                "product": product,
                "qty": qty,
                "unit_price": unit_price,
                "line_total": unit_price * qty,
                "variant_color": variant_color,
            }
        )

    grand_total = sum(line["line_total"] for line in parsed_lines)
    if grand_total <= 0:
        raise SupplierSaleError("إجمالي البيع يجب أن يكون أكبر من صفر")

    sale = SupplierSale(
        supplier_id=supplier.id,
        invoice_no=_next_supplier_sale_invoice_no(),
        status="confirmed",
        grand_total=grand_total,
        notes=(note or "").strip() or None,
        sale_date=date.today(),
        branch_id=branch_id,
        created_by_employee_id=employee.id if employee else None,
    )
    db.session.add(sale)
    db.session.flush()

    for line in parsed_lines:
        product = line["product"]
        qty = line["qty"]
        _deduct_sale_item_stock(product, qty, branch_id, line["variant_color"])
        db.session.add(
            SupplierSaleItem(
                supplier_sale_id=sale.id,
                product_id=product.id,
                product_name=product.name,
                quantity=qty,
                unit_price=line["unit_price"],
                line_total=line["line_total"],
                cost=_safe_int(product.buy_price, 0),
                variant_color=line["variant_color"],
                fulfillment_branch_id=branch_id,
            )
        )

    supplier.total_paid = _safe_int(supplier.total_paid) + grand_total
    db.session.add(
        SupplierPayment(
            supplier_id=supplier.id,
            amount=grand_total,
            note=f"بيع للمورد — {sale.invoice_no}" + (f" — {note.strip()}" if note and note.strip() else ""),
            treasury_account_id=None,
            payment_method="offset",
            supplier_sale_id=sale.id,
        )
    )

    return sale


def cancel_supplier_sale(sale: SupplierSale) -> SupplierSale:
    ensure_supplier_sale_schema()

    status = (sale.status or "").strip().lower()
    if status == "cancelled":
        raise SupplierSaleError("البيع ملغى مسبقاً")

    supplier = Supplier.query.get(sale.supplier_id)
    if not supplier:
        raise SupplierSaleError("المورد غير موجود")

    grand_total = _safe_int(sale.grand_total)
    for item in list(sale.items or []):
        _restore_sale_item_stock(item)

    supplier.total_paid = max(_safe_int(supplier.total_paid) - grand_total, 0)

    payment = (
        SupplierPayment.query.filter_by(supplier_sale_id=sale.id, payment_method="offset")
        .order_by(SupplierPayment.id.desc())
        .first()
    )
    if payment:
        db.session.delete(payment)

    sale.status = "cancelled"
    return sale
