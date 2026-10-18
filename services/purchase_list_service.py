"""Daily Purchase List domain operations and atomic execution."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import threading
import uuid

from flask import session
from sqlalchemy import or_, update

from extensions import db
from models.employee import Employee
from models.product import Product
from models.purchase import Purchase
from models.purchase_list import PurchaseList, PurchaseListItem
from models.supplier import Supplier
from models.treasury_account import TreasuryAccount
from modules.wholesale.models.warehouse import Warehouse
from utils.activity_logger import log_activity
from utils.branch_scope import allowed_branch_ids


PAYMENT_METHODS = {"cash", "card", "bank_transfer", "credit"}
PAYMENT_METHOD_LABELS = {
    "cash": "نقدي",
    "card": "بطاقة",
    "bank_transfer": "تحويل بنكي",
    "credit": "آجل",
}
PURCHASE_REASONS = {
    "low_stock", "customer_request", "branch_request", "employee_request",
    "scheduled_purchase", "special_request", "other",
}
EDITABLE_STATUSES = {"draft", "open", "partially_executed"}
_EXECUTION_LOCK = threading.RLock()


class PurchaseListError(Exception):
    def __init__(self, message: str, *, code: str = "invalid_purchase_list", errors: list[dict] | None = None):
        self.code = code
        self.errors = errors or []
        super().__init__(message)


def current_tenant_id() -> int | None:
    raw = session.get("tenant_id")
    if raw not in (None, ""):
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    employee_id = session.get("user_id")
    employee = db.session.get(Employee, employee_id) if employee_id else None
    return int(employee.tenant_id) if employee and employee.tenant_id is not None else None


def _tenant_matches(entity, tenant_id: int | None) -> bool:
    entity_tenant = getattr(entity, "tenant_id", None)
    # Tenant databases are physically isolated. NULL is retained for legacy
    # rows created before tenant_id was projected into every table.
    return entity_tenant is None or tenant_id is None or int(entity_tenant) == int(tenant_id)


def scoped_lists_query(tenant_id: int | None = None):
    tenant_id = current_tenant_id() if tenant_id is None else tenant_id
    query = PurchaseList.query
    if tenant_id is not None:
        query = query.filter(or_(PurchaseList.tenant_id == tenant_id, PurchaseList.tenant_id.is_(None)))
    branches = allowed_branch_ids()
    if branches:
        query = query.filter(PurchaseList.branch_id.in_(branches))
    return query


def get_list_or_error(list_id: int, tenant_id: int | None = None) -> PurchaseList:
    row = scoped_lists_query(tenant_id).filter(PurchaseList.id == int(list_id)).first()
    if not row:
        raise PurchaseListError("قائمة الشراء غير موجودة.", code="not_found")
    return row


def next_list_number(tenant_id: int | None, list_date: date) -> str:
    prefix = f"PL-{list_date.strftime('%Y%m%d')}-"
    rows = (
        PurchaseList.query.filter(PurchaseList.list_number.like(f"{prefix}%"))
        .with_entities(PurchaseList.list_number)
        .all()
    )
    highest = 0
    for (value,) in rows:
        try:
            highest = max(highest, int(str(value).rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            continue
    return f"{prefix}{highest + 1:03d}"


def create_list(*, branch_id: int, warehouse_id: int, responsible_employee_id: int | None,
                list_date: date, notes: str | None, employee_id: int | None) -> PurchaseList:
    tenant_id = current_tenant_id()
    if branch_id not in allowed_branch_ids():
        raise PurchaseListError("لا يمكنك إنشاء قائمة شراء لهذا الفرع.", code="branch_forbidden")
    warehouse = db.session.get(Warehouse, warehouse_id)
    if not warehouse or not warehouse.is_active or warehouse.deleted_at or not _tenant_matches(warehouse, tenant_id):
        raise PurchaseListError("المخزن المحدد غير موجود أو غير متاح.", code="invalid_warehouse")
    if warehouse.branch_id and int(warehouse.branch_id) != int(branch_id):
        raise PurchaseListError("المخزن المحدد لا يتبع الفرع المختار.", code="warehouse_branch_mismatch")
    if responsible_employee_id:
        responsible = db.session.get(Employee, responsible_employee_id)
        if not responsible or not _tenant_matches(responsible, tenant_id):
            raise PurchaseListError("الموظف المسؤول غير موجود.", code="invalid_employee")
    row = PurchaseList(
        tenant_id=tenant_id,
        branch_id=branch_id,
        warehouse_id=warehouse_id,
        list_number=next_list_number(tenant_id, list_date),
        list_date=list_date,
        responsible_employee_id=responsible_employee_id or employee_id,
        status="open",
        notes=(notes or "").strip() or None,
        created_by=employee_id,
    )
    db.session.add(row)
    db.session.flush()
    log_activity(
        "create", "purchases", f"إنشاء قائمة شراء {row.list_number}",
        entity_type="purchase_list", entity_id=row.id,
        payload={"branch_id": branch_id, "warehouse_id": warehouse_id}, commit=False,
    )
    return row


def _parse_nonnegative(value, field: str) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        raise PurchaseListError(f"قيمة {field} غير صالحة.")
    if parsed < 0:
        raise PurchaseListError(f"قيمة {field} لا يمكن أن تكون سالبة.")
    return parsed


def apply_item_data(item: PurchaseListItem, payload: dict, purchase_list: PurchaseList, *, creating=False) -> None:
    if not purchase_list.is_editable:
        raise PurchaseListError("لا يمكن تعديل قائمة شراء منفذة.", code="read_only")
    tenant_id = current_tenant_id()
    product_id = int(payload.get("product_id") or item.product_id or 0)
    supplier_id = int(payload.get("supplier_id") or item.supplier_id or 0)
    product = Product.query.execution_options(skip_branch_scope=True).filter_by(id=product_id, active=True).first()
    supplier = Supplier.query.execution_options(skip_branch_scope=True).filter_by(id=supplier_id).first()
    if not product or not _tenant_matches(product, tenant_id):
        raise PurchaseListError("المنتج غير موجود أو لا يتبع الشركة الحالية.", code="invalid_product")
    if not supplier or not _tenant_matches(supplier, tenant_id):
        raise PurchaseListError("المورد غير موجود أو لا يتبع الشركة الحالية.", code="invalid_supplier")
    if product.branch_id and int(product.branch_id) != int(purchase_list.branch_id):
        raise PurchaseListError(f"المنتج «{product.name}» لا يتبع فرع القائمة.", code="product_branch_mismatch")
    if supplier.branch_id and int(supplier.branch_id) != int(purchase_list.branch_id):
        raise PurchaseListError(f"المورد «{supplier.name}» لا يتبع فرع القائمة.", code="supplier_branch_mismatch")
    try:
        quantity = int(payload.get("quantity", item.quantity or 0))
    except (TypeError, ValueError):
        quantity = 0
    if quantity <= 0:
        raise PurchaseListError(f"كمية «{product.name}» يجب أن تكون أكبر من صفر.", code="invalid_quantity")
    price = _parse_nonnegative(payload.get("purchase_price", item.purchase_price), "سعر الشراء")
    discount = _parse_nonnegative(payload.get("discount", item.discount), "الخصم")
    tax = _parse_nonnegative(payload.get("tax", item.tax), "الضريبة")
    if discount > price + tax:
        raise PurchaseListError(f"خصم «{product.name}» يتجاوز سعره.", code="invalid_discount")
    method = str(payload.get("payment_method") or item.payment_method or "credit").strip().lower()
    if method not in PAYMENT_METHODS:
        raise PurchaseListError(f"طريقة الدفع للمنتج «{product.name}» غير صالحة.", code="invalid_payment_method")
    raw_account = payload.get("payment_account_id", item.payment_account_id)
    account_id = int(raw_account) if raw_account not in (None, "", 0, "0") else None
    if method != "credit":
        account = TreasuryAccount.query.execution_options(skip_branch_scope=True).filter_by(id=account_id, is_active=True).first()
        if not account or not _tenant_matches(account, tenant_id):
            raise PurchaseListError(f"حساب الدفع للمنتج «{product.name}» مفقود أو غير صالح.", code="invalid_payment_account")
        if account.branch_id and int(account.branch_id) != int(purchase_list.branch_id):
            raise PurchaseListError(f"حساب الدفع للمنتج «{product.name}» لا يتبع فرع القائمة.", code="payment_account_branch_mismatch")
        if method == "cash" and not account.is_cash:
            raise PurchaseListError(f"يجب اختيار صندوق نقدي للمنتج «{product.name}».", code="invalid_cash_account")
        if method in {"card", "bank_transfer"} and account.is_cash:
            raise PurchaseListError(f"يجب اختيار حساب بطاقة/بنك للمنتج «{product.name}».", code="invalid_bank_account")
    else:
        account_id = None
    reason = str(payload.get("purchase_reason") or item.purchase_reason or "").strip() or None
    if reason and reason not in PURCHASE_REASONS:
        raise PurchaseListError("سبب الشراء المحدد غير صالح.", code="invalid_reason")

    item.tenant_id = tenant_id
    item.product_id = product.id
    item.supplier_id = supplier.id
    item.quantity = quantity
    item.unit_id = int(payload["unit_id"]) if payload.get("unit_id") not in (None, "") else None
    item.unit_name = str(payload.get("unit_name") or item.unit_name or "قطعة").strip()[:50]
    item.purchase_price = price
    item.discount = discount
    item.tax = tax
    item.payment_method = method
    item.payment_account_id = account_id
    item.purchase_reason = reason
    item.notes = str(payload.get("notes") or "").strip() or None
    item.is_selected = bool(payload.get("is_selected", item.is_selected if not creating else True))
    item.status = "selected" if item.is_selected else "draft"
    item.updated_at = datetime.utcnow()


def add_item(purchase_list: PurchaseList, payload: dict, employee_id: int | None) -> PurchaseListItem:
    item = PurchaseListItem(purchase_list_id=purchase_list.id, created_by=employee_id)
    apply_item_data(item, payload, purchase_list, creating=True)
    db.session.add(item)
    db.session.flush()
    log_activity(
        "create", "purchases", f"إضافة {item.product.name} إلى {purchase_list.list_number}",
        entity_type="purchase_list_item", entity_id=item.id,
        payload={"purchase_list_id": purchase_list.id, "product_id": item.product_id}, commit=False,
    )
    return item


def _execution_summary(purchase_list: PurchaseList, invoices: list[Purchase] | None = None) -> dict:
    executed = [item for item in purchase_list.items if item.status == "executed"]
    invoice_ids = sorted({item.purchase_invoice_id for item in executed if item.purchase_invoice_id})
    if invoices is None and invoice_ids:
        invoices = Purchase.query.filter(Purchase.id.in_(invoice_ids)).all()
    totals = defaultdict(int)
    for item in executed:
        totals[item.payment_method] += item.total
    return {
        "list_id": purchase_list.id,
        "list_number": purchase_list.list_number,
        "list_status": purchase_list.status,
        "executed_item_count": len(executed),
        "supplier_count": len({item.supplier_id for item in executed}),
        "purchase_invoice_count": len(invoice_ids),
        "invoice_ids": invoice_ids,
        "total": sum(item.total for item in executed),
        "cash": totals["cash"],
        "card": totals["card"],
        "bank_transfer": totals["bank_transfer"],
        "credit": totals["credit"],
    }


def _validate_execution(purchase_list: PurchaseList, selected: list[PurchaseListItem]) -> None:
    errors: list[dict] = []
    tenant_id = current_tenant_id()
    warehouse = db.session.get(Warehouse, purchase_list.warehouse_id) if purchase_list.warehouse_id else None
    if not warehouse or not _tenant_matches(warehouse, tenant_id):
        errors.append({"field": "warehouse_id", "message": "المخزن المحدد غير موجود أو لا يتبع الشركة الحالية."})
    elif warehouse.branch_id and int(warehouse.branch_id) != int(purchase_list.branch_id):
        errors.append({"field": "warehouse_id", "message": "المخزن لا يتبع فرع قائمة الشراء."})
    if int(purchase_list.branch_id) not in allowed_branch_ids():
        errors.append({"field": "branch_id", "message": "لا تملك صلاحية التنفيذ في فرع هذه القائمة."})
    for item in selected:
        name = item.product.name if item.product else f"عنصر #{item.id}"
        if item.status == "executed" or item.purchase_invoice_id:
            errors.append({"item_id": item.id, "message": f"تم تنفيذ «{name}» مسبقاً."})
            continue
        try:
            apply_item_data(item, {
                "product_id": item.product_id,
                "supplier_id": item.supplier_id,
                "quantity": item.quantity,
                "purchase_price": item.purchase_price,
                "discount": item.discount,
                "tax": item.tax,
                "payment_method": item.payment_method,
                "payment_account_id": item.payment_account_id,
                "purchase_reason": item.purchase_reason,
                "unit_id": item.unit_id,
                "unit_name": item.unit_name,
                "notes": item.notes,
                "is_selected": True,
            }, purchase_list)
        except PurchaseListError as exc:
            errors.append({"item_id": item.id, "message": str(exc)})
    if errors:
        raise PurchaseListError("تعذر تنفيذ بعض عناصر قائمة الشراء.", code="validation_failed", errors=errors)


def execute_list(list_id: int, *, employee_id: int | None, discard_unselected: bool = True,
                 idempotency_key: str | None = None) -> dict:
    key = (idempotency_key or str(uuid.uuid4())).strip()[:100]
    # All additive compatibility work must finish before the financial
    # transaction starts; schema guards may use their own transaction.
    from utils.inventory_lots import ensure_inventory_lot_schema
    from utils.branch_migration import ensure_branch_schema
    from utils.purchase_schema_guard import ensure_purchase_schema
    from utils.stock_movement_guard import ensure_stock_movement_schema
    from utils.treasury_schema_guard import ensure_treasury_schema

    ensure_branch_schema()
    ensure_purchase_schema()
    ensure_inventory_lot_schema()
    ensure_stock_movement_schema()
    ensure_treasury_schema()
    with _EXECUTION_LOCK:
        # Execution owns its transaction boundary. Closing the read transaction
        # before taking the write lock is important for SQLite tenant files.
        db.session.rollback()
        try:
            with db.session.begin():
                query = scoped_lists_query().filter(PurchaseList.id == int(list_id)).with_for_update()
                purchase_list = query.first()
                if not purchase_list:
                    raise PurchaseListError("قائمة الشراء غير موجودة.", code="not_found")
                if purchase_list.execution_key == key and purchase_list.status in {"executed", "partially_executed"}:
                    return _execution_summary(purchase_list)
                if purchase_list.status == "executed":
                    raise PurchaseListError("تم تنفيذ قائمة الشراء هذه مسبقاً.", code="already_executed")
                if purchase_list.status not in EDITABLE_STATUSES:
                    raise PurchaseListError("قائمة الشراء غير قابلة للتنفيذ حالياً.", code="not_executable")

                selected = [
                    item for item in purchase_list.items
                    if item.is_selected and item.status not in {"executed", "discarded", "cancelled"}
                ]
                if not selected:
                    raise PurchaseListError("حدد عنصراً واحداً على الأقل للتنفيذ.", code="nothing_selected")
                _validate_execution(purchase_list, selected)

                # Claim the list with a status-guarded write.  ``FOR UPDATE``
                # protects databases that support row locks; this compare-and-
                # set also prevents a second worker from reviving an already
                # executed row on SQLite, where FOR UPDATE is a no-op.
                claim_time = datetime.utcnow()
                claim = db.session.execute(
                    update(PurchaseList)
                    .where(
                        PurchaseList.id == purchase_list.id,
                        PurchaseList.status.in_(EDITABLE_STATUSES),
                    )
                    .values(status="executing", execution_key=key, updated_at=claim_time)
                    .execution_options(synchronize_session="fetch")
                )
                if claim.rowcount != 1:
                    raise PurchaseListError(
                        "تم تغيير قائمة الشراء بواسطة مستخدم آخر. أعد التحميل وحاول مجدداً.",
                        code="concurrent_change",
                    )
                db.session.flush()

                grouped: dict[int, list[PurchaseListItem]] = defaultdict(list)
                for item in selected:
                    grouped[item.supplier_id].append(item)

                invoices: list[Purchase] = []
                from routes.purchases import _create_purchase_from_payload

                tenant_id = current_tenant_id()
                now = datetime.utcnow()
                for supplier_id, items in grouped.items():
                    payments: dict[tuple[str, int], int] = defaultdict(int)
                    methods = set()
                    purchase_items = []
                    for item in items:
                        methods.add(item.payment_method)
                        purchase_items.append({
                            "product_id": item.product_id,
                            # Existing purchase service models discount per unit.
                            # Tax is folded into acquisition cost, matching Finora's
                            # current inventory-cost representation.
                            "quantity": item.quantity,
                            "unit_cost_before_discount": item.purchase_price + item.tax,
                            "discount_value": item.discount,
                        })
                        if item.payment_method != "credit":
                            payments[(item.payment_method, int(item.payment_account_id))] += item.total
                    payment_rows = [
                        {
                            "payment_method": method,
                            "treasury_account_id": account_id,
                            "amount": amount,
                            "_schema_ready": True,
                            "note": f"دفعة مجمعة من {purchase_list.list_number}",
                        }
                        for (method, account_id), amount in payments.items()
                    ]
                    purchase_mode = "credit" if methods == {"credit"} else (next(iter(methods)) if len(methods) == 1 else "mixed")
                    purchase, error = _create_purchase_from_payload({
                        "supplier_id": supplier_id,
                        "branch_id": purchase_list.branch_id,
                        "_validated_branch_id": purchase_list.branch_id,
                        "warehouse_id": purchase_list.warehouse_id,
                        "tenant_id": tenant_id,
                        "purchase_list_id": purchase_list.id,
                        "purchase_list_number": purchase_list.list_number,
                        "source_module": "purchase_list",
                        "purchase_date": purchase_list.list_date.isoformat(),
                        "status": "confirmed",
                        "purchase_mode": purchase_mode,
                        "notes": f"من قائمة الشراء {purchase_list.list_number}",
                        "items": purchase_items,
                        "payments": payment_rows,
                    }, [], commit=False, employee_id=employee_id)
                    if error or purchase is None:
                        raise PurchaseListError(error or "تعذر إنشاء فاتورة الشراء.", code="invoice_creation_failed")
                    from services.purchase_list_accounting import post_split_purchase_journals

                    post_split_purchase_journals(purchase, employee_id=employee_id)
                    invoices.append(purchase)
                    for item in items:
                        item.status = "executed"
                        item.is_selected = True
                        item.purchase_invoice_id = purchase.id
                        item.executed_at = now

                remaining = []
                for item in purchase_list.items:
                    if item.status == "executed":
                        continue
                    if discard_unselected:
                        item.status = "discarded"
                        item.is_selected = False
                        item.updated_at = now
                    elif item.status not in {"cancelled", "discarded"}:
                        item.status = "draft"
                        remaining.append(item)

                purchase_list.status = "partially_executed" if remaining else "executed"
                purchase_list.executed_by = employee_id
                purchase_list.executed_at = now
                purchase_list.updated_at = now
                db.session.flush()
                summary = _execution_summary(purchase_list, invoices)
                log_activity(
                    "execute", "purchases", f"تنفيذ قائمة الشراء {purchase_list.list_number}",
                    entity_type="purchase_list", entity_id=purchase_list.id,
                    payload={**summary, "discard_unselected": bool(discard_unselected)}, commit=False,
                )
            return summary
        except Exception:
            db.session.rollback()
            raise
