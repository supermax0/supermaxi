"""
صفحة المشتريات (Purchases)
Refactor كامل: Purchase master + items + payments + attachments
"""

import json
import os
import uuid
from datetime import datetime, date

from flask import Blueprint, current_app, flash, jsonify, make_response, redirect, render_template, request, session, url_for
from sqlalchemy import inspect, or_, text
from sqlalchemy.sql import func
from werkzeug.utils import secure_filename

from extensions import db
from models.account_transaction import AccountTransaction
from models.employee import Employee
from models.product import Product
from models.purchase import Purchase
from models.purchase_attachment import PurchaseAttachment
from models.purchase_item import PurchaseItem
from models.purchase_payment import PurchasePayment
from models.supplier import Supplier
from models.treasury_account import TreasuryAccount
from utils.inventory_lots import create_purchase_lot, ensure_inventory_lot_schema, reverse_purchase_lot
from utils.stock_movement_guard import (
    StockMovementConflict,
    claim_stock_movement,
    ensure_stock_movement_schema,
)
from utils.permission_checks import check_permission
from utils.activity_logger import log_activity
from utils.treasury_helpers import resolve_treasury_account_id, get_default_cash_account, treasury_choices_for_form
from utils.treasury_calculations import assert_sufficient_balance, InsufficientTreasuryBalance
from utils.treasury_schema_guard import ensure_treasury_schema
from utils.branch_migration import ensure_branch_schema, get_default_branch
from utils.branch_context import current_branch_id, resolve_branch_id
from utils.branch_scope import resolve_write_branch_id
from utils.branch_mode import independent_branches_enabled
from utils.branch_stock_service import deduct_stock, receive_stock
from utils.order_item_schema_guard import ensure_order_item_schema
from utils.product_color_service import (
    ProductColorError,
    colors_for_product_dict,
    deduct_color_stock,
    ensure_color_variant,
    product_has_colors,
    receive_color_stock,
    update_color_buy_price,
)
from utils.supplier_exchange_rate import get_supplier_exchange_rate
from utils.supplier_payment_allocation import (
    backfill_supplier_payment_allocations,
    effective_purchase_payment_totals,
    purchase_allocation_totals_for_ids,
    purchase_has_supplier_payment_allocations,
)

purchases_bp = Blueprint("purchases", __name__, url_prefix="/purchases")


def _is_admin_user():
    if "user_id" not in session:
        return False
    if (session.get("role") or "").strip() == "admin":
        return True
    employee = Employee.query.get(session["user_id"])
    return bool(employee and employee.role == "admin")


def _ensure_purchase_schema():
    """Adds new purchase header fields and creates child tables if missing."""
    bind = db.session.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())
    if "purchase" in tables:
        cols = {c["name"] for c in insp.get_columns("purchase")}
        stmts = []
        additions = {
            "invoice_no": "ALTER TABLE purchase ADD COLUMN invoice_no VARCHAR(60)",
            "status": "ALTER TABLE purchase ADD COLUMN status VARCHAR(30) DEFAULT 'draft'",
            "branch_code": "ALTER TABLE purchase ADD COLUMN branch_code VARCHAR(60)",
            "branch_id": "ALTER TABLE purchase ADD COLUMN branch_id INTEGER",
            "reference_no": "ALTER TABLE purchase ADD COLUMN reference_no VARCHAR(120)",
            "supplier_invoice_no": "ALTER TABLE purchase ADD COLUMN supplier_invoice_no VARCHAR(120)",
            "address": "ALTER TABLE purchase ADD COLUMN address VARCHAR(255)",
            "purchase_mode": "ALTER TABLE purchase ADD COLUMN purchase_mode VARCHAR(30)",
            "payment_term": "ALTER TABLE purchase ADD COLUMN payment_term VARCHAR(80)",
            "notes": "ALTER TABLE purchase ADD COLUMN notes TEXT",
            "shipping_details": "ALTER TABLE purchase ADD COLUMN shipping_details TEXT",
            "extra_cost_note": "ALTER TABLE purchase ADD COLUMN extra_cost_note VARCHAR(255)",
            "sub_total": "ALTER TABLE purchase ADD COLUMN sub_total INTEGER DEFAULT 0",
            "discount_value": "ALTER TABLE purchase ADD COLUMN discount_value INTEGER DEFAULT 0",
            "shipping_extra": "ALTER TABLE purchase ADD COLUMN shipping_extra INTEGER DEFAULT 0",
            "grand_total": "ALTER TABLE purchase ADD COLUMN grand_total INTEGER DEFAULT 0",
            "paid_total": "ALTER TABLE purchase ADD COLUMN paid_total INTEGER DEFAULT 0",
            "remaining_total": "ALTER TABLE purchase ADD COLUMN remaining_total INTEGER DEFAULT 0",
            "created_by_employee_id": "ALTER TABLE purchase ADD COLUMN created_by_employee_id INTEGER",
            "stock_applied": "ALTER TABLE purchase ADD COLUMN stock_applied BOOLEAN DEFAULT 0",
            "stock_revision": "ALTER TABLE purchase ADD COLUMN stock_revision INTEGER NOT NULL DEFAULT 1",
            "purchase_list_id": "ALTER TABLE purchase ADD COLUMN purchase_list_id INTEGER",
        }
        for key, stmt in additions.items():
            if key not in cols:
                stmts.append(stmt)
        for stmt in stmts:
            db.session.execute(text(stmt))
        if stmts:
            # One-time backfill when the stock_applied column is first added:
            # confirmed legacy invoices already affected stock before this flag
            # existed, while legacy draft/cancelled rows never did. Never run
            # these on later requests, because a draft with stock_applied=1 is
            # a legitimate state (a confirmed invoice unlocked for editing) and
            # resetting it would skip the stock reversal on save, duplicating
            # stock.
            if "stock_applied" not in cols:
                db.session.execute(
                    text(
                        "UPDATE purchase SET stock_applied = 1 "
                        "WHERE lower(coalesce(status, 'confirmed')) = 'confirmed'"
                    )
                )
                db.session.execute(
                    text(
                        "UPDATE purchase SET stock_applied = 0 "
                        "WHERE lower(coalesce(status, '')) IN ('draft', 'cancelled', 'canceled') "
                        "AND coalesce(stock_applied, 0) != 0"
                    )
                )
            db.session.commit()

    PurchaseItem.__table__.create(bind=bind, checkfirst=True)
    PurchasePayment.__table__.create(bind=bind, checkfirst=True)
    PurchaseAttachment.__table__.create(bind=bind, checkfirst=True)
    ensure_inventory_lot_schema()
    ensure_stock_movement_schema()
    ensure_order_item_schema()


def _purchase_line_variant_color(raw: dict) -> str:
    return (raw.get("color") or raw.get("variant_color") or "").strip()


def _shared_name_key(value) -> str:
    text_value = str(value or "").strip().casefold()
    return " ".join(text_value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").split())


def _supplier_for_purchase_branch(supplier_id: int, branch_id: int):
    """Use a branch copy when available, otherwise keep the shared supplier."""
    supplier_query = Supplier.query.execution_options(skip_branch_scope=True)
    supplier = supplier_query.filter_by(id=int(supplier_id)).first()
    if not supplier:
        return supplier
    if not supplier.branch_id:
        supplier.branch_id = int(branch_id)
        return supplier
    if independent_branches_enabled():
        return supplier
    if int(supplier.branch_id or 0) == int(branch_id):
        return supplier
    candidates = (
        supplier_query
        .filter(Supplier.branch_id == int(branch_id))
        .all()
    )
    return next(
        (row for row in candidates if _shared_name_key(row.name) == _shared_name_key(supplier.name)),
        supplier,
    )


def _supplier_allowed_for_purchase_branch(supplier, branch_id: int) -> bool:
    """Suppliers are company-wide in shared mode; only stock is branch-local."""
    if not independent_branches_enabled():
        return True
    return int(getattr(supplier, "branch_id", 0) or 0) == int(branch_id or 0)


def _product_for_purchase_branch(product_id: int, branch_id: int):
    product = (
        Product.query.execution_options(skip_branch_scope=True)
        .filter_by(id=int(product_id), active=True)
        .first()
    )
    if not product:
        return product
    # Adopt unscoped legacy products into the receiving branch.  They predate
    # branch ownership and are not a product belonging to some other branch.
    if not product.branch_id:
        product.branch_id = int(branch_id)
        return product
    if independent_branches_enabled():
        return product
    if int(product.branch_id or 0) == int(branch_id):
        return product
    from utils.branch_product_service import product_for_branch

    return product_for_branch(product, branch_id, create=True)


def _parse_purchase_line(raw: dict, idx: int, *, product_override=None, allow_archived=False):
    product_id = _safe_int(raw.get("product_id"), 0)
    qty = _safe_int(raw.get("quantity"), 0)
    if product_id <= 0 or qty <= 0:
        raise ValueError(f"العنصر رقم {idx + 1} غير صالح.")
    unit_before = _safe_int(raw.get("unit_cost_before_discount") or raw.get("unit_cost"), 0)
    item_discount = _safe_int(raw.get("discount_value"), 0)
    if unit_before < 0 or item_discount < 0:
        raise ValueError(f"أسعار العنصر رقم {idx + 1} لا يمكن أن تكون سالبة.")
    if item_discount > unit_before:
        raise ValueError(f"خصم العنصر رقم {idx + 1} أكبر من سعر الوحدة.")
    final_unit = unit_before - item_discount
    # Never trust a browser-supplied total for an accounting row.
    line_total = final_unit * qty
    product = product_override or Product.query.get_or_404(product_id)
    variant_color = _purchase_line_variant_color(raw)
    from utils.product_options import validate_selection, option_config
    try:
        if option_config(product).get("axes") or raw.get("variant_id") is not None:
            variant_color = validate_selection(product, variant_color, raw.get("variant_id"), allow_archived=allow_archived)
        elif product_has_colors(product) and not variant_color:
            raise ProductColorError(f"يجب اختيار لون للمنتج: {product.name}")
    except ProductColorError as exc:
        raise ValueError(str(exc)) from exc
    if variant_color:
        ensure_color_variant(product.id, variant_color)
    return product, qty, unit_before, item_discount, final_unit, line_total, variant_color


def _purchase_stock_revision(purchase) -> int:
    return max(1, _safe_int(getattr(purchase, "stock_revision", 1), 1))


def _max_recorded_purchase_stock_revision(purchase_id: int) -> int:
    """Highest stock_revision already used in immutable movement keys for this id.

    SQLite may reuse purchase / purchase_item rowids after delete, while
    stock_movement keys remain. Scanning recorded keys avoids colliding with
    orphaned receive/reverse history for a recycled purchase id.
    """
    ensure_stock_movement_schema()
    from models.stock_movement import StockMovement

    prefix = f"purchase:{int(purchase_id)}:revision:"
    rows = (
        db.session.query(StockMovement.movement_key)
        .filter(StockMovement.movement_key.like(f"{prefix}%"))
        .all()
    )
    max_rev = 0
    for (movement_key,) in rows:
        rest = str(movement_key or "")[len(prefix) :]
        rev_token = rest.split(":", 1)[0]
        try:
            max_rev = max(max_rev, int(rev_token))
        except (TypeError, ValueError):
            continue
    return max_rev


def _allocate_purchase_stock_revision(purchase_id: int, *, at_least: int = 1) -> int:
    at_least = max(1, int(at_least or 1))
    recorded = _max_recorded_purchase_stock_revision(purchase_id)
    if recorded <= 0:
        return at_least
    return max(at_least, recorded + 1)


def _apply_purchase_item_stock(
    purchase,
    purchase_item,
    branch_id: int | None,
    apply_stock: bool,
) -> bool:
    if not apply_stock:
        return False
    product = purchase_item.product
    qty = _safe_int(purchase_item.quantity, 0)
    variant_color = (getattr(purchase_item, "variant_color", None) or "").strip()
    last_conflict = None
    for _attempt in range(3):
        revision = _purchase_stock_revision(purchase)
        movement_key = (
            f"purchase:{purchase.id}:revision:{revision}:"
            f"item:{purchase_item.id}:receive"
        )
        try:
            claim = claim_stock_movement(
                movement_key,
                movement_type="purchase_receive",
                direction="in",
                product_id=product.id,
                branch_id=branch_id,
                quantity=qty,
                unit_cost=_safe_int(purchase_item.final_unit_cost, 0),
                source_type="purchase",
                source_id=purchase.id,
                source_line_id=purchase_item.id,
                details={"variant_color": variant_color or None},
            )
        except StockMovementConflict as exc:
            last_conflict = exc
            purchase.stock_revision = _allocate_purchase_stock_revision(
                purchase.id,
                at_least=revision + 1,
            )
            continue
        if not claim.applied:
            return False
        if branch_id:
            receive_stock(branch_id, product.id, qty)
        else:
            product.quantity = _safe_int(product.quantity, 0) + qty
        if variant_color:
            receive_color_stock(product.id, variant_color, qty, branch_id=branch_id)
        return True
    if last_conflict is not None:
        raise last_conflict
    return False


def _reverse_purchase_item_stock(purchase, it, branch_id: int | None) -> bool:
    if not it.product:
        return False
    qty = _safe_int(it.quantity, 0)
    if qty <= 0:
        return False
    revision = _purchase_stock_revision(purchase)
    receive_key = f"purchase:{purchase.id}:revision:{revision}:item:{it.id}:receive"
    reverse_key = f"purchase:{purchase.id}:revision:{revision}:item:{it.id}:reverse"
    variant_color = (getattr(it, "variant_color", None) or "").strip()
    claim = claim_stock_movement(
        reverse_key,
        movement_type="purchase_reverse",
        direction="out",
        product_id=it.product.id,
        branch_id=branch_id,
        quantity=qty,
        unit_cost=_safe_int(getattr(it, "final_unit_cost", 0), 0),
        source_type="purchase",
        source_id=purchase.id,
        source_line_id=getattr(it, "id", None),
        reversal_of_key=receive_key,
        details={"variant_color": variant_color or None},
    )
    if not claim.applied:
        return False
    reverse_purchase_lot(it)
    if branch_id:
        deduct_stock(branch_id, it.product.id, qty)
    else:
        current_qty = _safe_int(it.product.quantity, 0)
        if current_qty < qty:
            raise ValueError(
                f"لا يمكن عكس فاتورة الشراء لأن مخزون {it.product.name} أقل من كمية الفاتورة."
            )
        it.product.quantity = current_qty - qty
    if variant_color:
        try:
            deduct_color_stock(it.product.id, variant_color, qty, branch_id=branch_id)
        except ProductColorError as exc:
            raise ValueError(str(exc)) from exc
    return True


def _fmt_iq(num):
    return f"{int(num or 0):,}"


def _next_invoice_no():
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
    return f"PUR-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def _purchase_invoice_no_conflict(branch_id: int, invoice_no: str, exclude_id: int | None = None):
    query = (
        Purchase.query.execution_options(skip_branch_scope=True)
        .filter(Purchase.branch_id == int(branch_id), Purchase.invoice_no == invoice_no)
    )
    if exclude_id:
        query = query.filter(Purchase.id != int(exclude_id))
    return query.first()


def _save_attachment(file_storage, purchase_id):
    uploads_dir = os.path.join(current_app.root_path, "static", "uploads", "purchases")
    os.makedirs(uploads_dir, exist_ok=True)
    original = secure_filename(file_storage.filename or "")
    if not original:
        return None
    ext = os.path.splitext(original)[1].lower()
    token = uuid.uuid4().hex[:12]
    filename = f"purchase_{purchase_id}_{token}{ext}"
    full_path = os.path.join(uploads_dir, filename)
    file_storage.save(full_path)
    rel = f"static/uploads/purchases/{filename}"
    return PurchaseAttachment(
        purchase_id=purchase_id,
        file_path=rel,
        original_name=original,
        mime_type=file_storage.mimetype,
        file_size=os.path.getsize(full_path) if os.path.exists(full_path) else None,
    )


def _is_cash_method(method):
    return (method or "").strip().lower() in ("cash", "صندوق", "نقدي")


def _is_bank_method(method):
    return (method or "").strip().lower() in (
        "bank", "bank_transfer", "transfer", "card", "بنك", "تحويل بنكي", "بطاقة"
    )


def _affects_treasury(method):
    return _is_cash_method(method) or _is_bank_method(method)


def _payment_treasury_id(pay_payload: dict, payment_method: str, branch_id: int) -> int:
    if not pay_payload.get("_schema_ready"):
        ensure_treasury_schema()
    raw_id = pay_payload.get("treasury_account_id")
    if raw_id not in (None, ""):
        account = (
            TreasuryAccount.query.execution_options(skip_branch_scope=True)
            .filter_by(
                id=_safe_int(raw_id, 0),
                branch_id=int(branch_id),
                is_active=True,
            )
            .first()
        )
        if not account:
            raise ValueError("حساب الدفع لا يتبع فرع فاتورة الشراء")
        return account.id
    if _is_bank_method(payment_method):
        banks = (
            TreasuryAccount.query.execution_options(skip_branch_scope=True)
            .filter_by(
                branch_id=int(branch_id),
                account_type="bank",
                is_active=True,
            )
            .order_by(TreasuryAccount.name.asc())
            .all()
        )
        if banks:
            return banks[0].id
        raise ValueError("لا يوجد حساب بنكي فعال في فرع فاتورة الشراء")
    return get_default_cash_account(branch_id).id


def _add_purchase_withdraw(pay: PurchasePayment, purchase, supplier, note_suffix: str = ""):
    if not _affects_treasury(pay.payment_method):
        return
    treasury_id = pay.treasury_account_id or get_default_cash_account(purchase.branch_id).id
    assert_sufficient_balance(treasury_id, int(pay.amount or 0))
    normalized_method = (pay.payment_method or "").strip().lower()
    label = "بطاقة" if normalized_method == "card" else ("بنك" if _is_bank_method(normalized_method) else "صندوق")
    db.session.add(
        AccountTransaction(
            branch_id=purchase.branch_id,
            type="withdraw",
            amount=int(pay.amount or 0),
            note=f"{label} - دفعة شراء {purchase.invoice_no} للمورد {supplier.name}{note_suffix}",
            treasury_account_id=treasury_id,
            purchase_list_id=getattr(purchase, "purchase_list_id", None),
        )
    )


def _treasury_paid_amount(purchase):
    return sum(_treasury_paid_by_account(purchase).values())


def _treasury_paid_by_account(purchase) -> dict[int, int]:
    default_cash_id = get_default_cash_account(getattr(purchase, "branch_id", None)).id
    totals: dict[int, int] = {}
    rows = purchase.payments or []
    if rows:
        for payment in rows:
            if not _affects_treasury(payment.payment_method):
                continue
            amount = _safe_int(payment.amount, 0)
            if amount <= 0:
                continue
            treasury_id = payment.treasury_account_id or default_cash_id
            totals[treasury_id] = totals.get(treasury_id, 0) + amount
        return totals
    if _affects_treasury(purchase.purchase_mode) and _safe_int(purchase.paid_total, 0) > 0:
        treasury_id = getattr(purchase, "treasury_account_id", None) or default_cash_id
        totals[treasury_id] = _safe_int(purchase.paid_total, 0)
    return totals


def _safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


def _purchase_status_applies_stock(status) -> bool:
    return (status or "confirmed").strip().lower() not in {
        "draft",
        "draft_editing",
        "cancelled",
        "canceled",
    }


def _purchase_stock_applied(purchase) -> bool:
    if hasattr(purchase, "stock_applied"):
        raw = getattr(purchase, "stock_applied", None)
        if raw is not None and bool(raw):
            return True
        return _purchase_status_applies_stock(getattr(purchase, "status", None))
    return _purchase_status_applies_stock(getattr(purchase, "status", None))


def _purchase_accounting_applied(purchase) -> bool:
    status = (getattr(purchase, "status", None) or "confirmed").strip().lower()
    if status in {"cancelled", "canceled"}:
        return False
    if status in {"draft", "draft_editing"}:
        return bool(getattr(purchase, "stock_applied", False))
    return True


def _resolve_purchase_branch_id(payload: dict, branch_code: str | None = None) -> int | None:
    branch_id = payload.get("branch_id") if payload else None
    if branch_id:
        try:
            return int(branch_id)
        except (TypeError, ValueError):
            pass

    code = (branch_code or (payload.get("branch_code") if payload else "") or "").strip()
    if code:
        from models.branch import Branch

        match = Branch.query.filter(db.func.upper(Branch.code) == code.upper()).first()
        if match:
            return match.id

    default = get_default_branch()
    return default.id if default else None


def _reverse_purchase_effects(purchase, reason, *, hard_delete=False):
    if str(getattr(purchase, "source_module", "") or "").strip().lower() == "food":
        if reason == "تعديل الفاتورة":
            raise ValueError("عدّل مشتريات المواد الغذائية من مساحتها المخصصة حفاظاً على الوحدات والمخزون")
        from modules.food.service import reverse_purchase

        reverse_purchase(purchase, reason, hard_delete=hard_delete)
        return
    if purchase_has_supplier_payment_allocations(purchase.id):
        raise ValueError(
            "لا يمكن عكس أو تعديل فاتورة مرتبطة بدفعات مورد لاحقة. "
            "احذف أو اعكس دفعات المورد المرتبطة بها أولاً للمحافظة على سلامة التسوية."
        )

    # Reverse stock
    branch_id = getattr(purchase, "branch_id", None) or _resolve_purchase_branch_id({}, getattr(purchase, "branch_code", None))
    items = list(purchase.items or [])
    if not items and getattr(purchase, "product", None):
        items = [purchase]

    if _purchase_stock_applied(purchase):
        for it in items:
            try:
                _reverse_purchase_item_stock(purchase, it, branch_id)
            except (ProductColorError, ValueError):
                raise
        if hasattr(purchase, "stock_applied"):
            purchase.stock_applied = False

    accounting_applied = _purchase_accounting_applied(purchase)

    # Reverse supplier ledgers
    if accounting_applied and purchase.supplier:
        purchase.supplier.total_debt = max(
            _safe_int(purchase.supplier.total_debt, 0) - _safe_int(purchase.grand_total or purchase.total, 0),
            0,
        )
        purchase.supplier.total_paid = max(
            _safe_int(purchase.supplier.total_paid, 0) - _safe_int(purchase.paid_total, 0),
            0,
        )

    if not accounting_applied:
        return

    # Reverse treasury movement with opposite transaction (audit-safe)
    for treasury_id, treasury_paid in _treasury_paid_by_account(purchase).items():
        if treasury_paid <= 0:
            continue
        db.session.add(
            AccountTransaction(
                branch_id=purchase.branch_id,
                type="deposit",
                amount=treasury_paid,
                note=f"صندوق - عكس دفعات شراء {purchase.invoice_no or purchase.id} ({reason})",
                treasury_account_id=treasury_id,
            )
        )


def _create_purchase_from_payload(payload, files, *, commit=True, employee_id=None):
    supplier_id = int(payload.get("supplier_id") or 0)
    supplier = None
    items = payload.get("items") or []
    if not items:
        return None, "يجب إضافة عنصر واحد على الأقل."

    p_date = payload.get("purchase_date")
    try:
        purchase_date = datetime.strptime(p_date, "%Y-%m-%d").date() if p_date else date.today()
    except ValueError:
        purchase_date = date.today()

    discount_value = _safe_int(payload.get("discount_value"), 0)
    shipping_extra = _safe_int(payload.get("shipping_extra"), 0)
    if discount_value < 0 or shipping_extra < 0:
        return None, "الخصم وتكلفة الشحن لا يمكن أن يكونا سالبين"
    payment_term = (payload.get("payment_term") or "").strip() or None
    purchase_mode = (payload.get("purchase_mode") or "").strip() or "credit"
    branch_code = (payload.get("branch_code") or "").strip() or None
    validated_branch_id = _safe_int(payload.get("_validated_branch_id"), 0)
    requested_branch_id = validated_branch_id or _resolve_purchase_branch_id(payload, branch_code)
    if validated_branch_id:
        # Internal domain services may pass a branch that they have already
        # tenant/permission validated. Avoid request-scope initialization in
        # the middle of their financial transaction.
        branch_id = validated_branch_id
    elif not independent_branches_enabled():
        # Shared inventory is still physically received at the branch chosen
        # in the quick-purchase dialog.  The old shared-mode resolver always
        # forced the default branch, which caused a valid supplier/product
        # selection for Karrada (or another branch) to return HTTP 400.
        if _is_admin_user() and requested_branch_id:
            branch_id = int(requested_branch_id)
        else:
            branch_id = current_branch_id() or requested_branch_id
    else:
        branch_id = resolve_write_branch_id({"branch_id": requested_branch_id})
    supplier = _supplier_for_purchase_branch(supplier_id, branch_id)
    if not supplier:
        return None, "المورد غير موجود"
    if not _supplier_allowed_for_purchase_branch(supplier, branch_id):
        return None, "المورد لا يتبع الفرع المختار"
    reference_no = (payload.get("reference_no") or "").strip() or None
    supplier_invoice_no = (payload.get("supplier_invoice_no") or "").strip() or None
    address = (payload.get("address") or "").strip() or None
    notes = (payload.get("notes") or "").strip() or None
    shipping_details = (payload.get("shipping_details") or "").strip() or None
    extra_cost_note = (payload.get("extra_cost_note") or "").strip() or None
    status = (payload.get("status") or "confirmed").strip()
    apply_stock = _purchase_status_applies_stock(status)
    purchase_list_id = _safe_int(payload.get("purchase_list_id"), 0) or None
    warehouse_id = _safe_int(payload.get("warehouse_id"), 0) or None
    if warehouse_id:
        try:
            from modules.wholesale.services.warehouse_service import get_warehouse

            warehouse = get_warehouse(payload.get("tenant_id"), warehouse_id)
        except Exception:
            return None, "المخزن المحدد غير موجود أو لا يتبع الشركة الحالية"
        if warehouse.branch_id and int(warehouse.branch_id) != int(branch_id):
            return None, "المخزن المحدد لا يتبع فرع فاتورة الشراء"

    parsed_items = []
    sub_total = 0
    legacy_product_id = None
    legacy_qty = 0
    legacy_price = 0
    for idx, raw in enumerate(items):
        try:
            product_override = _product_for_purchase_branch(
                _safe_int(raw.get("product_id"), 0), branch_id
            )
            product, qty, unit_before, item_discount, final_unit, line_total, variant_color = _parse_purchase_line(
                raw, idx, product_override=product_override
            )
        except ValueError as exc:
            return None, str(exc)
        parsed_items.append((product, qty, unit_before, item_discount, final_unit, line_total, variant_color))
        if int(product.branch_id or 0) != int(branch_id):
            return None, f"المنتج «{product.name}» لا يتبع الفرع المختار"
        sub_total += line_total
        if legacy_product_id is None:
            legacy_product_id = product.id
            legacy_price = final_unit
        legacy_qty += qty

    payments_payload = payload.get("payments") or []
    paid_total = 0
    parsed_payments = []
    for pay in payments_payload:
        amount = int(pay.get("amount") or 0)
        if amount <= 0:
            continue
        paid_total += amount
        paid_at_raw = pay.get("paid_at")
        paid_at = datetime.utcnow()
        if paid_at_raw:
            try:
                paid_at = datetime.fromisoformat(paid_at_raw.replace("Z", ""))
            except Exception:
                paid_at = datetime.utcnow()
        payment_method = (pay.get("payment_method") or "").strip() or "cash"
        try:
            treasury_account_id = _payment_treasury_id(pay, payment_method, branch_id)
        except ValueError as exc:
            return None, str(exc)
        parsed_payments.append(
            PurchasePayment(
                amount=amount,
                paid_at=paid_at,
                payment_method=payment_method,
                account_name=(pay.get("account_name") or "").strip() or None,
                note=(pay.get("note") or "").strip() or None,
                treasury_account_id=treasury_account_id,
            )
        )

    grand_total = max(sub_total - discount_value + shipping_extra, 0)
    if discount_value > sub_total:
        return None, "الخصم الإجمالي لا يمكن أن يتجاوز مجموع المنتجات"
    if paid_total > grand_total:
        return None, "مجموع الدفعات لا يمكن أن يتجاوز إجمالي فاتورة الشراء"
    remaining_total = max(grand_total - paid_total, 0)
    if purchase_mode in ("cash", "bank") and paid_total <= 0:
        paid_total = grand_total
        remaining_total = 0
        automatic_method = "bank" if purchase_mode == "bank" else "cash"
        parsed_payments.append(
            PurchasePayment(
                amount=paid_total,
                paid_at=datetime.utcnow(),
                payment_method=automatic_method,
                account_name=None,
                note="دفعة بنكية تلقائية (شراء بنكي كامل)" if automatic_method == "bank" else "دفعة نقدية تلقائية (شراء نقدي كامل)",
                treasury_account_id=_payment_treasury_id({}, automatic_method, branch_id),
            )
        )

    invoice_no = (payload.get("invoice_no") or "").strip() or _next_invoice_no()
    if _purchase_invoice_no_conflict(branch_id, invoice_no):
        return None, "رقم فاتورة الشراء مستخدم مسبقاً في هذا الفرع"

    purchase = Purchase(
        supplier_id=supplier.id,
        product_id=legacy_product_id or parsed_items[0][0].id,
        quantity=legacy_qty,
        price=legacy_price,
        total=grand_total,
        invoice_no=invoice_no,
        status=status,
        branch_code=branch_code,
        branch_id=branch_id,
        reference_no=reference_no,
        supplier_invoice_no=supplier_invoice_no,
        address=address,
        purchase_mode=purchase_mode,
        payment_term=payment_term,
        notes=notes,
        shipping_details=shipping_details,
        extra_cost_note=extra_cost_note,
        sub_total=sub_total,
        discount_value=discount_value,
        shipping_extra=shipping_extra,
        grand_total=grand_total,
        paid_total=paid_total,
        remaining_total=remaining_total,
        purchase_date=purchase_date,
        created_by_employee_id=session.get("user_id"),
        stock_applied=apply_stock,
        warehouse_id=warehouse_id,
        purchase_list_id=purchase_list_id,
        source_module=(payload.get("source_module") or "").strip() or None,
    )
    if employee_id is not None:
        purchase.created_by_employee_id = employee_id
    db.session.add(purchase)
    db.session.flush()
    # Avoid colliding with orphaned stock_movement keys when SQLite reuses
    # a deleted purchase's rowid for this new invoice.
    purchase.stock_revision = _allocate_purchase_stock_revision(purchase.id)

    for product, qty, unit_before, item_discount, final_unit, line_total, variant_color in parsed_items:
        purchase_item = PurchaseItem(
            purchase_id=purchase.id,
            product_id=product.id,
            quantity=qty,
            unit_cost_before_discount=unit_before,
            discount_value=item_discount,
            final_unit_cost=final_unit,
            line_total=line_total,
            variant_color=variant_color or None,
        )
        db.session.add(purchase_item)
        db.session.flush()
        try:
            stock_applied_now = _apply_purchase_item_stock(
                purchase,
                purchase_item,
                branch_id,
                apply_stock,
            )
        except ProductColorError as exc:
            return None, str(exc)
        if stock_applied_now:
            create_purchase_lot(purchase_item, branch_id)
            if warehouse_id:
                from modules.wholesale.services.warehouse_service import apply_movement

                apply_movement(
                    payload.get("tenant_id"),
                    warehouse_id=warehouse_id,
                    product_id=product.id,
                    quantity_delta=qty,
                    movement_type="in",
                    reference_type="purchase",
                    reference_id=purchase.id,
                    unit_cost=final_unit,
                    note=f"استلام فاتورة شراء {purchase.invoice_no}",
                    created_by=purchase.created_by_employee_id,
                    allow_negative=True,
                )
        product.buy_price = final_unit
        if variant_color:
            update_color_buy_price(product.id, variant_color, final_unit)

    accounting_applied = _purchase_accounting_applied(purchase)
    for pay in parsed_payments:
        pay.purchase_id = purchase.id
        pay.branch_id = branch_id
        db.session.add(pay)
        if accounting_applied:
            try:
                _add_purchase_withdraw(
                    pay,
                    purchase,
                    supplier,
                    f" / قائمة {payload.get('purchase_list_number')}" if payload.get("purchase_list_number") else "",
                )
            except InsufficientTreasuryBalance as exc:
                if commit:
                    db.session.rollback()
                return None, str(exc)

    # supplier ledger: debt is the gross obligation, paid is the actual payments.
    if accounting_applied:
        supplier.total_debt = int(supplier.total_debt or 0) + grand_total
        supplier.total_paid = int(supplier.total_paid or 0) + paid_total
        backfill_supplier_payment_allocations(supplier.id)

    # attachments
    if files:
        for f in files:
            if not f or not f.filename:
                continue
            att = _save_attachment(f, purchase.id)
            if att:
                db.session.add(att)

    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return purchase, None


def _get_purchase_stats():
    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
    if not independent_branches_enabled():
        from routes.suppliers import _shared_supplier_rows
        suppliers = _shared_supplier_rows(suppliers)
    try:
        purchases_list = Purchase.query.order_by(Purchase.created_at.desc()).limit(500).all()
        total_purchases = sum(int(p.grand_total or p.total or 0) for p in purchases_list)
        purchases_count = len(purchases_list)
        current_month_start = date.today().replace(day=1)
        monthly_total = sum(
            int(p.grand_total or p.total or 0)
            for p in Purchase.query.filter(Purchase.purchase_date >= current_month_start).all()
        )
        try:
            from utils.supplier_accounting_repair import expected_supplier_totals

            if not independent_branches_enabled():
                # Shared rows already contain the company-wide aggregate;
                # do not recalculate using only the representative supplier.
                supplier_remaining = [max(int(s.remaining or 0), 0) for s in suppliers]
            else:
                supplier_remaining = []
                for s in suppliers:
                    expected_debt, expected_paid = expected_supplier_totals(int(s.id))
                    supplier_remaining.append(max(expected_debt - expected_paid, 0))
        except Exception:
            db.session.rollback()
            supplier_remaining = [
                max(
                    int(getattr(s, "total_debt", 0) or 0) - int(getattr(s, "total_paid", 0) or 0),
                    0,
                )
                for s in suppliers
            ]
        total_supplier_debts = sum(supplier_remaining)
        suppliers_with_debt = len([remaining for remaining in supplier_remaining if remaining > 0])
    except Exception:
        db.session.rollback()
        current_app.logger.exception("purchases stats query failed")
        total_purchases = purchases_count = monthly_total = total_supplier_debts = suppliers_with_debt = 0
    return {
        "total_purchases": total_purchases,
        "purchases_count": purchases_count,
        "monthly_total": monthly_total,
        "total_supplier_debts": total_supplier_debts,
        "suppliers_with_debt": suppliers_with_debt,
    }


def _product_search_row(product):
    row = {
        "id": product.id,
        "name": product.name,
        "sku": product.sku or "",
        "barcode": product.barcode or "",
        "buy_price": int(product.buy_price or 0),
        "quantity": int(product.quantity or 0),
    }
    row.update(colors_for_product_dict(product))
    return row


def _shared_purchase_products(products):
    """Show one product card for branch copies in legacy shared mode."""
    from services.pos_catalog import shared_catalog_groups
    representatives = []
    for members in shared_catalog_groups(products):
        members.sort(key=lambda item: (int(item.branch_id or 0), int(item.id)))
        representatives.append(members[0])
    return sorted(representatives, key=lambda item: ((item.name or "").casefold(), int(item.id)))


def _prepare_purchases_context():
    try:
        _ensure_purchase_schema()
        ensure_branch_schema()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("purchase schema migration failed")
    from models.branch import Branch

    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
    if not independent_branches_enabled():
        from routes.suppliers import _shared_supplier_rows
        suppliers = _shared_supplier_rows(suppliers)
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name.asc()).all()
    stats = _get_purchase_stats()
    return {
        "suppliers": suppliers,
        "branches": branches,
        "treasury_choices": treasury_choices_for_form(),
        "supplier_exchange_rate": get_supplier_exchange_rate(),
        **stats,
    }


@purchases_bp.route("/", methods=["GET"])
def purchases_index():
    """سجل المشتريات — الصفحة الرئيسية."""
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403
    ctx = _prepare_purchases_context()
    return render_template("purchases_history.html", **ctx)


@purchases_bp.route("/new", methods=["GET"])
def purchases_new():
    """فاتورة شراء جديدة."""
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403
    ctx = _prepare_purchases_context()
    products = Product.query.filter_by(active=True).order_by(Product.name.asc()).all()
    if not independent_branches_enabled():
        products = _shared_purchase_products(products)
    return render_template(
        "purchases_form.html",
        products=products,
        edit_purchase=None,
        form_mode="new",
        **ctx,
    )


@purchases_bp.route("/edit/<int:purchase_id>", methods=["GET"])
def purchases_edit(purchase_id):
    """تعديل فاتورة شراء (مسودة أو بعد فتحها للتحرير)."""
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403
    _ensure_purchase_schema()
    purchase = Purchase.query.get_or_404(purchase_id)
    status = (purchase.status or "").strip().lower()
    if status == "cancelled":
        flash("لا يمكن تعديل فاتورة ملغية. أعد فتحها من السجل أولاً.", "warning")
        return redirect(url_for("purchases.purchases_index"))
    if status == "confirmed":
        flash("الفاتورة المؤكدة مقفلة. افتحها للتحرير من سجل المشتريات أولاً.", "warning")
        return redirect(url_for("purchases.purchases_index"))
    ctx = _prepare_purchases_context()
    products = Product.query.filter_by(active=True).order_by(Product.name.asc()).all()
    if not independent_branches_enabled():
        products = _shared_purchase_products(products)
    return render_template(
        "purchases_form.html",
        products=products,
        edit_purchase=purchase,
        form_mode="edit",
        **ctx,
    )


@purchases_bp.route("/", methods=["POST"])
@purchases_bp.route("/create", methods=["POST"])
def purchases_create():
    """إنشاء فاتورة شراء (API / نموذج)."""
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403
    try:
        _ensure_purchase_schema()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("purchase schema migration failed")

    payload = {}
    files = []
    if request.is_json:
        payload = request.get_json(silent=True) or {}
    elif request.form.get("payload"):
        try:
            payload = json.loads(request.form.get("payload") or "{}")
        except Exception:
            payload = {}
        files = request.files.getlist("attachments")
    elif request.form.get("form_type") == "purchase":
        payload = {
            "supplier_id": request.form.get("supplier_id"),
            "purchase_date": request.form.get("purchase_date"),
            "purchase_mode": request.form.get("payment_method", "credit"),
            "status": "confirmed",
            "items": [
                {
                    "product_id": request.form.get("product_id"),
                    "quantity": request.form.get("quantity"),
                    "unit_cost": request.form.get("buy_price"),
                }
            ],
        }

    try:
        purchase, err = _create_purchase_from_payload(payload, files)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("purchases_create failed")
        err_msg = str(exc) or "حدث خطأ أثناء حفظ فاتورة الشراء"
        if request.is_json or request.form.get("payload"):
            return jsonify({"success": False, "error": err_msg}), 500
        flash(f"❌ {err_msg}", "danger")
        return redirect(url_for("purchases.purchases_new"))

    if err:
        db.session.rollback()
        if request.is_json or request.form.get("payload"):
            return jsonify({"success": False, "error": err}), 400
        flash(f"❌ {err}", "danger")
        return redirect(url_for("purchases.purchases_new"))

    try:
        log_activity(
            "create",
            "purchases",
            f"فاتورة شراء {purchase.invoice_no}",
            entity_type="purchase",
            entity_id=purchase.id,
            payload={"invoice_no": purchase.invoice_no, "supplier_id": purchase.supplier_id, "total": purchase.total_amount},
        )
    except Exception:
        pass

    msg = f"✅ تم حفظ فاتورة الشراء رقم {purchase.invoice_no} بنجاح"
    if request.is_json or request.form.get("payload"):
        return jsonify({"success": True, "message": msg, "purchase_id": purchase.id, "invoice_no": purchase.invoice_no})
    flash(msg, "success")
    return redirect(url_for("purchases.purchases_index"))


@purchases_bp.route("/api/products/search")
def search_products_for_purchase(*, _snapshot=False):
    if not check_permission("can_manage_inventory"):
        return jsonify([]), 403
    q = (request.args.get("q") or "").strip()
    if _snapshot:
        rows = Product.query.filter(Product.active.is_(True)).order_by(Product.name, Product.id).all()
        if not independent_branches_enabled():
            rows = _shared_purchase_products(rows)
        return jsonify([_product_search_row(p) for p in rows])
    if not q:
        return jsonify([])
    barcode_rows = Product.query.filter(Product.active.is_(True), Product.barcode == q).order_by(Product.branch_id.asc(), Product.id.asc()).all()
    if barcode_rows:
        if not independent_branches_enabled():
            barcode_rows = _shared_purchase_products(barcode_rows)
        return jsonify([_product_search_row(barcode_rows[0])])
    like = f"%{q}%"
    rows = (
        Product.query.filter(
            Product.active.is_(True),
            or_(
                Product.name.ilike(like),
                Product.sku.ilike(like),
                Product.barcode.ilike(like),
            ),
        )
        .order_by(Product.name.asc())
        .limit(50)
        .all()
    )
    if not independent_branches_enabled():
        rows = _shared_purchase_products(rows)[:15]
    else:
        rows = rows[:15]
    return jsonify([_product_search_row(p) for p in rows])


def _purchase_list_record(p, allocated_total):
    """One purchase as served by /purchases/api/list (shared with the paginated API)."""
    effective_paid, effective_remaining, later_paid = (
        effective_purchase_payment_totals(
            p,
            allocated_total,
        )
    )
    items = p.items or []
    item_count = len(items) if items else (1 if p.product_id else 0)
    first_product = ""
    if items:
        first_product = items[0].product.name if items[0].product else ""
    elif getattr(p, "product", None):
        first_product = p.product.name
    rec = {
        "id": p.id,
        "invoice_no": p.invoice_no or f"LEG-{p.id}",
        "date": p.purchase_date.strftime("%Y-%m-%d") if p.purchase_date else "",
        "supplier_id": p.supplier_id,
        "supplier": p.supplier.name if p.supplier else "",
        "status": p.status or "confirmed",
        "branch_code": p.branch_code or "",
        "reference_no": p.reference_no or "",
        "supplier_invoice_no": p.supplier_invoice_no or "",
        "payment_term": p.payment_term or "",
        "address": p.address or "",
        "notes": p.notes or "",
        "shipping_details": p.shipping_details or "",
        "extra_cost_note": p.extra_cost_note or "",
        "item_count": item_count,
        "first_product": first_product,
        "sub_total": int(p.sub_total or p.total or 0),
        "discount_value": int(p.discount_value or 0),
        "shipping_extra": int(p.shipping_extra or 0),
        "grand_total": int(p.grand_total or p.total or 0),
        "paid_total": effective_paid,
        "remaining_total": effective_remaining,
        "later_paid_total": later_paid,
        "purchase_mode": p.purchase_mode or "credit",
        "items": [
            {
                "product_id": it.product_id,
                "product": it.product.name if it.product else "",
                "color": (getattr(it, "variant_color", None) or "").strip(),
                "quantity": int(it.quantity or 0),
                "unit_cost_before_discount": int(it.unit_cost_before_discount or 0),
                "discount_value": int(it.discount_value or 0),
                "unit_cost": int(it.final_unit_cost or 0),
                "line_total": int(it.line_total or 0),
            }
            for it in items
        ],
        "payments": [
            {
                "amount": int(pay.amount or 0),
                "paid_at": pay.paid_at.strftime("%Y-%m-%d %H:%M") if pay.paid_at else "",
                "payment_method": pay.payment_method or "",
                "account_name": pay.account_name or "",
                "note": pay.note or "",
            }
            for pay in (p.payments or [])
        ],
        "attachments": [
            {
                "name": att.original_name or "",
                "url": "/" + (att.file_path or "").lstrip("/"),
            }
            for att in (p.attachments or [])
        ],
    }
    return rec


@purchases_bp.route("/api/list")
def get_purchases():
    if not check_permission("can_manage_inventory"):
        return jsonify({"error": "Unauthorized"}), 403
    try:
        _ensure_purchase_schema()
    except Exception:
        db.session.rollback()
        from flask import current_app
        current_app.logger.exception("purchase schema migration failed (api/list)")
        return jsonify([])

    supplier_id = request.args.get("supplier_id", type=int)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    search = (request.args.get("search", "") or "").strip().lower()

    query = Purchase.query
    if supplier_id:
        query = query.filter(Purchase.supplier_id == supplier_id)
    if date_from:
        try:
            query = query.filter(Purchase.purchase_date >= datetime.strptime(date_from, "%Y-%m-%d").date())
        except Exception:
            pass
    if date_to:
        try:
            query = query.filter(Purchase.purchase_date <= datetime.strptime(date_to, "%Y-%m-%d").date())
        except Exception:
            pass

    try:
        rows = query.order_by(Purchase.created_at.desc()).all()
    except Exception:
        db.session.rollback()
        from flask import current_app
        current_app.logger.exception("purchases api/list query failed")
        return jsonify([])

    allocated_by_purchase = purchase_allocation_totals_for_ids([p.id for p in rows])
    data = []
    for p in rows:
        try:
            data.append(_purchase_list_record(p, allocated_by_purchase.get(p.id, 0)))
        except Exception:
            from flask import current_app
            current_app.logger.exception("purchases api/list row failed purchase_id=%s", getattr(p, "id", "?"))
            continue

    if search:
        data = [
            r for r in data
            if search in (r["invoice_no"] or "").lower()
            or search in (r["supplier_invoice_no"] or "").lower()
            or search in (r["supplier"] or "").lower()
            or search in (r["first_product"] or "").lower()
        ]
    return jsonify(data)


@purchases_bp.route("/api/<int:purchase_id>")
def get_purchase_one(purchase_id):
    if not check_permission("can_manage_inventory"):
        return jsonify({"error": "Unauthorized"}), 403
    _ensure_purchase_schema()
    p = Purchase.query.get_or_404(purchase_id)
    effective_paid, effective_remaining, later_paid = (
        effective_purchase_payment_totals(p)
    )
    items = p.items or []
    rec = {
        "id": p.id,
        "invoice_no": p.invoice_no or f"LEG-{p.id}",
        "date": p.purchase_date.strftime("%Y-%m-%d") if p.purchase_date else "",
        "supplier_id": p.supplier_id,
        "supplier": p.supplier.name if p.supplier else "",
        "status": p.status or "confirmed",
        "branch_code": p.branch_code or "",
        "reference_no": p.reference_no or "",
        "supplier_invoice_no": p.supplier_invoice_no or "",
        "payment_term": p.payment_term or "",
        "address": p.address or "",
        "notes": p.notes or "",
        "shipping_details": p.shipping_details or "",
        "extra_cost_note": p.extra_cost_note or "",
        "item_count": len(items) if items else (1 if p.product_id else 0),
        "sub_total": int(p.sub_total or p.total or 0),
        "discount_value": int(p.discount_value or 0),
        "shipping_extra": int(p.shipping_extra or 0),
        "grand_total": int(p.grand_total or p.total or 0),
        "paid_total": effective_paid,
        "remaining_total": effective_remaining,
        "later_paid_total": later_paid,
        "purchase_mode": p.purchase_mode or "credit",
        "items": [
            {
                "product_id": it.product_id,
                "product": it.product.name if it.product else "",
                "product_name": it.product.name if it.product else "",
                "color": (getattr(it, "variant_color", None) or "").strip(),
                "quantity": int(it.quantity or 0),
                "unit_cost_before_discount": int(it.unit_cost_before_discount or 0),
                "discount_value": int(it.discount_value or 0),
                "unit_cost": int(it.final_unit_cost or 0),
                "line_total": int(it.line_total or 0),
            }
            for it in items
        ],
        "payments": [
            {
                "amount": int(pay.amount or 0),
                "paid_at": pay.paid_at.strftime("%Y-%m-%d %H:%M") if pay.paid_at else "",
                "payment_method": pay.payment_method or "",
                "account_name": pay.account_name or "",
                "note": pay.note or "",
            }
            for pay in (p.payments or [])
        ],
        "attachments": [
            {"name": att.original_name or "", "url": "/" + (att.file_path or "").lstrip("/")}
            for att in (p.attachments or [])
        ],
    }
    return jsonify(rec)


@purchases_bp.route("/export")
def export_purchases():
    if not check_permission("can_manage_inventory"):
        return jsonify({"error": "Unauthorized"}), 403
    _ensure_purchase_schema()

    rows = Purchase.query.order_by(Purchase.created_at.desc()).all()
    allocated_by_purchase = purchase_allocation_totals_for_ids([p.id for p in rows])
    csv_lines = ["التاريخ,رقم الفاتورة,رقم فاتورة المورد,المورد,عدد العناصر,الإجمالي,المدفوع,المتبقي,حالة الشراء\n"]
    for p in rows:
        effective_paid, effective_remaining, _later_paid = (
            effective_purchase_payment_totals(
                p,
                allocated_by_purchase.get(p.id, 0),
            )
        )
        item_count = len(p.items or []) if p.items else 1
        csv_lines.append(
            f"{(p.purchase_date.strftime('%Y-%m-%d') if p.purchase_date else '')},"
            f"{p.invoice_no or ('LEG-' + str(p.id))},"
            f"{p.supplier_invoice_no or ''},"
            f"{(p.supplier.name if p.supplier else '')},"
            f"{item_count},"
            f"{int(p.grand_total or p.total or 0)},"
            f"{effective_paid},"
            f"{effective_remaining},"
            f"{p.status or 'confirmed'}\n"
        )
    content = "\ufeff" + "".join(csv_lines)
    response = make_response(content)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f"attachment; filename=purchases_{date.today().strftime('%Y%m%d')}.csv"
    return response


@purchases_bp.route("/api/<int:purchase_id>/update", methods=["POST"])
def update_purchase(purchase_id):
    if not check_permission("can_manage_inventory"):
        return jsonify({"error": "Unauthorized"}), 403
    _ensure_purchase_schema()

    purchase = Purchase.query.get_or_404(purchase_id)
    if (purchase.status or "").strip().lower() == "cancelled":
        return jsonify({"success": False, "error": "لا يمكن تعديل فاتورة ملغية. أعد فتحها أولاً."}), 400
    if (purchase.status or "").strip().lower() == "confirmed":
        return jsonify({"success": False, "error": "الفاتورة المؤكدة مقفلة. يلزم فتحها للتحرير أولاً."}), 400
    payload = {}
    files = []
    if request.is_json:
        payload = request.get_json(silent=True) or {}
    elif request.form.get("payload"):
        payload = json.loads(request.form.get("payload") or "{}")
        files = request.files.getlist("attachments")
    else:
        return jsonify({"success": False, "error": "بيانات غير صالحة"}), 400

    try:
        # Atomically own this edit. Two concurrent saves cannot both reverse
        # and re-apply the same inventory/accounting revision.
        edit_claimed = (
            db.session.query(Purchase)
            .filter(
                Purchase.id == purchase.id,
                db.func.lower(db.func.coalesce(Purchase.status, "draft")) == "draft",
            )
            .update({Purchase.status: "draft_editing"}, synchronize_session=False)
        )
        if edit_claimed != 1:
            db.session.rollback()
            return jsonify({
                "success": False,
                "error": "الفاتورة قيد التعديل أو تم حفظها مسبقاً. حدّث الصفحة.",
            }), 409
        db.session.expire(purchase)

        previous_stock_revision = _purchase_stock_revision(purchase)
        previous_selections = {(item.product_id, (item.variant_color or "").strip()) for item in purchase.items}
        _reverse_purchase_effects(purchase, "تعديل الفاتورة")
        purchase.stock_revision = _allocate_purchase_stock_revision(
            purchase.id,
            at_least=previous_stock_revision + 1,
        )

        # remove old children
        for x in list(purchase.items or []):
            db.session.delete(x)
        for x in list(purchase.payments or []):
            db.session.delete(x)

        supplier_id = _safe_int(payload.get("supplier_id"), 0)
        supplier = Supplier.query.get_or_404(supplier_id)
        p_date = payload.get("purchase_date")
        try:
            purchase_date = datetime.strptime(p_date, "%Y-%m-%d").date() if p_date else date.today()
        except ValueError:
            purchase_date = date.today()

        discount_value = _safe_int(payload.get("discount_value"), 0)
        shipping_extra = _safe_int(payload.get("shipping_extra"), 0)
        if discount_value < 0 or shipping_extra < 0:
            db.session.rollback()
            return jsonify({"success": False, "error": "الخصم وتكلفة الشحن لا يمكن أن يكونا سالبين"}), 400
        branch_code = (payload.get("branch_code") or "").strip() or None
        branch_id = resolve_write_branch_id({
            "branch_id": _resolve_purchase_branch_id(payload, branch_code)
        })
        supplier = _supplier_for_purchase_branch(supplier_id, branch_id)
        if not supplier:
            db.session.rollback()
            return jsonify({"success": False, "error": "المورد غير موجود"}), 404
        if not _supplier_allowed_for_purchase_branch(supplier, branch_id):
            db.session.rollback()
            return jsonify({"success": False, "error": "المورد لا يتبع الفرع المختار"}), 400
        items = payload.get("items") or []
        if not items:
            db.session.rollback()
            return jsonify({"success": False, "error": "يجب إضافة عنصر واحد على الأقل."}), 400

        sub_total = 0
        legacy_product_id = None
        legacy_qty = 0
        legacy_price = 0
        parsed_items = []
        for idx, raw in enumerate(items):
            try:
                product_override = _product_for_purchase_branch(
                    _safe_int(raw.get("product_id"), 0), branch_id
                )
                product, qty, unit_before, item_discount, final_unit, line_total, variant_color = _parse_purchase_line(
                    raw, idx, product_override=product_override,
                    allow_archived=(_safe_int(raw.get("product_id"), 0), _purchase_line_variant_color(raw)) in previous_selections,
                )
            except ValueError as exc:
                db.session.rollback()
                return jsonify({"success": False, "error": str(exc)}), 400
            parsed_items.append((product, qty, unit_before, item_discount, final_unit, line_total, variant_color))
            if int(product.branch_id or 0) != int(branch_id):
                db.session.rollback()
                return jsonify({"success": False, "error": f"المنتج «{product.name}» لا يتبع الفرع المختار"}), 400
            sub_total += line_total
            if legacy_product_id is None:
                legacy_product_id = product.id
                legacy_price = final_unit
            legacy_qty += qty

        payments_payload = payload.get("payments") or []
        parsed_payments = []
        paid_total = 0
        for pay in payments_payload:
            amount = _safe_int(pay.get("amount"), 0)
            if amount <= 0:
                continue
            paid_total += amount
            paid_at_raw = pay.get("paid_at")
            paid_at = datetime.utcnow()
            if paid_at_raw:
                try:
                    paid_at = datetime.fromisoformat(paid_at_raw.replace("Z", ""))
                except Exception:
                    paid_at = datetime.utcnow()
            payment_method = (pay.get("payment_method") or "").strip() or "cash"
            try:
                treasury_account_id = _payment_treasury_id(pay, payment_method, branch_id)
            except ValueError as exc:
                db.session.rollback()
                return jsonify({"success": False, "error": str(exc)}), 400
            parsed_payments.append(
                PurchasePayment(
                    purchase_id=purchase.id,
                    amount=amount,
                    paid_at=paid_at,
                    payment_method=payment_method,
                    account_name=(pay.get("account_name") or "").strip() or None,
                    note=(pay.get("note") or "").strip() or None,
                    treasury_account_id=treasury_account_id,
                )
            )

        purchase_mode = (payload.get("purchase_mode") or "").strip() or "credit"
        grand_total = max(sub_total - discount_value + shipping_extra, 0)
        if discount_value > sub_total:
            db.session.rollback()
            return jsonify({"success": False, "error": "الخصم الإجمالي لا يمكن أن يتجاوز مجموع المنتجات"}), 400
        if paid_total > grand_total:
            db.session.rollback()
            return jsonify({"success": False, "error": "مجموع الدفعات لا يمكن أن يتجاوز إجمالي فاتورة الشراء"}), 400
        remaining_total = max(grand_total - paid_total, 0)
        if purchase_mode in ("cash", "bank") and paid_total <= 0:
            paid_total = grand_total
            remaining_total = 0
            automatic_method = "bank" if purchase_mode == "bank" else "cash"
            parsed_payments.append(
                PurchasePayment(
                    purchase_id=purchase.id,
                    amount=paid_total,
                    paid_at=datetime.utcnow(),
                    payment_method=automatic_method,
                    note="دفعة بنكية تلقائية (شراء بنكي كامل)" if automatic_method == "bank" else "دفعة نقدية تلقائية (شراء نقدي كامل)",
                    treasury_account_id=_payment_treasury_id({}, automatic_method, branch_id),
                )
            )

        new_status = (payload.get("status") or "confirmed").strip()
        apply_stock = _purchase_status_applies_stock(new_status)

        purchase.supplier_id = supplier.id
        purchase.product_id = legacy_product_id
        purchase.quantity = legacy_qty
        purchase.price = legacy_price
        purchase.total = grand_total
        invoice_no = (payload.get("invoice_no") or "").strip() or (purchase.invoice_no or _next_invoice_no())
        if _purchase_invoice_no_conflict(branch_id, invoice_no, exclude_id=purchase.id):
            db.session.rollback()
            return jsonify({"success": False, "error": "رقم فاتورة الشراء مستخدم مسبقاً في هذا الفرع"}), 400
        purchase.invoice_no = invoice_no
        purchase.status = new_status
        purchase.branch_code = branch_code
        purchase.branch_id = branch_id
        purchase.reference_no = (payload.get("reference_no") or "").strip() or None
        purchase.supplier_invoice_no = (payload.get("supplier_invoice_no") or "").strip() or None
        purchase.address = (payload.get("address") or "").strip() or None
        purchase.purchase_mode = purchase_mode
        purchase.payment_term = (payload.get("payment_term") or "").strip() or None
        purchase.notes = (payload.get("notes") or "").strip() or None
        purchase.shipping_details = (payload.get("shipping_details") or "").strip() or None
        purchase.extra_cost_note = (payload.get("extra_cost_note") or "").strip() or None
        purchase.sub_total = sub_total
        purchase.discount_value = discount_value
        purchase.shipping_extra = shipping_extra
        purchase.grand_total = grand_total
        purchase.paid_total = paid_total
        purchase.remaining_total = remaining_total
        purchase.purchase_date = purchase_date

        for product, qty, unit_before, item_discount, final_unit, line_total, variant_color in parsed_items:
            purchase_item = PurchaseItem(
                purchase_id=purchase.id,
                product_id=product.id,
                quantity=qty,
                unit_cost_before_discount=unit_before,
                discount_value=item_discount,
                final_unit_cost=final_unit,
                line_total=line_total,
                variant_color=variant_color or None,
            )
            db.session.add(purchase_item)
            db.session.flush()
            try:
                stock_applied_now = _apply_purchase_item_stock(
                    purchase,
                    purchase_item,
                    branch_id,
                    apply_stock,
                )
            except ProductColorError as exc:
                db.session.rollback()
                return jsonify({"success": False, "error": str(exc)}), 400
            if stock_applied_now:
                create_purchase_lot(purchase_item, branch_id)
            product.buy_price = final_unit
            if variant_color:
                update_color_buy_price(product.id, variant_color, final_unit)

        if hasattr(purchase, "stock_applied"):
            purchase.stock_applied = apply_stock

        accounting_applied = _purchase_accounting_applied(purchase)
        for pay in parsed_payments:
            pay.branch_id = branch_id
            db.session.add(pay)
            if not accounting_applied:
                continue
            try:
                _add_purchase_withdraw(pay, purchase, supplier, " (بعد تعديل)")
            except InsufficientTreasuryBalance as exc:
                db.session.rollback()
                return jsonify({"success": False, "error": str(exc)}), 400

        if accounting_applied:
            supplier.total_debt = _safe_int(supplier.total_debt, 0) + grand_total
            supplier.total_paid = _safe_int(supplier.total_paid, 0) + paid_total
            backfill_supplier_payment_allocations(supplier.id)

        if files:
            for f in files:
                if not f or not f.filename:
                    continue
                att = _save_attachment(f, purchase.id)
                if att:
                    db.session.add(att)

        db.session.commit()
        return jsonify({"success": True, "message": f"تم تعديل الفاتورة {purchase.invoice_no} بنجاح"})
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("update purchase failed")
        return jsonify({"success": False, "error": str(e)}), 500


@purchases_bp.route("/api/<int:purchase_id>/cancel", methods=["POST"])
def cancel_purchase(purchase_id):
    if not check_permission("can_manage_inventory"):
        return jsonify({"error": "Unauthorized"}), 403
    _ensure_purchase_schema()

    purchase = Purchase.query.get_or_404(purchase_id)
    if (purchase.status or "").lower() == "cancelled":
        return jsonify({"success": True, "message": "الفاتورة ملغية سابقا"})
    try:
        _reverse_purchase_effects(purchase, "إلغاء الفاتورة")
        purchase.status = "cancelled"
        purchase.remaining_total = 0
        purchase.paid_total = 0
        db.session.commit()
        return jsonify({"success": True, "message": f"تم إلغاء الفاتورة {purchase.invoice_no or purchase.id}"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@purchases_bp.route("/api/<int:purchase_id>/delete", methods=["POST"])
def delete_purchase(purchase_id):
    if not check_permission("can_manage_inventory"):
        return jsonify({"error": "Unauthorized"}), 403
    if not _is_admin_user():
        return jsonify({"success": False, "error": "الحذف مسموح للمدير فقط"}), 403
    _ensure_purchase_schema()
    purchase = Purchase.query.get_or_404(purchase_id)
    try:
        _reverse_purchase_effects(purchase, "حذف الفاتورة", hard_delete=True)
        for att in list(purchase.attachments or []):
            try:
                full = os.path.join(current_app.root_path, att.file_path.replace("/", os.sep))
                if os.path.exists(full):
                    os.remove(full)
            except Exception:
                pass
        db.session.delete(purchase)
        db.session.commit()
        return jsonify({"success": True, "message": "تم حذف الفاتورة"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@purchases_bp.route("/api/<int:purchase_id>/reopen", methods=["POST"])
def reopen_purchase(purchase_id):
    if not check_permission("can_manage_inventory"):
        return jsonify({"error": "Unauthorized"}), 403
    if not _is_admin_user():
        return jsonify({"success": False, "error": "إعادة فتح الفاتورة للمدير فقط"}), 403
    _ensure_purchase_schema()
    purchase = Purchase.query.get_or_404(purchase_id)
    if str(getattr(purchase, "source_module", "") or "").strip().lower() == "food":
        return jsonify({"success": False, "error": "إعادة فتح مشتريات الأغذية تتم من مساحتها المخصصة"}), 400
    if (purchase.status or "").strip().lower() != "cancelled":
        return jsonify({"success": False, "error": "الفاتورة ليست ملغية"}), 400
    purchase.status = "draft"
    db.session.commit()
    return jsonify({"success": True, "message": f"تمت إعادة فتح الفاتورة {purchase.invoice_no or purchase.id}"})


@purchases_bp.route("/api/<int:purchase_id>/unlock-edit", methods=["POST"])
def unlock_purchase_for_edit(purchase_id):
    """
    فتح فاتورة مؤكدة للتحرير بدون عكس محاسبي/مخزني.
    الهدف: قفل المحاسبة الافتراضي مع سماح مسؤول بالتصحيح المتعمد.
    """
    if not check_permission("can_manage_inventory"):
        return jsonify({"error": "Unauthorized"}), 403
    if not _is_admin_user():
        return jsonify({"success": False, "error": "فتح الفاتورة المؤكدة للتحرير للمدير فقط"}), 403
    _ensure_purchase_schema()
    purchase = Purchase.query.get_or_404(purchase_id)
    if str(getattr(purchase, "source_module", "") or "").strip().lower() == "food":
        return jsonify({"success": False, "error": "تحرير مشتريات الأغذية يتم من مساحتها المخصصة"}), 400
    if (purchase.status or "").strip().lower() == "cancelled":
        return jsonify({"success": False, "error": "لا يمكن فتح فاتورة ملغية عبر هذا الإجراء"}), 400
    if (purchase.status or "").strip().lower() == "draft":
        return jsonify({"success": True, "message": "الفاتورة بالفعل في وضع مسودة"})
    if hasattr(purchase, "stock_applied"):
        purchase.stock_applied = True
    purchase.status = "draft"
    db.session.commit()
    return jsonify({"success": True, "message": f"تم فتح الفاتورة {purchase.invoice_no or purchase.id} للتحرير"})


@purchases_bp.route("/api/<int:purchase_id>/clone", methods=["POST"])
def clone_purchase(purchase_id):
    if not check_permission("can_manage_inventory"):
        return jsonify({"error": "Unauthorized"}), 403
    _ensure_purchase_schema()
    src = Purchase.query.get_or_404(purchase_id)
    if str(getattr(src, "source_module", "") or "").strip().lower() == "food":
        return jsonify({"success": False, "error": "استنساخ مشتريات الأغذية يتم من مساحتها المخصصة"}), 400
    try:
        new_purchase = Purchase(
            supplier_id=src.supplier_id,
            product_id=src.product_id,
            quantity=src.quantity,
            price=src.price,
            total=src.total,
            invoice_no=_next_invoice_no(),
            status="draft",
            branch_code=src.branch_code,
            branch_id=src.branch_id,
            reference_no=src.reference_no,
            supplier_invoice_no=src.supplier_invoice_no,
            address=src.address,
            purchase_mode=src.purchase_mode,
            payment_term=src.payment_term,
            notes=src.notes,
            shipping_details=src.shipping_details,
            extra_cost_note=src.extra_cost_note,
            sub_total=src.sub_total,
            discount_value=src.discount_value,
            shipping_extra=src.shipping_extra,
            grand_total=src.grand_total,
            paid_total=0,
            remaining_total=src.grand_total or src.total or 0,
            purchase_date=date.today(),
            created_by_employee_id=session.get("user_id"),
        )
        db.session.add(new_purchase)
        db.session.flush()
        new_purchase.stock_revision = _allocate_purchase_stock_revision(new_purchase.id)

        for it in (src.items or []):
            db.session.add(
                PurchaseItem(
                    purchase_id=new_purchase.id,
                    product_id=it.product_id,
                    quantity=it.quantity,
                    unit_cost_before_discount=it.unit_cost_before_discount,
                    discount_value=it.discount_value,
                    final_unit_cost=it.final_unit_cost,
                    line_total=it.line_total,
                    variant_color=getattr(it, "variant_color", None),
                )
            )

        for att in (src.attachments or []):
            db.session.add(
                PurchaseAttachment(
                    purchase_id=new_purchase.id,
                    file_path=att.file_path,
                    original_name=att.original_name,
                    mime_type=att.mime_type,
                    file_size=att.file_size,
                )
            )

        db.session.commit()
        return jsonify(
            {
                "success": True,
                "message": f"تم استنساخ الفاتورة إلى مسودة جديدة {new_purchase.invoice_no}",
                "purchase_id": new_purchase.id,
            }
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@purchases_bp.route("/print/<int:purchase_id>")
def print_purchase(purchase_id):
    if not (
        check_permission("can_manage_inventory")
        or check_permission("can_manage_suppliers")
    ):
        return redirect("/pos"), 403
    _ensure_purchase_schema()
    from sqlalchemy.orm import joinedload
    from models.purchase_item import PurchaseItem

    purchase = (
        Purchase.query.options(
            joinedload(Purchase.items).joinedload(PurchaseItem.product),
            joinedload(Purchase.supplier),
            joinedload(Purchase.payments),
        )
        .get_or_404(purchase_id)
    )
    effective_paid, effective_remaining, later_paid = (
        effective_purchase_payment_totals(purchase)
    )
    return render_template(
        "purchase_print.html",
        purchase=purchase,
        effective_paid_total=effective_paid,
        effective_remaining_total=effective_remaining,
        later_paid_total=later_paid,
    )


# ======================================
# Paginated purchases JSON (desktop / API clients)
# ======================================
def _purchase_tab(rec: dict) -> str:
    status = (rec.get("status") or "").lower()
    if status == "cancelled":
        return "cancelled"
    if status == "draft":
        return "draft"
    return "unpaid" if int(rec.get("remaining_total") or 0) > 0 else "confirmed"


def _purchase_supplier_options() -> list[dict]:
    """Supplier choices exactly as FINORA's suppliers page lists them.

    Shared mode: suppliers are company-wide, so each supplier's branch copies
    collapse into one row (routes.suppliers._shared_supplier_rows); saving maps
    to the branch copy via _supplier_for_purchase_branch. Independent mode:
    only the current branch's suppliers.
    """
    from routes.suppliers import _shared_supplier_rows

    if independent_branches_enabled():
        rows = Supplier.query.order_by(Supplier.name.asc(), Supplier.id.asc()).all()
        return [{"id": row.id, "name": row.name} for row in rows]
    rows = Supplier.query.execution_options(skip_branch_scope=True).all()
    return [{"id": row.id, "name": row.name} for row in _shared_supplier_rows(rows)]


@purchases_bp.route("/api/page")
def purchases_page_api(*, _snapshot=False):
    """Same rows and filters as /api/list, served one page at a time with tab counts and a summary."""
    if not check_permission("can_manage_inventory"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    _ensure_purchase_schema()

    supplier_id = request.args.get("supplier_id", type=int)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    search = (request.args.get("search", "") or "").strip().lower()
    query = Purchase.query
    if supplier_id:
        query = query.filter(Purchase.supplier_id == supplier_id)
    try:
        if date_from:
            query = query.filter(Purchase.purchase_date >= datetime.strptime(date_from, "%Y-%m-%d").date())
        if date_to:
            query = query.filter(Purchase.purchase_date <= datetime.strptime(date_to, "%Y-%m-%d").date())
    except ValueError:
        return jsonify({"success": False, "error": "صيغة التاريخ غير صحيحة"}), 400

    purchases = query.order_by(Purchase.created_at.desc()).all()
    allocated = purchase_allocation_totals_for_ids([row.id for row in purchases])
    rows = []
    for purchase in purchases:
        try:
            rec = _purchase_list_record(purchase, allocated.get(purchase.id, 0))
        except Exception:
            from flask import current_app
            current_app.logger.exception("purchases api/page row failed purchase_id=%s", purchase.id)
            continue
        rec["tab"] = _purchase_tab(rec)
        rows.append(rec)
    if search:
        rows = [
            r for r in rows
            if search in (r["invoice_no"] or "").lower()
            or search in (r["supplier_invoice_no"] or "").lower()
            or search in (r["supplier"] or "").lower()
            or search in (r["first_product"] or "").lower()
        ]

    active = [r for r in rows if r["tab"] != "cancelled"]
    summary = {
        "total_amount": sum(int(r["grand_total"] or 0) for r in active if r["tab"] != "draft"),
        "count": len(active),
        "draft": sum(1 for r in rows if r["tab"] == "draft"),
        "unpaid": sum(1 for r in rows if r["tab"] == "unpaid"),
        "remaining_amount": sum(int(r["remaining_total"] or 0) for r in active),
    }
    counts = {"all": len(rows)}
    for tab in ("draft", "confirmed", "unpaid", "cancelled"):
        counts[tab] = sum(1 for r in rows if r["tab"] == tab)

    tab = (request.args.get("tab") or "all").strip()
    if tab in counts and tab != "all":
        rows = [r for r in rows if r["tab"] == tab]

    page_size = (len(rows) or 1) if _snapshot else min(100, max(1, request.args.get("page_size", 25, type=int) or 25))
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, request.args.get("page", 1, type=int) or 1), total_pages)
    start = (page - 1) * page_size
    return jsonify({
        "success": True,
        "rows": rows[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "counts": counts,
        "summary": summary,
        "suppliers": _purchase_supplier_options(),
    })
