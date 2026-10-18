"""HTTP/UI layer for Daily Purchase Lists."""
from __future__ import annotations

from datetime import date, datetime
import json

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import or_

from extensions import db
from models.branch import Branch
from models.employee import Employee
from models.product import Product
from models.purchase import Purchase
from models.purchase_item import PurchaseItem
from models.purchase_list import PurchaseList, PurchaseListItem
from models.supplier import Supplier
from models.treasury_account import TreasuryAccount
from modules.wholesale.models.warehouse import Warehouse
from modules.wholesale.services.warehouse_service import ensure_default_warehouses, list_warehouses
from services.purchase_list_service import (
    PAYMENT_METHOD_LABELS,
    PurchaseListError,
    add_item,
    apply_item_data,
    create_list,
    current_tenant_id,
    execute_list,
    get_list_or_error,
    scoped_lists_query,
    _tenant_matches,
)
from utils.activity_logger import log_activity
from utils.branch_scope import allowed_branch_ids
from utils.permission_checks import check_permission
from utils.purchase_list_schema import ensure_purchase_list_schema


purchase_lists_bp = Blueprint("purchase_lists", __name__, url_prefix="/purchases/lists")

REASON_LABELS = {
    "low_stock": "نقص بالمخزون",
    "customer_request": "طلب زبون",
    "branch_request": "طلب فرع",
    "employee_request": "طلب موظف",
    "scheduled_purchase": "شراء مجدول",
    "special_request": "طلب خاص",
    "other": "أخرى",
}


@purchase_lists_bp.before_request
def _prepare_schema():
    ensure_purchase_list_schema()


def _can(permission: str) -> bool:
    # ``manage_inventory`` preserves access for existing roles. New roles can
    # receive the narrower purchase_list.* permissions independently.
    return check_permission(permission) or check_permission("manage_inventory")


def _guard(permission: str):
    if _can(permission):
        return None
    if request.path.startswith("/purchases/lists/api/") or request.is_json:
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    return redirect("/pos/login")


def _json_error(exc: Exception, status=400):
    if isinstance(exc, PurchaseListError):
        if exc.code == "not_found":
            status = 404
        elif exc.code in {"validation_failed", "nothing_selected"}:
            status = 422
        elif exc.code in {"already_executed", "not_executable", "read_only", "concurrent_change"}:
            status = 409
        elif exc.code in {"payment_forbidden", "branch_forbidden"}:
            status = 403
        return jsonify({"success": False, "error": str(exc), "code": exc.code, "errors": exc.errors}), status
    return jsonify({"success": False, "error": "تعذر إكمال العملية. حاول مرة أخرى."}), status


def _secured_item_payload(payload: dict, item: PurchaseListItem | None = None) -> dict:
    clean = dict(payload or {})
    if not _can("purchase_list.manage_payment"):
        requested_method = str(clean.get("payment_method") or (item.payment_method if item else "credit")).strip().lower()
        requested_account = clean.get("payment_account_id")
        changed = item is not None and (
            requested_method != item.payment_method
            or str(requested_account or "") != str(item.payment_account_id or "")
        )
        if (item is None and (requested_method != "credit" or requested_account not in (None, "", 0, "0"))) or changed:
            raise PurchaseListError("لا تملك صلاحية إدارة طريقة أو حساب الدفع.", code="payment_forbidden")
        clean["payment_method"] = item.payment_method if item else "credit"
        clean["payment_account_id"] = item.payment_account_id if item else None
    if not _can("purchase_list.view_cost"):
        if item is None:
            product = db.session.get(Product, int(clean.get("product_id") or 0))
            clean["purchase_price"] = int(product.buy_price or 0) if product else 0
            clean["discount"] = 0
            clean["tax"] = 0
        else:
            clean["purchase_price"] = item.purchase_price
            clean["discount"] = item.discount
            clean["tax"] = item.tax
    return clean


def _item_dict(item: PurchaseListItem, *, can_view_cost=True) -> dict:
    return {
        "id": item.id,
        "product_id": item.product_id,
        "product_name": item.product.name if item.product else "—",
        "supplier_id": item.supplier_id,
        "supplier_name": item.supplier.name if item.supplier else "—",
        "quantity": int(item.quantity or 0),
        "unit_id": item.unit_id,
        "unit_name": item.unit_name or "قطعة",
        "purchase_price": int(item.purchase_price or 0) if can_view_cost else None,
        "discount": int(item.discount or 0) if can_view_cost else None,
        "tax": int(item.tax or 0) if can_view_cost else None,
        "payment_method": item.payment_method,
        "payment_method_label": PAYMENT_METHOD_LABELS.get(item.payment_method, item.payment_method),
        "payment_account_id": item.payment_account_id,
        "payment_account_name": item.payment_account.name if item.payment_account else "",
        "purchase_reason": item.purchase_reason,
        "purchase_reason_label": REASON_LABELS.get(item.purchase_reason, ""),
        "notes": item.notes or "",
        "is_selected": bool(item.is_selected),
        "status": item.status,
        "purchase_invoice_id": item.purchase_invoice_id,
        "total": item.total if can_view_cost else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _list_dict(row: PurchaseList, *, include_items=False, can_view_cost=True) -> dict:
    items = list(row.items or [])
    active = [item for item in items if item.status not in {"discarded", "cancelled"}]
    selected = [item for item in active if item.is_selected]
    result = {
        "id": row.id,
        "list_number": row.list_number,
        "list_date": row.list_date.isoformat(),
        "branch_id": row.branch_id,
        "branch_name": row.branch.name if row.branch else "—",
        "warehouse_id": row.warehouse_id,
        "warehouse_name": row.warehouse.name if row.warehouse else "—",
        "responsible_employee_id": row.responsible_employee_id,
        "responsible_employee_name": row.responsible_employee.name if row.responsible_employee else "—",
        "status": row.status,
        "notes": row.notes or "",
        "is_editable": row.is_editable,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
        "executed_by_name": row.executor.name if row.executor else "—",
        "item_count": len(active),
        "selected_count": len(selected),
        "supplier_count": len({item.supplier_id for item in selected}),
        "total": sum(item.total for item in active) if can_view_cost else None,
        "selected_total": sum(item.total for item in selected) if can_view_cost else None,
    }
    if include_items:
        result["items"] = [_item_dict(item, can_view_cost=can_view_cost) for item in items]
    return result


def _page_context(row: PurchaseList | None = None) -> dict:
    tenant_id = current_tenant_id()
    branch_ids = allowed_branch_ids()
    requested_branch = request.args.get("branch_id", type=int)
    branches = Branch.query.filter(Branch.id.in_(branch_ids), Branch.is_active.is_(True)).order_by(Branch.name).all() if branch_ids else []
    warehouses = list_warehouses(tenant_id)
    if not warehouses and branches:
        warehouses = ensure_default_warehouses(tenant_id, branches[0].id)
        db.session.commit()
    if branch_ids:
        warehouses = [w for w in warehouses if not w.branch_id or int(w.branch_id) in branch_ids]
    suppliers = Supplier.query.execution_options(skip_branch_scope=True).order_by(Supplier.name).all()
    employees_query = Employee.query.filter_by(is_active=True)
    if tenant_id is not None:
        employees_query = employees_query.filter(or_(Employee.tenant_id == tenant_id, Employee.tenant_id.is_(None)))
    employees = employees_query.order_by(Employee.name).all()
    accounts = TreasuryAccount.query.execution_options(skip_branch_scope=True).filter_by(is_active=True).order_by(TreasuryAccount.account_type, TreasuryAccount.name).all()
    can_view_cost = _can("purchase_list.view_cost")
    return {
        "purchase_list": row,
        "purchase_list_json": _list_dict(row, include_items=True, can_view_cost=can_view_cost) if row else None,
        "branches": branches,
        "warehouses": warehouses,
        "suppliers": suppliers,
        # Products are loaded by the debounced, tenant-scoped picker endpoint.
        "products": [],
        "employees": employees,
        "accounts": accounts,
        "reason_labels": REASON_LABELS,
        "payment_labels": PAYMENT_METHOD_LABELS,
        "permissions": {
            "view": _can("purchase_list.view"),
            "create": _can("purchase_list.create"),
            "edit": _can("purchase_list.edit"),
            "execute": _can("purchase_list.execute"),
            "print": _can("purchase_list.print"),
            "view_cost": can_view_cost,
            "manage_payment": _can("purchase_list.manage_payment"),
        },
    }


@purchase_lists_bp.get("")
@purchase_lists_bp.get("/")
def index():
    denied = _guard("purchase_list.view")
    if denied:
        return denied
    status = (request.args.get("status") or "").strip()
    query = scoped_lists_query()
    if status:
        query = query.filter(PurchaseList.status == status)
    rows = query.order_by(PurchaseList.list_date.desc(), PurchaseList.id.desc()).limit(250).all()
    context = _page_context()
    context["rows"] = rows
    context["prefill_product_id"] = request.args.get("product_id", type=int)
    return render_template("purchase_lists/index.html", **context)


@purchase_lists_bp.get("/api/products/search")
def api_product_search():
    """Small, tenant-scoped product lookup used by the item picker."""
    denied = _guard("purchase_list.view")
    if denied:
        return denied
    tenant_id = current_tenant_id()
    branch_ids = allowed_branch_ids()
    requested_branch = request.args.get("branch_id", type=int)
    query_text = (request.args.get("q") or "").strip()
    product_id = request.args.get("id", type=int)
    limit = min(max(request.args.get("limit", 40, type=int) or 40, 1), 40)
    query = Product.query.execution_options(skip_branch_scope=True).filter(Product.active.is_(True))
    if tenant_id is not None:
        query = query.filter(or_(Product.tenant_id == tenant_id, Product.tenant_id.is_(None)))
    if branch_ids:
        query = query.filter(or_(Product.branch_id.in_(branch_ids), Product.branch_id.is_(None)))
    if requested_branch and requested_branch in branch_ids:
        query = query.filter(or_(Product.branch_id == requested_branch, Product.branch_id.is_(None)))
    if product_id:
        query = query.filter(Product.id == product_id)
    elif query_text:
        pattern = f"%{query_text}%"
        query = query.filter(or_(Product.name.ilike(pattern), Product.sku.ilike(pattern), Product.barcode.ilike(pattern)))
    rows = query.order_by(Product.name.asc(), Product.id.asc()).limit(limit * 3).all()
    # Do not show the same catalog identity twice in the picker. The duplicate
    # records remain available to the dedicated merge screen.
    unique = {}
    for product in rows:
        key = ("barcode", (product.barcode or "").strip().lower()) if product.barcode else ("sku", (product.sku or "").strip().lower()) if product.sku else ("name", " ".join((product.name or "").lower().split()))
        unique.setdefault(key, product)
    rows = list(unique.values())[:limit]
    return jsonify({"success": True, "products": [{
        "id": p.id, "name": p.name, "sku": p.sku or "", "barcode": p.barcode or "",
        "buy_price": p.buy_price or 0, "quantity": p.quantity or 0, "branch_id": p.branch_id,
    } for p in rows]})


@purchase_lists_bp.get("/<int:list_id>")
def detail(list_id):
    denied = _guard("purchase_list.view")
    if denied:
        return denied
    try:
        row = get_list_or_error(list_id)
    except PurchaseListError:
        return redirect(url_for("purchase_lists.index"))
    return render_template("purchase_lists/detail.html", **_page_context(row))


@purchase_lists_bp.post("/api")
def api_create():
    denied = _guard("purchase_list.create")
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    try:
        raw_date = payload.get("list_date")
        list_date = datetime.strptime(raw_date, "%Y-%m-%d").date() if raw_date else date.today()
        row = create_list(
            branch_id=int(payload.get("branch_id") or 0),
            warehouse_id=int(payload.get("warehouse_id") or 0),
            responsible_employee_id=int(payload["responsible_employee_id"]) if payload.get("responsible_employee_id") else None,
            list_date=list_date,
            notes=payload.get("notes"),
            employee_id=session.get("user_id"),
        )
        db.session.commit()
        return jsonify({"success": True, "purchase_list": _list_dict(row), "redirect_url": url_for("purchase_lists.detail", list_id=row.id)}), 201
    except Exception as exc:
        db.session.rollback()
        return _json_error(exc)


@purchase_lists_bp.patch("/api/<int:list_id>")
def api_update(list_id):
    denied = _guard("purchase_list.edit")
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    try:
        row = get_list_or_error(list_id)
        if not row.is_editable:
            raise PurchaseListError("لا يمكن تعديل قائمة شراء منفذة.", code="read_only")
        before = {"notes": row.notes, "warehouse_id": row.warehouse_id, "responsible_employee_id": row.responsible_employee_id}
        if "notes" in payload:
            row.notes = str(payload.get("notes") or "").strip() or None
        if payload.get("responsible_employee_id"):
            employee = db.session.get(Employee, int(payload["responsible_employee_id"]))
            if not employee or not _tenant_matches(employee, current_tenant_id()):
                raise PurchaseListError("الموظف المسؤول غير موجود.")
            row.responsible_employee_id = employee.id
        if payload.get("warehouse_id"):
            warehouse = db.session.get(Warehouse, int(payload["warehouse_id"]))
            if not warehouse or not _tenant_matches(warehouse, current_tenant_id()) or (warehouse.branch_id and int(warehouse.branch_id) != int(row.branch_id)):
                raise PurchaseListError("المخزن غير صالح لفرع القائمة.")
            row.warehouse_id = warehouse.id
        row.updated_at = datetime.utcnow()
        log_activity("update", "purchases", f"تعديل قائمة الشراء {row.list_number}", entity_type="purchase_list", entity_id=row.id,
                     payload={"before": before, "after": payload}, commit=False)
        db.session.commit()
        return jsonify({"success": True, "purchase_list": _list_dict(row, include_items=True, can_view_cost=_can("purchase_list.view_cost"))})
    except Exception as exc:
        db.session.rollback()
        return _json_error(exc)


@purchase_lists_bp.post("/api/<int:list_id>/items")
def api_add_item(list_id):
    denied = _guard("purchase_list.edit")
    if denied:
        return denied
    try:
        row = get_list_or_error(list_id)
        item = add_item(row, _secured_item_payload(request.get_json(silent=True) or {}), session.get("user_id"))
        db.session.commit()
        return jsonify({"success": True, "item": _item_dict(item, can_view_cost=_can("purchase_list.view_cost"))}), 201
    except Exception as exc:
        db.session.rollback()
        return _json_error(exc)


@purchase_lists_bp.patch("/api/<int:list_id>/items/<int:item_id>")
def api_update_item(list_id, item_id):
    denied = _guard("purchase_list.edit")
    if denied:
        return denied
    try:
        row = get_list_or_error(list_id)
        item = PurchaseListItem.query.filter_by(id=item_id, purchase_list_id=row.id).first()
        if not item:
            raise PurchaseListError("عنصر قائمة الشراء غير موجود.", code="not_found")
        before = _item_dict(item)
        apply_item_data(item, _secured_item_payload(request.get_json(silent=True) or {}, item), row)
        log_activity("update", "purchases", f"تعديل عنصر في {row.list_number}", entity_type="purchase_list_item", entity_id=item.id,
                     payload={"before": before, "after": _item_dict(item)}, commit=False)
        db.session.commit()
        return jsonify({"success": True, "item": _item_dict(item, can_view_cost=_can("purchase_list.view_cost"))})
    except Exception as exc:
        db.session.rollback()
        return _json_error(exc)


@purchase_lists_bp.delete("/api/<int:list_id>/items/<int:item_id>")
def api_discard_item(list_id, item_id):
    denied = _guard("purchase_list.delete")
    if denied:
        return denied
    try:
        row = get_list_or_error(list_id)
        if not row.is_editable:
            raise PurchaseListError("لا يمكن تعديل قائمة شراء منفذة.", code="read_only")
        item = PurchaseListItem.query.filter_by(id=item_id, purchase_list_id=row.id).first()
        if not item or item.status == "executed":
            raise PurchaseListError("لا يمكن استبعاد هذا العنصر.", code="read_only")
        item.status = "discarded"
        item.is_selected = False
        item.updated_at = datetime.utcnow()
        log_activity("discard", "purchases", f"استبعاد عنصر من {row.list_number}", entity_type="purchase_list_item", entity_id=item.id,
                     payload={"product_id": item.product_id}, commit=False)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as exc:
        db.session.rollback()
        return _json_error(exc)


@purchase_lists_bp.post("/api/<int:list_id>/selection")
def api_selection(list_id):
    denied = _guard("purchase_list.edit")
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    try:
        row = get_list_or_error(list_id)
        if not row.is_editable:
            raise PurchaseListError("لا يمكن تعديل قائمة شراء منفذة.", code="read_only")
        selected_ids = {int(value) for value in payload.get("selected_ids", [])}
        for item in row.items:
            if item.status in {"executed", "discarded", "cancelled"}:
                continue
            item.is_selected = item.id in selected_ids
            item.status = "selected" if item.is_selected else "draft"
            item.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"success": True})
    except Exception as exc:
        db.session.rollback()
        return _json_error(exc)


@purchase_lists_bp.post("/api/<int:list_id>/execute")
def api_execute(list_id):
    denied = _guard("purchase_list.execute")
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    key = request.headers.get("Idempotency-Key") or payload.get("idempotency_key")
    try:
        summary = execute_list(
            list_id,
            employee_id=session.get("user_id"),
            discard_unselected=bool(payload.get("discard_unselected", True)),
            idempotency_key=key,
        )
        return jsonify({"success": True, "message": "تم تنفيذ قائمة الشراء بنجاح", "summary": summary})
    except Exception as exc:
        return _json_error(exc)


@purchase_lists_bp.get("/<int:list_id>/print")
def print_list(list_id):
    denied = _guard("purchase_list.print")
    if denied:
        return denied
    row = get_list_or_error(list_id)
    return render_template(
        "purchase_lists/print_list.html",
        purchase_list=row,
        can_view_cost=_can("purchase_list.view_cost"),
        reason_labels=REASON_LABELS,
    )


@purchase_lists_bp.get("/<int:list_id>/report")
def execution_report(list_id):
    denied = _guard("purchase_list.print")
    if denied:
        return denied
    row = get_list_or_error(list_id)
    executed = [item for item in row.items if item.status == "executed"]
    grouped = {}
    for item in executed:
        grouped.setdefault(item.supplier, []).append(item)
    return render_template("purchase_lists/execution_report.html", purchase_list=row, grouped=grouped,
                           payment_labels=PAYMENT_METHOD_LABELS, can_view_cost=_can("purchase_list.view_cost"))


@purchase_lists_bp.get("/<int:list_id>/invoices/print")
def print_all_invoices(list_id):
    denied = _guard("purchase_list.print")
    if denied:
        return denied
    row = get_list_or_error(list_id)
    invoice_ids = sorted({item.purchase_invoice_id for item in row.items if item.purchase_invoice_id})
    purchases = Purchase.query.filter(Purchase.id.in_(invoice_ids)).order_by(Purchase.id).all() if invoice_ids else []
    return render_template(
        "purchase_lists/print_invoices.html",
        purchase_list=row,
        purchases=purchases,
        can_view_cost=_can("purchase_list.view_cost"),
    )


@purchase_lists_bp.post("/api/from-inventory/<int:product_id>")
def add_from_inventory(product_id):
    denied = _guard("purchase_list.create")
    if denied:
        return denied
    try:
        product = Product.query.execution_options(skip_branch_scope=True).filter_by(id=product_id, active=True).first()
        if not product:
            raise PurchaseListError("المنتج غير موجود.", code="not_found")
        branch_id = product.branch_id if product.branch_id in allowed_branch_ids() else (allowed_branch_ids()[0] if allowed_branch_ids() else 0)
        tenant_id = current_tenant_id()
        warehouses = [w for w in list_warehouses(tenant_id) if not w.branch_id or w.branch_id == branch_id]
        if not warehouses:
            warehouses = ensure_default_warehouses(tenant_id, branch_id)
        row = (
            scoped_lists_query().filter(
                PurchaseList.branch_id == branch_id,
                PurchaseList.warehouse_id == warehouses[0].id,
                PurchaseList.list_date == date.today(),
                PurchaseList.status.in_(("draft", "open", "partially_executed")),
            ).order_by(PurchaseList.id.desc()).first()
        )
        if not row:
            row = create_list(branch_id=branch_id, warehouse_id=warehouses[0].id,
                              responsible_employee_id=session.get("user_id"), list_date=date.today(), notes=None,
                              employee_id=session.get("user_id"))
        last_item = (
            PurchaseItem.query.join(Purchase, Purchase.id == PurchaseItem.purchase_id)
            .filter(PurchaseItem.product_id == product.id, Purchase.status == "confirmed")
            .order_by(Purchase.purchase_date.desc(), Purchase.id.desc()).first()
        )
        supplier_id = last_item.purchase.supplier_id if last_item and last_item.purchase else None
        try:
            product_meta = json.loads(product.meta_json or "{}")
        except (TypeError, ValueError):
            product_meta = {}
        target_stock = int(product_meta.get("target_stock") or product.low_stock_threshold or 0)
        suggested = max(1, target_stock - int(product.quantity or 0))
        if supplier_id:
            add_item(row, {
                "product_id": product.id, "supplier_id": supplier_id, "quantity": suggested,
                "purchase_price": int(product.buy_price or 0), "payment_method": "credit",
                "purchase_reason": "low_stock", "is_selected": True,
            }, session.get("user_id"))
        db.session.commit()
        return jsonify({"success": True, "redirect_url": url_for("purchase_lists.detail", list_id=row.id,
                        product_id=None if supplier_id else product.id), "item_added": bool(supplier_id)})
    except Exception as exc:
        db.session.rollback()
        return _json_error(exc)
