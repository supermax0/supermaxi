"""Unified JSON API for wholesale — also consumed by future React UI."""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request, Response

from extensions import db
from models.branch import Branch
from models.customer import Customer
from models.supplier import Supplier
from models.treasury_account import TreasuryAccount
from modules.wholesale.guards import current_tenant_id, require_wholesale
from modules.wholesale.schema_guard import ensure_wholesale_schema
from modules.wholesale.services import (
    draft_autosave,
    party_ledger_service,
    purchase_service,
    receipt_service,
    sale_service,
    supplier_payment_service,
    warehouse_service,
)
from modules.wholesale.services.helpers import WholesaleError, parse_int
from utils.activity_logger import log_activity
from sqlalchemy import or_

wholesale_api_bp = Blueprint("wholesale_api", __name__, url_prefix="/api/wholesale")


@wholesale_api_bp.before_request
def _api_schema():
    ensure_wholesale_schema()


def _tid():
    return getattr(g, "wholesale_tenant_id", None) or current_tenant_id()


def _emp_id():
    emp = getattr(g, "wholesale_employee", None)
    return emp.id if emp else None


def _ok(data=None, **extra):
    payload = {"ok": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return jsonify(payload)


def _err(exc, status=400):
    if isinstance(exc, WholesaleError):
        return jsonify({"ok": False, "error": exc.message, "code": exc.code}), status
    return jsonify({"ok": False, "error": str(exc)}), status


@wholesale_api_bp.route("/context", methods=["GET"])
@require_wholesale("wholesale_ops", json_mode=True)
def api_context():
    tid = _tid()
    warehouses = warehouse_service.ensure_default_warehouses(tid)
    branches = Branch.query.filter(Branch.is_active.is_(True)).all()
    treasuries = []
    try:
        treasuries = [
            {"id": t.id, "name": t.name}
            for t in TreasuryAccount.query.limit(50).all()
        ]
    except Exception:
        treasuries = []
    from modules.wholesale.guards import WHOLESALE_PERMISSIONS

    emp = getattr(g, "wholesale_employee", None)
    default_warehouse_id = getattr(emp, "default_warehouse_id", None) if emp else None
    if default_warehouse_id and not any(int(w.id) == int(default_warehouse_id) for w in warehouses):
        default_warehouse_id = None
    if emp and emp.role == "admin":
        perms = list(WHOLESALE_PERMISSIONS)
    elif emp:
        perms = [p for p in WHOLESALE_PERMISSIONS if emp.has_permission(p)]
    else:
        perms = []
    return _ok(
        {
            "tenant_id": tid,
            "currencies": ["IQD", "USD"],
            "default_currency": "IQD",
            "default_exchange_rate": 1500.0,
            "warehouses": [w.to_dict() for w in warehouses],
            "default_warehouse_id": default_warehouse_id,
            "branches": [b.to_dict() for b in branches],
            "treasury_accounts": treasuries,
            "permissions": perms,
            "next_sale_no": sale_service.next_invoice_no(tid),
            "next_purchase_no": purchase_service.next_purchase_no(tid),
        }
    )


# ── Parties ──────────────────────────────────────────────────────────────
@wholesale_api_bp.route("/customers/search", methods=["GET"])
@require_wholesale("wholesale_ops", json_mode=True)
def search_customers():
    tid = _tid()
    q = (request.args.get("q") or "").strip()
    query = Customer.query
    if tid is not None:
        query = query.filter(or_(Customer.tenant_id == tid, Customer.tenant_id.is_(None)))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Customer.name.ilike(like), Customer.phone.ilike(like)))
    rows = query.order_by(Customer.name.asc()).limit(30).all()
    return _ok(
        [
            {
                "id": c.id,
                "name": c.name,
                "phone": c.phone,
                "balance": party_ledger_service.party_balance(tid, "customer", c.id),
            }
            for c in rows
        ]
    )


@wholesale_api_bp.route("/customers", methods=["POST"])
@require_wholesale("wholesale_ops", json_mode=True)
def create_customer():
    tid = _tid()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip() or "0000000000"
    if not name:
        return _err(WholesaleError("اسم العميل مطلوب"))
    c = Customer(tenant_id=tid, name=name, phone=phone, address=data.get("address"), notes=data.get("notes"))
    db.session.add(c)
    db.session.commit()
    return _ok({"id": c.id, "name": c.name, "phone": c.phone})


@wholesale_api_bp.route("/suppliers/search", methods=["GET"])
@require_wholesale("wholesale_ops", json_mode=True)
def search_suppliers():
    tid = _tid()
    q = (request.args.get("q") or "").strip()
    query = Supplier.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Supplier.name.ilike(like), Supplier.phone.ilike(like) if hasattr(Supplier, "phone") else Supplier.name.ilike(like)))
    rows = query.order_by(Supplier.name.asc()).limit(30).all()
    return _ok(
        [
            {
                "id": s.id,
                "name": s.name,
                "balance": party_ledger_service.party_balance(tid, "supplier", s.id),
            }
            for s in rows
        ]
    )


@wholesale_api_bp.route("/suppliers", methods=["POST"])
@require_wholesale("wholesale_ops", json_mode=True)
def create_supplier():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return _err(WholesaleError("اسم المورد مطلوب"))
    s = Supplier(name=name)
    if hasattr(s, "phone") and data.get("phone"):
        s.phone = data.get("phone")
    db.session.add(s)
    db.session.commit()
    return _ok({"id": s.id, "name": s.name})


@wholesale_api_bp.route("/products/search", methods=["GET"])
@require_wholesale("wholesale_ops", json_mode=True)
def search_products():
    tid = _tid()
    wh = parse_int(request.args.get("warehouse_id")) or None
    return _ok(sale_service.search_products(tid, request.args.get("q") or "", warehouse_id=wh))


# ── Sales ────────────────────────────────────────────────────────────────
@wholesale_api_bp.route("/sales", methods=["GET"])
@require_wholesale("wholesale_sales", json_mode=True)
def list_sales():
    rows = sale_service.list_sales(_tid())
    return _ok([sale_service.sale_to_dict(r) for r in rows])


@wholesale_api_bp.route("/sales", methods=["POST"])
@require_wholesale("wholesale_sales", json_mode=True)
def create_sale():
    tid = _tid()
    data = request.get_json(silent=True) or {}
    confirm = bool(data.get("confirm"))
    as_draft = bool(data.get("draft") or data.get("as_draft")) and not confirm
    try:
        inv = sale_service.create_or_update_sale(
            tid, data, employee_id=_emp_id(), confirm=confirm, as_draft=as_draft
        )
        db.session.commit()
        return _ok(sale_service.sale_to_dict(inv))
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


@wholesale_api_bp.route("/sales/<int:invoice_id>/confirm", methods=["POST"])
@require_wholesale("wholesale_sales", json_mode=True)
def confirm_sale(invoice_id):
    try:
        inv = sale_service.confirm_sale(_tid(), invoice_id, employee_id=_emp_id())
        db.session.commit()
        return _ok(sale_service.sale_to_dict(inv))
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


# ── Receipts ─────────────────────────────────────────────────────────────
@wholesale_api_bp.route("/receipts", methods=["POST"])
@require_wholesale("wholesale_receipts", json_mode=True)
def create_receipt():
    try:
        result = receipt_service.create_receipt(_tid(), request.get_json(silent=True) or {}, employee_id=_emp_id())
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


@wholesale_api_bp.route("/customers/<int:customer_id>/balance", methods=["GET"])
@require_wholesale("wholesale_receipts", json_mode=True)
def customer_balance(customer_id):
    tid = _tid()
    currency = request.args.get("currency")
    bal = party_ledger_service.party_balance(tid, "customer", customer_id, currency)
    opens = receipt_service.customer_open_invoices(tid, customer_id)
    return _ok(
        {
            "balance": bal,
            "open_invoices": [
                {
                    "id": i.id,
                    "invoice_no": i.invoice_no,
                    "total": int(i.total or 0),
                    "paid_amount": int(i.paid_amount or 0),
                    "remaining": max(0, int(i.total or 0) - int(i.paid_amount or 0)),
                }
                for i in opens
            ],
        }
    )


# ── Purchases ────────────────────────────────────────────────────────────
@wholesale_api_bp.route("/purchases", methods=["GET"])
@require_wholesale("wholesale_purchases", json_mode=True)
def list_purchases():
    return _ok([purchase_service.purchase_to_dict(p) for p in purchase_service.list_purchases(_tid())])


@wholesale_api_bp.route("/purchases", methods=["POST"])
@require_wholesale("wholesale_purchases", json_mode=True)
def create_purchase():
    data = request.get_json(silent=True) or {}
    confirm = bool(data.get("confirm"))
    as_draft = bool(data.get("draft") or data.get("as_draft")) and not confirm
    try:
        p = purchase_service.create_or_update_purchase(
            _tid(), data, employee_id=_emp_id(), confirm=confirm, as_draft=as_draft
        )
        db.session.commit()
        return _ok(purchase_service.purchase_to_dict(p))
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


@wholesale_api_bp.route("/purchases/<int:purchase_id>/confirm", methods=["POST"])
@require_wholesale("wholesale_purchases", json_mode=True)
def confirm_purchase(purchase_id):
    try:
        p = purchase_service.confirm_purchase(_tid(), purchase_id, employee_id=_emp_id())
        db.session.commit()
        return _ok(purchase_service.purchase_to_dict(p))
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


# ── Supplier payments ────────────────────────────────────────────────────
@wholesale_api_bp.route("/payments", methods=["POST"])
@require_wholesale("wholesale_payments", json_mode=True)
def create_payment():
    try:
        result = supplier_payment_service.create_payment(
            _tid(), request.get_json(silent=True) or {}, employee_id=_emp_id()
        )
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


@wholesale_api_bp.route("/suppliers/<int:supplier_id>/balance", methods=["GET"])
@require_wholesale("wholesale_payments", json_mode=True)
def supplier_balance(supplier_id):
    tid = _tid()
    bal = party_ledger_service.party_balance(tid, "supplier", supplier_id, request.args.get("currency"))
    opens = supplier_payment_service.supplier_open_purchases(tid, supplier_id)
    return _ok(
        {
            "balance": bal,
            "open_purchases": [
                {
                    "id": p.id,
                    "invoice_no": p.invoice_no,
                    "grand_total": int(p.grand_total or 0),
                    "paid_total": int(p.paid_total or 0),
                    "remaining": max(0, int(p.grand_total or 0) - int(p.paid_total or 0)),
                }
                for p in opens
            ],
        }
    )


# ── Warehouses ───────────────────────────────────────────────────────────
@wholesale_api_bp.route("/warehouses", methods=["GET"])
@require_wholesale("wholesale_warehouses", json_mode=True)
def list_warehouses():
    tid = _tid()
    rows = warehouse_service.ensure_default_warehouses(tid)
    return _ok([w.to_dict() for w in rows])


@wholesale_api_bp.route("/warehouses", methods=["POST"])
@require_wholesale("wholesale_warehouses", json_mode=True)
def create_warehouse():
    data = request.get_json(silent=True) or {}
    try:
        wh = warehouse_service.create_warehouse(
            _tid(),
            code=data.get("code") or "",
            name=data.get("name") or "",
            branch_id=parse_int(data.get("branch_id")) or None,
            kind=data.get("kind") or "main",
        )
        db.session.commit()
        return _ok(wh.to_dict())
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


@wholesale_api_bp.route("/warehouses/transfer", methods=["POST"])
@require_wholesale("wholesale_warehouses", json_mode=True)
def transfer_stock():
    data = request.get_json(silent=True) or {}
    try:
        tr = warehouse_service.create_transfer(
            _tid(),
            from_warehouse_id=parse_int(data.get("from_warehouse_id")),
            to_warehouse_id=parse_int(data.get("to_warehouse_id")),
            lines=data.get("lines") or [],
            note=data.get("note"),
            created_by=_emp_id(),
            send=bool(data.get("send", True)),
        )
        if data.get("receive"):
            warehouse_service.receive_transfer(_tid(), tr.id, received_by=_emp_id())
        log_activity("create", "wholesale", f"إنشاء تحويل مخزني {tr.transfer_no}", entity_type="warehouse_transfer", entity_id=tr.id, commit=False)
        db.session.commit()
        return _ok({"id": tr.id, "transfer_no": tr.transfer_no, "status": tr.status})
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


@wholesale_api_bp.route("/warehouses/transfers", methods=["GET"])
@require_wholesale("wholesale_warehouses", json_mode=True)
def list_transfers():
    rows = warehouse_service.list_transfers(
        _tid(),
        warehouse_id=parse_int(request.args.get("warehouse_id")) or None,
    )
    return _ok([warehouse_service.transfer_to_dict(t) for t in rows])


@wholesale_api_bp.route("/warehouses/transfers/<int:transfer_id>/approve", methods=["POST"])
@require_wholesale("wholesale_warehouses", json_mode=True)
def approve_transfer(transfer_id):
    try:
        tr = warehouse_service.approve_transfer(_tid(), transfer_id, approved_by=_emp_id())
        log_activity("update", "wholesale", f"اعتماد تحويل مخزني {tr.transfer_no}", entity_type="warehouse_transfer", entity_id=tr.id, commit=False)
        db.session.commit()
        return _ok(warehouse_service.transfer_to_dict(tr))
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


@wholesale_api_bp.route("/warehouses/transfers/<int:transfer_id>/send", methods=["POST"])
@require_wholesale("wholesale_warehouses", json_mode=True)
def send_transfer(transfer_id):
    try:
        tr = warehouse_service.send_transfer(_tid(), transfer_id, created_by=_emp_id())
        log_activity("update", "wholesale", f"إرسال تحويل مخزني {tr.transfer_no}", entity_type="warehouse_transfer", entity_id=tr.id, commit=False)
        db.session.commit()
        return _ok(warehouse_service.transfer_to_dict(tr))
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


@wholesale_api_bp.route("/warehouses/transfers/<int:transfer_id>/receive", methods=["POST"])
@require_wholesale("wholesale_warehouses", json_mode=True)
def receive_transfer(transfer_id):
    try:
        tr = warehouse_service.receive_transfer(_tid(), transfer_id, received_by=_emp_id())
        log_activity("update", "wholesale", f"استلام تحويل مخزني {tr.transfer_no}", entity_type="warehouse_transfer", entity_id=tr.id, commit=False)
        db.session.commit()
        return _ok(warehouse_service.transfer_to_dict(tr))
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


@wholesale_api_bp.route("/warehouses/transfers/<int:transfer_id>/cancel", methods=["POST"])
@require_wholesale("wholesale_warehouses", json_mode=True)
def cancel_transfer(transfer_id):
    try:
        tr = warehouse_service.cancel_transfer(_tid(), transfer_id, cancelled_by=_emp_id())
        log_activity("update", "wholesale", f"إلغاء تحويل مخزني {tr.transfer_no}", entity_type="warehouse_transfer", entity_id=tr.id, commit=False)
        db.session.commit()
        return _ok(warehouse_service.transfer_to_dict(tr))
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


@wholesale_api_bp.route("/warehouses/adjust", methods=["POST"])
@require_wholesale("wholesale_warehouses", json_mode=True)
def adjust_stock():
    data = request.get_json(silent=True) or {}
    try:
        row = warehouse_service.adjust_stock(
            _tid(),
            warehouse_id=parse_int(data.get("warehouse_id")),
            product_id=parse_int(data.get("product_id")),
            new_quantity=parse_int(data.get("quantity")),
            created_by=_emp_id(),
            note=data.get("note"),
        )
        db.session.commit()
        return _ok({"warehouse_id": row.warehouse_id, "product_id": row.product_id, "quantity": row.quantity})
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


@wholesale_api_bp.route("/warehouses/movements", methods=["GET"])
@require_wholesale("wholesale_warehouses", json_mode=True)
def movements():
    rows = warehouse_service.list_movements(
        _tid(),
        warehouse_id=parse_int(request.args.get("warehouse_id")) or None,
        product_id=parse_int(request.args.get("product_id")) or None,
    )
    return _ok(
        [
            {
                "id": m.id,
                "warehouse_id": m.warehouse_id,
                "product_id": m.product_id,
                "movement_type": m.movement_type,
                "quantity": m.quantity,
                "reference_type": m.reference_type,
                "reference_id": m.reference_id,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in rows
        ]
    )


@wholesale_api_bp.route("/stock-ledger", methods=["GET"])
@require_wholesale("wholesale_warehouses", json_mode=True)
def stock_ledger():
    """Detailed item ledger; the reference can be used to open its document."""
    rows = warehouse_service.list_movements(
        _tid(),
        warehouse_id=parse_int(request.args.get("warehouse_id")) or None,
        product_id=parse_int(request.args.get("product_id")) or None,
        limit=min(500, max(1, parse_int(request.args.get("limit")) or 200)),
    )
    return _ok(
        [
            {
                "id": m.id,
                "date": m.created_at.isoformat() if m.created_at else None,
                "movement_type": m.movement_type,
                "document_type": m.reference_type,
                "document_id": m.reference_id,
                "warehouse_id": m.warehouse_id,
                "product_id": m.product_id,
                "quantity_in": max(0, int(m.quantity or 0)),
                "quantity_out": max(0, -int(m.quantity or 0)),
                "balance_before": m.quantity_before,
                "balance_after": m.quantity_after,
                "user_id": m.created_by,
                "note": m.note,
            }
            for m in rows
        ]
    )


@wholesale_api_bp.route("/settings/default-warehouse", methods=["POST"])
@require_wholesale("wholesale_settings", json_mode=True)
def set_default_warehouse():
    emp = getattr(g, "wholesale_employee", None)
    warehouse_id = parse_int((request.get_json(silent=True) or {}).get("warehouse_id")) or None
    if warehouse_id is not None:
        warehouse_service.get_warehouse(_tid(), warehouse_id)
    emp.default_warehouse_id = warehouse_id
    db.session.commit()
    return _ok({"default_warehouse_id": warehouse_id})


# ── Statement ────────────────────────────────────────────────────────────
@wholesale_api_bp.route("/statement", methods=["GET"])
@require_wholesale("wholesale_statement", json_mode=True)
def statement():
    tid = _tid()
    party_type = (request.args.get("party_type") or "customer").strip()
    party_id = parse_int(request.args.get("party_id"))
    if party_id <= 0:
        return _err(WholesaleError("اختر العميل أو المورد"))
    stmt = party_ledger_service.build_statement(
        tid,
        party_type=party_type,
        party_id=party_id,
        date_from=request.args.get("from"),
        date_to=request.args.get("to"),
        currency=request.args.get("currency"),
    )
    fmt = (request.args.get("format") or "json").lower()
    if fmt == "csv":
        csv_data = party_ledger_service.statement_to_csv(stmt)
        return Response(
            csv_data,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=statement.csv"},
        )
    if fmt in ("xlsx", "excel"):
        raw = party_ledger_service.statement_to_xlsx_bytes(stmt)
        return Response(
            raw,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=statement.xlsx"},
        )
    return _ok(stmt)


# ── Drafts ───────────────────────────────────────────────────────────────
@wholesale_api_bp.route("/drafts", methods=["GET"])
@require_wholesale("wholesale_ops", json_mode=True)
def list_drafts():
    rows = draft_autosave.list_drafts(_tid(), employee_id=_emp_id(), op_type=request.args.get("op_type"))
    return _ok([draft_autosave.draft_to_dict(d) for d in rows])


@wholesale_api_bp.route("/drafts", methods=["POST"])
@require_wholesale("wholesale_ops", json_mode=True)
def save_draft():
    data = request.get_json(silent=True) or {}
    try:
        d = draft_autosave.save_draft(
            _tid(),
            employee_id=_emp_id(),
            op_type=data.get("op_type") or "sale",
            payload=data.get("payload") or data,
            draft_id=parse_int(data.get("id")) or None,
            title=data.get("title"),
        )
        db.session.commit()
        return _ok(draft_autosave.draft_to_dict(d))
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


@wholesale_api_bp.route("/drafts/<int:draft_id>", methods=["DELETE"])
@require_wholesale("wholesale_ops", json_mode=True)
def delete_draft(draft_id):
    try:
        draft_autosave.delete_draft(_tid(), draft_id)
        db.session.commit()
        return _ok({"deleted": True})
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


# ── Reports summary ──────────────────────────────────────────────────────
@wholesale_api_bp.route("/reports/summary", methods=["GET"])
@require_wholesale("wholesale_reports", json_mode=True)
def reports_summary():
    tid = _tid()
    sales = sale_service.list_sales(tid, limit=500, include_drafts=False)
    purchases = purchase_service.list_purchases(tid, limit=500)
    sales_total = sum(int(s.total or 0) for s in sales if not s.is_draft)
    purchases_total = sum(int(p.grand_total or 0) for p in purchases if p.status == "confirmed")
    return _ok(
        {
            "sales_count": len([s for s in sales if not s.is_draft]),
            "sales_total": sales_total,
            "purchases_count": len([p for p in purchases if p.status == "confirmed"]),
            "purchases_total": purchases_total,
            "warehouses": len(warehouse_service.list_warehouses(tid)),
        }
    )
