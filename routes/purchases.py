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
from utils.permission_checks import check_permission
from utils.activity_logger import log_activity
from utils.treasury_helpers import resolve_treasury_account_id, get_default_cash_account, treasury_choices_for_form
from utils.treasury_calculations import assert_sufficient_balance, InsufficientTreasuryBalance
from utils.treasury_schema_guard import ensure_treasury_schema
from utils.branch_migration import ensure_branch_schema, get_default_branch
from utils.branch_context import current_branch_id, resolve_branch_id
from utils.branch_stock_service import deduct_stock, receive_stock
from utils.order_item_schema_guard import ensure_order_item_schema
from utils.product_color_service import (
    ProductColorError,
    colors_for_product_dict,
    deduct_color_stock,
    ensure_color_variant,
    product_has_colors,
    receive_color_stock,
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
    ensure_order_item_schema()


def _purchase_line_variant_color(raw: dict) -> str:
    return (raw.get("color") or raw.get("variant_color") or "").strip()


def _parse_purchase_line(raw: dict, idx: int):
    product_id = _safe_int(raw.get("product_id"), 0)
    qty = _safe_int(raw.get("quantity"), 0)
    if product_id <= 0 or qty <= 0:
        raise ValueError(f"العنصر رقم {idx + 1} غير صالح.")
    unit_before = _safe_int(raw.get("unit_cost_before_discount") or raw.get("unit_cost"), 0)
    item_discount = _safe_int(raw.get("discount_value"), 0)
    final_unit = max(unit_before - item_discount, 0)
    line_total = _safe_int(raw.get("line_total"), final_unit * qty)
    product = Product.query.get_or_404(product_id)
    variant_color = _purchase_line_variant_color(raw)
    if product_has_colors(product) and not variant_color:
        raise ValueError(f"يجب اختيار لون للمنتج: {product.name}")
    if variant_color:
        ensure_color_variant(product.id, variant_color)
    return product, qty, unit_before, item_discount, final_unit, line_total, variant_color


def _apply_purchase_item_stock(product, qty: int, variant_color: str, branch_id: int | None, apply_stock: bool) -> None:
    if not apply_stock:
        return
    if branch_id:
        receive_stock(branch_id, product.id, qty)
    else:
        product.quantity = _safe_int(product.quantity, 0) + qty
    if variant_color:
        receive_color_stock(product.id, variant_color, qty)


def _reverse_purchase_item_stock(it, branch_id: int | None) -> None:
    if not it.product:
        return
    qty = _safe_int(it.quantity, 0)
    if qty <= 0:
        return
    if branch_id:
        deduct_stock(branch_id, it.product.id, qty)
    else:
        current_qty = _safe_int(it.product.quantity, 0)
        if current_qty < qty:
            raise ValueError(
                f"لا يمكن عكس فاتورة الشراء لأن مخزون {it.product.name} أقل من كمية الفاتورة."
            )
        it.product.quantity = current_qty - qty
    variant_color = (getattr(it, "variant_color", None) or "").strip()
    if variant_color:
        try:
            deduct_color_stock(it.product.id, variant_color, qty)
        except ProductColorError as exc:
            raise ValueError(str(exc)) from exc


def _fmt_iq(num):
    return f"{int(num or 0):,}"


def _next_invoice_no():
    today = datetime.utcnow().strftime("%Y%m%d")
    count_today = Purchase.query.filter(func.date(Purchase.created_at) == date.today()).count()
    return f"PUR-{today}-{count_today + 1:04d}"


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
    return (method or "").strip().lower() in ("bank", "بنك")


def _affects_treasury(method):
    return _is_cash_method(method) or _is_bank_method(method)


def _payment_treasury_id(pay_payload: dict, payment_method: str) -> int:
    ensure_treasury_schema()
    raw_id = pay_payload.get("treasury_account_id")
    if raw_id not in (None, ""):
        return resolve_treasury_account_id(raw_id)
    if _is_bank_method(payment_method):
        banks = treasury_choices_for_form(banks_only=True)
        if banks:
            return banks[0].id
    return get_default_cash_account().id


def _add_purchase_withdraw(pay: PurchasePayment, purchase, supplier, note_suffix: str = ""):
    if not _affects_treasury(pay.payment_method):
        return
    treasury_id = pay.treasury_account_id or get_default_cash_account().id
    assert_sufficient_balance(treasury_id, int(pay.amount or 0))
    label = "بنك" if _is_bank_method(pay.payment_method) else "صندوق"
    db.session.add(
        AccountTransaction(
            type="withdraw",
            amount=int(pay.amount or 0),
            note=f"{label} - دفعة شراء {purchase.invoice_no} للمورد {supplier.name}{note_suffix}",
            treasury_account_id=treasury_id,
        )
    )


def _treasury_paid_amount(purchase):
    return sum(_treasury_paid_by_account(purchase).values())


def _treasury_paid_by_account(purchase) -> dict[int, int]:
    default_cash_id = get_default_cash_account().id
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
    return (status or "confirmed").strip().lower() not in {"draft", "cancelled", "canceled"}


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
    if status == "draft":
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


def _reverse_purchase_effects(purchase, reason):
    # Reverse stock
    branch_id = getattr(purchase, "branch_id", None) or _resolve_purchase_branch_id({}, getattr(purchase, "branch_code", None))
    items = list(purchase.items or [])
    if not items and getattr(purchase, "product", None):
        items = [purchase]

    if _purchase_stock_applied(purchase):
        for it in items:
            try:
                _reverse_purchase_item_stock(it, branch_id)
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
                type="deposit",
                amount=treasury_paid,
                note=f"صندوق - عكس دفعات شراء {purchase.invoice_no or purchase.id} ({reason})",
                treasury_account_id=treasury_id,
            )
        )


def _create_purchase_from_payload(payload, files):
    supplier_id = int(payload.get("supplier_id") or 0)
    supplier = Supplier.query.get_or_404(supplier_id)
    items = payload.get("items") or []
    if not items:
        return None, "يجب إضافة عنصر واحد على الأقل."

    p_date = payload.get("purchase_date")
    try:
        purchase_date = datetime.strptime(p_date, "%Y-%m-%d").date() if p_date else date.today()
    except ValueError:
        purchase_date = date.today()

    discount_value = int(payload.get("discount_value") or 0)
    shipping_extra = int(payload.get("shipping_extra") or 0)
    payment_term = (payload.get("payment_term") or "").strip() or None
    purchase_mode = (payload.get("purchase_mode") or "").strip() or "credit"
    branch_code = (payload.get("branch_code") or "").strip() or None
    branch_id = payload.get("branch_id")
    if branch_id:
        branch_id = int(branch_id)
    elif branch_code:
        from models.branch import Branch

        match = Branch.query.filter(db.func.upper(Branch.code) == branch_code.upper()).first()
        branch_id = match.id if match else None
    if not branch_id:
        branch_id = resolve_branch_id() or (get_default_branch().id if get_default_branch() else None)
    reference_no = (payload.get("reference_no") or "").strip() or None
    supplier_invoice_no = (payload.get("supplier_invoice_no") or "").strip() or None
    address = (payload.get("address") or "").strip() or None
    notes = (payload.get("notes") or "").strip() or None
    shipping_details = (payload.get("shipping_details") or "").strip() or None
    extra_cost_note = (payload.get("extra_cost_note") or "").strip() or None
    status = (payload.get("status") or "confirmed").strip()
    apply_stock = _purchase_status_applies_stock(status)

    parsed_items = []
    sub_total = 0
    legacy_product_id = None
    legacy_qty = 0
    legacy_price = 0
    for idx, raw in enumerate(items):
        try:
            product, qty, unit_before, item_discount, final_unit, line_total, variant_color = _parse_purchase_line(raw, idx)
        except ValueError as exc:
            return None, str(exc)
        parsed_items.append((product, qty, unit_before, item_discount, final_unit, line_total, variant_color))
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
        treasury_account_id = _payment_treasury_id(pay, payment_method)
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
    paid_total = min(paid_total, grand_total)
    remaining_total = max(grand_total - paid_total, 0)
    if purchase_mode == "cash" and paid_total <= 0:
        paid_total = grand_total
        remaining_total = 0
        parsed_payments.append(
            PurchasePayment(
                amount=paid_total,
                paid_at=datetime.utcnow(),
                payment_method="cash",
                account_name=None,
                note="دفعة نقدية تلقائية (شراء نقدي كامل)",
                treasury_account_id=get_default_cash_account().id,
            )
        )

    purchase = Purchase(
        supplier_id=supplier.id,
        product_id=legacy_product_id or parsed_items[0][0].id,
        quantity=legacy_qty,
        price=legacy_price,
        total=grand_total,
        invoice_no=(payload.get("invoice_no") or "").strip() or _next_invoice_no(),
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
    )
    db.session.add(purchase)
    db.session.flush()

    for product, qty, unit_before, item_discount, final_unit, line_total, variant_color in parsed_items:
        db.session.add(
            PurchaseItem(
                purchase_id=purchase.id,
                product_id=product.id,
                quantity=qty,
                unit_cost_before_discount=unit_before,
                discount_value=item_discount,
                final_unit_cost=final_unit,
                line_total=line_total,
                variant_color=variant_color or None,
            )
        )
        try:
            _apply_purchase_item_stock(product, qty, variant_color, branch_id, apply_stock)
        except ProductColorError as exc:
            return None, str(exc)
        product.buy_price = final_unit

    accounting_applied = _purchase_accounting_applied(purchase)
    for pay in parsed_payments:
        pay.purchase_id = purchase.id
        db.session.add(pay)
        if accounting_applied:
            try:
                _add_purchase_withdraw(pay, purchase, supplier)
            except InsufficientTreasuryBalance as exc:
                db.session.rollback()
                return None, str(exc)

    # supplier ledger: debt is the gross obligation, paid is the actual payments.
    if accounting_applied:
        supplier.total_debt = int(supplier.total_debt or 0) + grand_total
        supplier.total_paid = int(supplier.total_paid or 0) + paid_total

    # attachments
    if files:
        for f in files:
            if not f or not f.filename:
                continue
            att = _save_attachment(f, purchase.id)
            if att:
                db.session.add(att)

    db.session.commit()
    return purchase, None


def _get_purchase_stats():
    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
    try:
        purchases_list = Purchase.query.order_by(Purchase.created_at.desc()).limit(500).all()
        total_purchases = sum(int(p.grand_total or p.total or 0) for p in purchases_list)
        purchases_count = len(purchases_list)
        current_month_start = date.today().replace(day=1)
        monthly_total = sum(
            int(p.grand_total or p.total or 0)
            for p in Purchase.query.filter(Purchase.purchase_date >= current_month_start).all()
        )
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


def _prepare_purchases_context():
    try:
        _ensure_purchase_schema()
        ensure_branch_schema()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("purchase schema migration failed")
    from models.branch import Branch

    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name.asc()).all()
    stats = _get_purchase_stats()
    return {
        "suppliers": suppliers,
        "branches": branches,
        "treasury_choices": treasury_choices_for_form(),
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
def search_products_for_purchase():
    if not check_permission("can_manage_inventory"):
        return jsonify([]), 403
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([])
    by_barcode = Product.query.filter(Product.active.is_(True), Product.barcode == q).first()
    if by_barcode:
        return jsonify([_product_search_row(by_barcode)])
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
        .limit(15)
        .all()
    )
    return jsonify([_product_search_row(p) for p in rows])


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

    data = []
    for p in rows:
        try:
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
                "paid_total": int(p.paid_total or 0),
                "remaining_total": int(p.remaining_total if p.remaining_total is not None else max(int((p.grand_total or p.total or 0) - (p.paid_total or 0)), 0)),
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
            data.append(rec)
        except Exception:
            from flask import current_app
            current_app.logger.exception("purchases api/list row failed purchase_id=%s", getattr(p, "id", "?"))
            continue

    if search:
        data = [
            r for r in data
            if search in (r["invoice_no"] or "").lower()
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
        "paid_total": int(p.paid_total or 0),
        "remaining_total": int(p.remaining_total if p.remaining_total is not None else max(int((p.grand_total or p.total or 0) - (p.paid_total or 0)), 0)),
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
    csv_lines = ["التاريخ,رقم الفاتورة,المورد,عدد العناصر,الإجمالي,المدفوع,المتبقي,حالة الشراء\n"]
    for p in rows:
        item_count = len(p.items or []) if p.items else 1
        csv_lines.append(
            f"{(p.purchase_date.strftime('%Y-%m-%d') if p.purchase_date else '')},"
            f"{p.invoice_no or ('LEG-' + str(p.id))},"
            f"{(p.supplier.name if p.supplier else '')},"
            f"{item_count},"
            f"{int(p.grand_total or p.total or 0)},"
            f"{int(p.paid_total or 0)},"
            f"{int(p.remaining_total or 0)},"
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
        _reverse_purchase_effects(purchase, "تعديل الفاتورة")

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
        items = payload.get("items") or []
        if not items:
            return jsonify({"success": False, "error": "يجب إضافة عنصر واحد على الأقل."}), 400

        sub_total = 0
        legacy_product_id = None
        legacy_qty = 0
        legacy_price = 0
        parsed_items = []
        for idx, raw in enumerate(items):
            try:
                product, qty, unit_before, item_discount, final_unit, line_total, variant_color = _parse_purchase_line(raw, idx)
            except ValueError as exc:
                return jsonify({"success": False, "error": str(exc)}), 400
            parsed_items.append((product, qty, unit_before, item_discount, final_unit, line_total, variant_color))
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
            treasury_account_id = _payment_treasury_id(pay, payment_method)
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
        branch_code = (payload.get("branch_code") or "").strip() or None
        branch_id = _resolve_purchase_branch_id(payload, branch_code)
        grand_total = max(sub_total - discount_value + shipping_extra, 0)
        paid_total = min(paid_total, grand_total)
        remaining_total = max(grand_total - paid_total, 0)
        if purchase_mode == "cash" and paid_total <= 0:
            paid_total = grand_total
            remaining_total = 0
            parsed_payments.append(
                PurchasePayment(
                    purchase_id=purchase.id,
                    amount=paid_total,
                    paid_at=datetime.utcnow(),
                    payment_method="cash",
                    note="دفعة نقدية تلقائية (شراء نقدي كامل)",
                    treasury_account_id=get_default_cash_account().id,
                )
            )

        new_status = (payload.get("status") or "confirmed").strip()
        apply_stock = _purchase_status_applies_stock(new_status)

        purchase.supplier_id = supplier.id
        purchase.product_id = legacy_product_id
        purchase.quantity = legacy_qty
        purchase.price = legacy_price
        purchase.total = grand_total
        purchase.invoice_no = (payload.get("invoice_no") or "").strip() or (purchase.invoice_no or _next_invoice_no())
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
            db.session.add(
                PurchaseItem(
                    purchase_id=purchase.id,
                    product_id=product.id,
                    quantity=qty,
                    unit_cost_before_discount=unit_before,
                    discount_value=item_discount,
                    final_unit_cost=final_unit,
                    line_total=line_total,
                    variant_color=variant_color or None,
                )
            )
            try:
                _apply_purchase_item_stock(product, qty, variant_color, branch_id, apply_stock)
            except ProductColorError as exc:
                db.session.rollback()
                return jsonify({"success": False, "error": str(exc)}), 400
            product.buy_price = final_unit

        if hasattr(purchase, "stock_applied"):
            purchase.stock_applied = apply_stock

        accounting_applied = _purchase_accounting_applied(purchase)
        for pay in parsed_payments:
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
        _reverse_purchase_effects(purchase, "حذف الفاتورة")
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
    return render_template("purchase_print.html", purchase=purchase)
