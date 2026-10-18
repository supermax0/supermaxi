"""HTTP-free POS checkout: preview and create share one inventory/accounting path."""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

from flask import g

from extensions import db
from models.customer import Customer
from models.employee import Employee
from models.invoice import Invoice
from models.order_item import OrderItem
from models.page import Page
from models.product import Product
from utils.activity_logger import INVOICE_SNAPSHOT_FIELDS, log_activity, snapshot_attrs
from utils.branch_context import current_branch_id
from utils.branch_migration import get_default_branch
from utils.branch_product_service import product_for_branch
from utils.branch_stock_service import BranchStockError
from utils.inventory_lots import InventoryLotError
from utils.cash_calculations import _effective_paid_amount
from utils.invoice_mutation_policy import (
    PAID_INVOICE_MUTATION_DISABLED_MESSAGE,
    paid_invoice_mutation_denied,
)
from utils.order_shipping import apply_manual_delivery_fee_on_payment, get_shipping_fee_from_invoice
from utils.order_stock_lock import (
    apply_stock_actions,
    check_stock_rows,
    clear_order_stock_lock,
    mark_order_stock_locked,
)
from utils.order_stock_policy import (
    OrderStockError,
    deduct_order_stock,
    deferred_stock_enabled,
    order_needs_stock,
    restore_order_stock,
    stock_is_deducted,
)
from utils.payment_ledger import append_payment_ledger_delta
from utils.permission_checks import employee_can
from utils.product_color_service import ProductColorError, product_has_colors
from utils.product_schema_guard import ensure_customer_blacklist_columns
from utils.trade_in_service import (
    TradeInError,
    employee_can_access_replacement_product,
    resolve_sale_selection,
    sync_trade_in_receipts,
)

from services.pos_catalog import shared_catalog_mode

_POS_SUBMISSION_LOCK = threading.Lock()
_POS_SUBMISSIONS: dict[str, dict] = {}
_POS_SUBMISSION_TTL_SECONDS = 10 * 60


class PosCheckoutError(Exception):
    def __init__(self, message: str, status_code: int = 400, *, code: str | None = None, payload: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        body = {"success": False, "error": message}
        if code:
            body["code"] = code
        if payload:
            body.update(payload)
        self.payload = body


def _cleanup_pos_submissions(now=None):
    now = now or time.time()
    expired = [
        token
        for token, record in _POS_SUBMISSIONS.items()
        if now - float(record.get("created_at", 0) or 0) > _POS_SUBMISSION_TTL_SECONDS
    ]
    for token in expired:
        _POS_SUBMISSIONS.pop(token, None)


def _submission_key(token: str, employee: Employee) -> str:
    tenant = str(getattr(g, "tenant", None) or "")
    employee_id = int(getattr(employee, "id", 0) or 0)
    return f"{tenant}:{employee_id}:{token}"


def _begin_pos_submission(token: str, employee: Employee):
    token = (token or "").strip()
    if not token:
        return "new", None, ""
    key = _submission_key(token, employee)
    now = time.time()
    with _POS_SUBMISSION_LOCK:
        _cleanup_pos_submissions(now)
        existing = _POS_SUBMISSIONS.get(key)
        if existing:
            if existing.get("status") == "done" and existing.get("response"):
                return "done", dict(existing["response"]), key
            return "busy", None, key
        _POS_SUBMISSIONS[key] = {"status": "busy", "created_at": now}
    return "new", None, key


def _finish_pos_submission(key: str, response=None, success=False):
    key = (key or "").strip()
    if not key:
        return
    with _POS_SUBMISSION_LOCK:
        if success and response:
            _POS_SUBMISSIONS[key] = {
                "status": "done",
                "response": dict(response),
                "created_at": time.time(),
            }
        else:
            _POS_SUBMISSIONS.pop(key, None)


def activate_pos_request_branch(branch_id):
    from models.branch import Branch

    branch = Branch.query.filter_by(id=int(branch_id), is_active=True).first()
    if not branch:
        return None
    g.branch = branch
    g.view_all_branches = False
    return branch


def bind_pos_employee_context(employee: Employee, branch_id=None):
    """Set request branch context from an authenticated employee (no session)."""
    from models.branch import Branch
    from utils.branch_migration import ensure_branch_schema
    from utils.branch_mode import independent_branches_enabled

    ensure_branch_schema()
    g.pos_employee = employee
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.is_default.desc(), Branch.id).all()
    g.branches = branches
    g.independent_branches_enabled = independent_branches_enabled()
    g.view_all_branches = bool(employee and employee.role == "admin")
    target_id = branch_id or getattr(employee, "branch_id", None)
    branch = None
    if target_id:
        try:
            branch = Branch.query.filter_by(id=int(target_id), is_active=True).first()
        except (TypeError, ValueError):
            branch = None
    g.branch = branch or get_default_branch()
    g.branch_scope_ready = True
    return g.branch


def resolve_checkout_branch(
    employee: Employee,
    requested_branch_id,
    *,
    allow_admin_any_branch: bool = True,
    require_explicit_branch: bool = False,
) -> int:
    from models.branch import Branch
    from utils.branch_mode import independent_branches_enabled

    if not independent_branches_enabled():
        default = get_default_branch()
        if not default:
            raise PosCheckoutError("لا يوجد فرع رئيسي للحفظ", 400, code="BRANCH_REQUIRED")
        return int(default.id)

    if not employee:
        raise PosCheckoutError("موظف غير صالح", 401, code="UNAUTHORIZED")

    requested = None
    if requested_branch_id not in (None, "", 0, "0", "all"):
        try:
            requested = Branch.query.filter_by(id=int(requested_branch_id), is_active=True).first()
        except (TypeError, ValueError):
            requested = None
        if not requested:
            raise PosCheckoutError("الفرع المطلوب غير موجود أو غير نشط", 400, code="BRANCH_INVALID")

    if employee.role == "admin":
        if allow_admin_any_branch and requested:
            return int(requested.id)
        if requested:
            return int(requested.id)
        from utils.branch_management import operating_branch_must_be_explicit

        # Interactive selling (web / desktop POS) must name its branch; machine integrations keep the
        # company-default behaviour they were built against.
        if require_explicit_branch and operating_branch_must_be_explicit():
            raise PosCheckoutError(
                "اختر فرعاً تشغيلياً واحداً قبل البيع — «جميع الفروع» للعرض المجمّع فقط",
                400,
                code="BRANCH_REQUIRED",
            )
        default = get_default_branch()
        if default:
            return int(default.id)
        raise PosCheckoutError("يجب اختيار الفرع قبل الحفظ", 400, code="BRANCH_REQUIRED")

    from utils.branch_assignments import assigned_branch_ids

    allowed = assigned_branch_ids(employee)
    if not allowed:
        raise PosCheckoutError("لم يتم تعيين فرع لهذا الموظف", 403, code="BRANCH_NOT_ASSIGNED")
    if requested:
        if int(requested.id) not in allowed:
            raise PosCheckoutError("لا يمكنك استخدام فرع آخر", 403, code="BRANCH_NOT_ALLOWED")
        return int(requested.id)
    chosen = current_branch_id()
    if chosen is not None and int(chosen) in allowed:
        return int(chosen)
    return int(employee.branch_id) if employee.branch_id else int(allowed[0])


def fallback_fulfillment_branch_id(invoice=None):
    branch_id = getattr(invoice, "branch_id", None) if invoice else None
    if branch_id:
        return branch_id
    branch_id = current_branch_id()
    if branch_id:
        return branch_id
    default_branch = get_default_branch()
    return default_branch.id if default_branch else None


def _item_qty(raw: dict) -> int:
    for key in ("qty", "quantity"):
        if raw.get(key) not in (None, ""):
            try:
                return int(raw.get(key) or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def _parse_scheduled_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _normalize_line_for_source(raw: dict, *, source: str, allow_override: bool) -> dict:
    line = dict(raw or {})
    line["qty"] = _item_qty(line)
    if source != "pos_api":
        return line
    override = line.get("override_price")
    has_override = override not in (None, "", 0, "0")
    has_client_price = line.get("price") not in (None, "", 0, "0")
    if has_override or has_client_price:
        if not allow_override:
            raise PosCheckoutError(
                "الموظف لا يملك صلاحية تعديل سعر البيع",
                403,
                code="PRICE_OVERRIDE_NOT_ALLOWED",
            )
        line["price"] = override if has_override else line.get("price")
    else:
        line.pop("price", None)
    return line


def _normalize_lines(items: list, *, source: str, employee: Employee) -> list[dict]:
    allow_override = employee_can(employee, "edit_price")
    normalized = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        normalized.append(_normalize_line_for_source(raw, source=source, allow_override=allow_override))
    return normalized


def resolve_checkout_lines(
    employee: Employee,
    items: list,
    *,
    invoice_branch_id,
    customer,
    source: str,
    shared_catalog: bool,
):
    normalized = _normalize_lines(items, source=source, employee=employee)
    if not normalized:
        raise PosCheckoutError("لا توجد منتجات", 400, code="VALIDATION_ERROR")

    resolved = []
    for raw in normalized:
        product_query = Product.query
        if employee.role == "admin" and invoice_branch_id:
            product_query = product_query.execution_options(skip_branch_scope=True)
        product_filters = [Product.id == raw.get("product_id")]
        if not shared_catalog:
            product_filters.append(Product.branch_id == invoice_branch_id)
        product = product_query.filter(*product_filters).first()
        if not product:
            raise PosCheckoutError("منتج غير موجود", 400, code="PRODUCT_NOT_FOUND")
        if shared_catalog and invoice_branch_id:
            local_product = product_for_branch(product, int(invoice_branch_id), create=False)
            if local_product is not None:
                product = local_product
        if not shared_catalog and int(product.branch_id or 0) != int(invoice_branch_id or 0):
            raise PosCheckoutError("المنتج لا يتبع فرع الطلب", 400, code="PRODUCT_BRANCH_MISMATCH")
        if not employee_can_access_replacement_product(employee, product):
            raise PosCheckoutError("منتج استبدال متاح للإدمن فقط", 403, code="FORBIDDEN")

        qty = int(raw.get("qty") or 0)
        if qty <= 0:
            raise PosCheckoutError("كمية المنتج غير صالحة", 400, code="INVALID_QTY")

        variant_color = (raw.get("color") or raw.get("variant_color") or "").strip()
        if product_has_colors(product) and not variant_color:
            raise PosCheckoutError(f"يجب اختيار لون للمنتج: {product.name}", 400, code="COLOR_REQUIRED")

        explicit_branch = (
            int(product.branch_id)
            if shared_catalog and product.branch_id
            else (int(invoice_branch_id) if invoice_branch_id else None)
        )
        from modules.inventory_locations.selection import parse as parse_storage_source
        from utils.inventory_lots import InventoryLotError
        try:storage_source=parse_storage_source(explicit_branch,raw)
        except InventoryLotError as exc:raise PosCheckoutError(str(exc),400,code='STORAGE_SOURCE_INVALID') from exc
        try:
            sale_mode, item_price, _source_product = resolve_sale_selection(
                product,
                raw,
                allow_custom_price=employee_can(employee, "edit_price"),
                customer_city=getattr(customer, "city", None),
            )
        except TradeInError as exc:
            raise PosCheckoutError(str(exc), 400, code="SALE_SELECTION") from exc

        item_total = int(item_price) * qty
        resolved.append(
            {
                "raw": raw,
                "product": product,
                "qty": qty,
                "price": int(item_price),
                "sale_mode": sale_mode,
                "variant_color": variant_color or None,
                "fulfillment_branch_id": explicit_branch,
                "storage_source":storage_source,
                "line_total": item_total,
                "name": product.name,
            }
        )
    return resolved


def _parse_discount(raw_data: dict | None, subtotal: int) -> int:
    data = raw_data or {}
    raw_discount = data.get("discount_amount")
    if raw_discount is None:
        raw_discount = data.get("discount_value") or data.get("discount")
    try:
        discount_amount = max(0, int(raw_discount or 0))
    except (TypeError, ValueError):
        discount_amount = 0
    return min(discount_amount, subtotal)


def preview_pos_order(
    *,
    employee: Employee,
    customer_id,
    items: list,
    branch_id=None,
    note=None,
    source: str = "pos_api",
    raw_data: dict | None = None,
) -> dict:
    ensure_customer_blacklist_columns()
    if not employee:
        raise PosCheckoutError("موظف غير صالح", 403, code="UNAUTHORIZED")
    if not customer_id:
        raise PosCheckoutError("يجب اختيار زبون", 400, code="CUSTOMER_REQUIRED")
    if not items:
        raise PosCheckoutError("لا توجد منتجات", 400, code="VALIDATION_ERROR")

    shared_catalog = shared_catalog_mode()
    new_branch_id = resolve_checkout_branch(employee, branch_id, allow_admin_any_branch=True)
    if not activate_pos_request_branch(new_branch_id):
        raise PosCheckoutError("فرع خصم المخزون غير موجود أو غير نشط", 400, code="BRANCH_INVALID")

    customer_query = Customer.query
    if employee.role == "admin" and new_branch_id:
        customer_query = customer_query.execution_options(skip_branch_scope=True)
    customer = customer_query.filter(Customer.id == customer_id).first()
    if not customer:
        raise PosCheckoutError("الزبون غير موجود", 400, code="CUSTOMER_NOT_FOUND")
    if getattr(customer, "is_blacklisted", False):
        raise PosCheckoutError(
            "هذا الزبون في القائمة السوداء — لا يُسمح بإنشاء طلب له.",
            400,
            code="BLACKLISTED",
            payload={"blacklisted": True},
        )
    if not shared_catalog and new_branch_id and int(customer.branch_id or 0) != int(new_branch_id):
        raise PosCheckoutError("الزبون لا يتبع الفرع المختار", 400, code="CUSTOMER_BRANCH_MISMATCH")

    resolved = resolve_checkout_lines(
        employee,
        items,
        invoice_branch_id=new_branch_id,
        customer=customer,
        source=source,
        shared_catalog=shared_catalog,
    )
    subtotal = sum(row["line_total"] for row in resolved)
    discount_amount = _parse_discount(raw_data, subtotal)
    total = max(0, subtotal - discount_amount)

    stock_rows = [
        {
            "product": row["product"],
            "product_id": row["product"].id,
            "quantity": row["qty"],
            "variant_color": row["variant_color"],
            "fulfillment_branch_id": row["fulfillment_branch_id"],
            "storage_location_id":row['storage_source']['location_id'],
            "storage_automatic":row['storage_source']['automatic'],
            "storage_source_selected":row['storage_source']['provided'],
        }
        for row in resolved
    ]
    stock_check = check_stock_rows(stock_rows, preferred_branch_id=new_branch_id)
    stock_ok = bool(getattr(stock_check, "can_fulfill", True))

    return {
        "subtotal": subtotal,
        "discount": discount_amount,
        "total": total,
        "stock_ok": stock_ok,
        "stock_reason": getattr(stock_check, "reason_text", None) if not stock_ok else None,
        "branch_id": new_branch_id,
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "province": customer.city or "",
        },
        "note": (note or "").strip() or None,
        "items": [
            {
                "product_id": row["product"].id,
                "name": row["name"],
                "quantity": row["qty"],
                "unit_price": row["price"],
                "line_total": row["line_total"],
            }
            for row in resolved
        ],
    }


def create_pos_order(
    *,
    employee: Employee,
    customer_id,
    items: list,
    branch_id=None,
    note=None,
    scheduled_date=None,
    page_id=None,
    discount_amount=None,
    order_id=None,
    submission_token: str | None = None,
    source: str = "web_pos",
    raw_data: dict | None = None,
    customer_updates: dict | None = None,
    commit: bool = True,
) -> dict:
    if not commit and (order_id or submission_token):
        raise PosCheckoutError("المعاملة الخارجية تدعم البيع الجديد فقط", 400)
    ensure_customer_blacklist_columns()
    if not employee:
        raise PosCheckoutError("موظف غير صالح", 403, code="UNAUTHORIZED")

    shared_catalog = shared_catalog_mode()
    try:
        editing_order_id = int(order_id) if order_id not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        editing_order_id = None

    editing_invoice = None
    if editing_order_id:
        invoice_query = Invoice.query
        if employee.role == "admin":
            invoice_query = invoice_query.execution_options(skip_branch_scope=True)
        editing_invoice = invoice_query.filter(Invoice.id == editing_order_id).first()
        if not editing_invoice:
            raise PosCheckoutError("الطلب المراد تعديله غير موجود", 404, code="NOT_FOUND")
        new_branch_id = resolve_checkout_branch(
            employee,
            editing_invoice.branch_id or branch_id,
            allow_admin_any_branch=(employee.role == "admin"),
            require_explicit_branch=(source == "web_pos"),
        )
    else:
        new_branch_id = resolve_checkout_branch(
            employee, branch_id, allow_admin_any_branch=True, require_explicit_branch=(source == "web_pos")
        )

    if not activate_pos_request_branch(new_branch_id):
        raise PosCheckoutError("فرع خصم المخزون غير موجود أو غير نشط", 400, code="BRANCH_INVALID")

    if not customer_id:
        raise PosCheckoutError("يجب اختيار زبون", 400, code="CUSTOMER_REQUIRED")

    customer_query = Customer.query
    if employee.role == "admin" and new_branch_id:
        customer_query = customer_query.execution_options(skip_branch_scope=True)
    customer = customer_query.filter(Customer.id == customer_id).first()
    if not customer:
        raise PosCheckoutError("الزبون غير موجود", 400, code="CUSTOMER_NOT_FOUND")
    if getattr(customer, "is_blacklisted", False):
        raise PosCheckoutError(
            "هذا الزبون في القائمة السوداء — لا يُسمح بإنشاء طلب له.",
            400,
            code="BLACKLISTED",
            payload={"blacklisted": True},
        )
    customer_name = customer.name
    if not items:
        raise PosCheckoutError("لا توجد منتجات", 400, code="VALIDATION_ERROR")

    note_text = (note or "").strip() if note else None
    scheduled = _parse_scheduled_date(scheduled_date)
    resolved_page_id = page_id
    page_name = None
    if resolved_page_id:
        page = Page.query.get(resolved_page_id)
        if page:
            page_name = page.name
            if source != "employee_desk" and page not in employee.pages.all():
                resolved_page_id = None
                page_name = None

    if not shared_catalog and new_branch_id and int(customer.branch_id or 0) != int(new_branch_id):
        raise PosCheckoutError("الزبون لا يتبع الفرع المختار", 400, code="CUSTOMER_BRANCH_MISMATCH")

    submission_started = False
    submission_key = ""
    if not editing_order_id:
        submission_state, submission_payload, submission_key = _begin_pos_submission(
            submission_token or "", employee
        )
        if submission_state == "done":
            payload = dict(submission_payload)
            payload["duplicate"] = True
            return payload
        if submission_state == "busy":
            raise PosCheckoutError(
                "الطلب قيد الإنشاء حالياً، انتظر لحظة ولا تضغط تأكيد مرة ثانية.",
                409,
                code="IN_PROGRESS",
                payload={"in_progress": True},
            )
        submission_started = bool(submission_key)

    def _abort_submission():
        if submission_started:
            _finish_pos_submission(submission_key)

    invoice = editing_invoice
    was_stock_deducted = False
    previous_effective_paid = 0
    previous_payment_status = None
    previous_treasury_account_id = None
    preserved_shipping_fee = 0
    if editing_order_id:
        if paid_invoice_mutation_denied(invoice):
            raise PosCheckoutError(
                PAID_INVOICE_MUTATION_DISABLED_MESSAGE,
                403,
                code="FEATURE_DISABLED",
                payload={"feature_disabled": True},
            )
        if (invoice.status or "") in ("ملغي", "راجع", "مرتجع", "راجعة"):
            raise PosCheckoutError("لا يمكن تعديل طلب ملغي أو راجع", 400, code="NOT_EDITABLE")

        previous_effective_paid = int(_effective_paid_amount(invoice) or 0)
        previous_payment_status = (invoice.payment_status or "").strip()
        preserved_shipping_fee = get_shipping_fee_from_invoice(invoice)
        if previous_effective_paid > 0:
            from models.invoice_payment_ledger import InvoicePaymentLedger

            last_collection = (
                InvoicePaymentLedger.query.filter(
                    InvoicePaymentLedger.invoice_id == invoice.id,
                    InvoicePaymentLedger.amount_delta > 0,
                )
                .order_by(InvoicePaymentLedger.id.desc())
                .first()
            )
            if last_collection:
                previous_treasury_account_id = last_collection.treasury_account_id

        was_stock_deducted = stock_is_deducted(invoice)
        if was_stock_deducted:
            restore_order_stock(invoice)
        old_items = OrderItem.query.filter_by(invoice_id=invoice.id).all()
        from models.trade_in_receipt import TradeInReceipt
        from utils.trade_in_service import reverse_trade_in_receipt

        old_item_ids = [item.id for item in old_items if item.id]
        if old_item_ids:
            try:
                receipts = TradeInReceipt.query.filter(
                    TradeInReceipt.order_item_id.in_(old_item_ids)
                ).all()
                for receipt in receipts:
                    if receipt.status == "received":
                        reverse_trade_in_receipt(receipt)
                    db.session.delete(receipt)
            except TradeInError as exc:
                db.session.rollback()
                raise PosCheckoutError(str(exc), 400, code="TRADE_IN") from exc
        from modules.inventory_locations.models import InventoryOrderItemLocation
        from sqlalchemy import inspect
        if old_item_ids and inspect(db.session.connection()).has_table(InventoryOrderItemLocation.__tablename__):
            db.session.query(InventoryOrderItemLocation).filter(
                InventoryOrderItemLocation.order_item_id.in_(old_item_ids)).delete(synchronize_session=False)
        for old_item in old_items:
            db.session.delete(old_item)
        db.session.flush()

        if int(customer_id) != int(invoice.customer_id):
            db.session.rollback()
            raise PosCheckoutError("لا يمكن تغيير الزبون عند تعديل الطلب", 400, code="CUSTOMER_LOCKED")

        customer = invoice.customer or Customer.query.get(invoice.customer_id)
        if customer_updates:
            customer_name_update = str(customer_updates.get("name") or "").strip()
            customer_phone_update = str(customer_updates.get("phone") or "").strip()
            if not customer_name_update:
                db.session.rollback()
                raise PosCheckoutError("اسم الزبون مطلوب", 400, code="CUSTOMER_NAME_REQUIRED")
            if not customer_phone_update:
                db.session.rollback()
                raise PosCheckoutError("رقم هاتف الزبون مطلوب", 400, code="CUSTOMER_PHONE_REQUIRED")
            customer.name = customer_name_update[:150]
            customer.phone = customer_phone_update[:20]
            customer.phone2 = str(customer_updates.get("phone2") or "").strip()[:20] or None
            customer.city = str(customer_updates.get("city") or "").strip()[:100] or None
            customer.address = str(customer_updates.get("address") or "").strip()[:255] or None
            invoice.customer_name = customer.name
        invoice.total = 0
        invoice.note = note_text
        invoice.scheduled_date = scheduled
    else:
        invoice = Invoice(
            customer_id=customer_id,
            customer_name=customer_name,
            employee_id=employee.id,
            employee_name=employee.name,
            branch_id=new_branch_id,
            total=0,
            status="تم الطلب",
            payment_status="غير مسدد",
            note=note_text,
            scheduled_date=scheduled,
            page_id=resolved_page_id,
            page_name=page_name,
            created_at=datetime.utcnow(),
            stock_is_deducted=False,
        )

    from utils.geo_links import apply_invoice_location

    location_error = apply_invoice_location(invoice, raw_data)
    if location_error:
        db.session.rollback()
        raise PosCheckoutError(location_error, 400, code="LOCATION_INVALID")

    db.session.add(invoice)
    db.session.flush()

    try:
        resolved = resolve_checkout_lines(
            employee,
            items,
            invoice_branch_id=invoice.branch_id,
            customer=customer,
            source=source,
            shared_catalog=shared_catalog,
        )
    except PosCheckoutError:
        db.session.rollback()
        _abort_submission()
        raise

    total = 0
    pending_items = []
    stock_rows = []
    preferred_branch_id = invoice.branch_id or fallback_fulfillment_branch_id(invoice)

    for row in resolved:
        product = row["product"]
        qty = row["qty"]
        item_price = row["price"]
        item_total = row["line_total"]
        order_item = OrderItem(
            invoice_id=invoice.id,
            product_id=product.id,
            product_name=product.name,
            quantity=qty,
            price=item_price,
            cost=product.buy_price,
            total=item_total,
            fulfillment_branch_id=row["fulfillment_branch_id"],
            variant_color=row["variant_color"],
            sale_mode=row["sale_mode"],
            trade_in_source_product_id=None,
            trade_in_source_product_name=None,
        )
        total += item_total
        pending_items.append(order_item)
        stock_rows.append(
            {
                "product": product,
                "product_id": product.id,
                "quantity": qty,
                "variant_color": row["variant_color"],
                "fulfillment_branch_id": row["fulfillment_branch_id"],
                "storage_location_id":row['storage_source']['location_id'],
                "storage_automatic":row['storage_source']['automatic'],
                "storage_source_selected":row['storage_source']['provided'],
            }
        )
        db.session.add(order_item)
        db.session.flush()
        if row['storage_source']['provided']:
            from modules.inventory_locations.lots import choose_order_item_location
            try:
                choose_order_item_location(order_item,int(row['fulfillment_branch_id']),row['storage_source']['location_id'],
                    automatic=row['storage_source']['automatic'])
            except InventoryLotError as exc:
                db.session.rollback();_abort_submission()
                raise PosCheckoutError(str(exc),400,code='STORAGE_SOURCE_INVALID') from exc
        stock_rows[-1]['order_item_id']=order_item.id

    target_needs_stock = order_needs_stock(
        status=invoice.status,
        payment_status=invoice.payment_status,
    )
    existing_deferred_order = bool(
        editing_order_id and not was_stock_deducted and not target_needs_stock
    )
    should_deduct_now = target_needs_stock or (
        not deferred_stock_enabled() and not existing_deferred_order
    )
    stock_check = (
        check_stock_rows(stock_rows, preferred_branch_id=preferred_branch_id)
        if should_deduct_now and not editing_order_id
        else None
    )
    if not should_deduct_now:
        invoice.stock_is_deducted = False
        clear_order_stock_lock(invoice)
    elif editing_order_id:
        try:
            db.session.flush()
            deduct_order_stock(invoice)
        except OrderStockError as exc:
            db.session.rollback()
            raise PosCheckoutError(
                exc.message,
                409,
                code="INSUFFICIENT_STOCK",
                payload={"shortages": exc.shortages},
            ) from exc
    elif stock_check.can_fulfill:
        try:
            for order_item, action in zip(pending_items, stock_check.actions):
                order_item.fulfillment_branch_id = action.fulfillment_branch_id
                action.order_item_id=order_item.id
            apply_stock_actions(stock_check.actions, invoice=invoice)
            invoice.stock_is_deducted = True
            invoice.stock_deducted_at = datetime.utcnow()
            invoice.stock_restored_at = None
            clear_order_stock_lock(invoice)
        except (BranchStockError, ProductColorError, InventoryLotError) as exc:
            db.session.rollback()
            _abort_submission()
            raise PosCheckoutError(str(exc), 400, code="STOCK_ERROR") from exc
    else:
        mark_order_stock_locked(invoice, stock_check.reason_text)

    data = raw_data or {}
    if discount_amount is not None and "discount_amount" not in data and "discount_value" not in data and "discount" not in data:
        data = {**data, "discount_amount": discount_amount}
    parsed_discount = _parse_discount(data, total)
    invoice.discount_amount = parsed_discount
    invoice.total = max(0, total - parsed_discount)
    if preserved_shipping_fee > 0:
        apply_manual_delivery_fee_on_payment(
            invoice,
            preserved_shipping_fee,
            getattr(invoice, "tenant_id", None),
        )

    if editing_order_id and previous_payment_status:
        if previous_payment_status == "مسدد":
            invoice.payment_status = "مسدد"
            invoice.paid_amount = invoice.total
        elif previous_payment_status in {"جزئي", "مسدد جزئي"}:
            invoice.paid_amount = min(previous_effective_paid, invoice.total)
            if invoice.total > 0 and invoice.paid_amount >= invoice.total:
                invoice.payment_status = "مسدد"
            else:
                invoice.payment_status = "جزئي"

    db.session.flush()
    sync_trade_in_receipts(invoice)

    if editing_order_id and previous_effective_paid > 0:
        new_effective_paid = int(_effective_paid_amount(invoice) or 0)
        append_payment_ledger_delta(
            invoice.id,
            new_effective_paid - previous_effective_paid,
            treasury_account_id=(
                previous_treasury_account_id
                if new_effective_paid > previous_effective_paid
                else None
            ),
        )
        if invoice.shipping_company_id and invoice.payment_status == "مسدد":
            from utils.shipping_settlement_service import resize_paid_shipping_order_settlement

            resize_paid_shipping_order_settlement(invoice)
        from utils.delivery_expense_service import sync_delivery_expense_for_invoice
        from utils.payroll_service import sync_commission_line_for_invoice

        sync_delivery_expense_for_invoice(invoice)
        sync_commission_line_for_invoice(invoice)

    installment_meta = None
    if not editing_order_id:
        try:
            from modules.order_installment_lifecycle import service as oil_svc

            if oil_svc.is_installment_mode_on():
                lifecycle = oil_svc.start_lifecycle(invoice, employee)
                if lifecycle:
                    installment_meta = lifecycle.to_dict()
        except Exception as oil_exc:
            from modules.order_installment_lifecycle.service import OrderInstallmentError

            if isinstance(oil_exc, OrderInstallmentError):
                db.session.rollback()
                _abort_submission()
                raise PosCheckoutError(oil_exc.message, oil_exc.status_code, code=oil_exc.code) from oil_exc
            raise

    try:
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        try:
            if not commit:
                # The transaction owner records its audit after its own commit.
                return {
                    "success": True, "invoice_id": invoice.id, "order_id": invoice.id,
                    "total": invoice.total, "updated": False,
                    "stock_locked": bool(getattr(invoice, "is_stock_locked", False)),
                    "stock_lock_reason": getattr(invoice, "stock_lock_reason", None),
                }
            log_activity(
                "update" if editing_order_id else "create",
                "pos" if source == "web_pos" else "pos_api",
                f"{'تعديل طلب' if editing_order_id else 'بيع جديد'} — فاتورة #{invoice.id} بمبلغ {invoice.total}",
                entity_type="invoice",
                entity_id=invoice.id,
                payload={
                    "invoice": snapshot_attrs(invoice, *INVOICE_SNAPSHOT_FIELDS),
                    "items_count": len(items),
                    "source": source,
                    **(
                        {"edited_by_id": employee.id, "edited_by_name": employee.name}
                        if editing_order_id
                        else {}
                    ),
                    **({"installment_lifecycle": installment_meta} if installment_meta else {}),
                },
            )
        except Exception:
            pass
        response_payload = {
            "success": True,
            "invoice_id": invoice.id,
            "order_id": invoice.id,
            "total": invoice.total,
            "updated": bool(editing_order_id),
            "stock_locked": bool(getattr(invoice, "is_stock_locked", False)),
            "stock_lock_reason": getattr(invoice, "stock_lock_reason", None),
        }
        if installment_meta:
            response_payload["installment_lifecycle"] = installment_meta
        if submission_started:
            _finish_pos_submission(submission_key, response_payload, success=True)
        return response_payload
    except PosCheckoutError:
        raise
    except Exception as exc:
        db.session.rollback()
        _abort_submission()
        raise PosCheckoutError(str(exc), 500, code="SERVER_ERROR") from exc
