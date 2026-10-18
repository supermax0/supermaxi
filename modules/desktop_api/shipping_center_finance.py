"""Shipping & Logistics Center — phase 2: account statements, receipt vouchers, agent custody, returns
inspection and per-carrier settings.

Returned stock goes back through ``utils.order_lifecycle.process_order_return`` (FIFO lots, sale reversal,
collection reversal) and damaged quantities through the stock write-off service
(``modules.stock_operations.writeoffs.post`` — inventory-loss journal). Nothing here posts money or stock itself.
"""
from __future__ import annotations

import json
from datetime import datetime
from html import escape
from typing import Any

from flask import Response, request, session

from extensions import db
from models.delivery_agent import DeliveryAgent
from models.invoice import Invoice
from models.shipping import ShippingCompany
from models.shipping_report import ShippingReport
from modules.desktop_api.routes import _error, desktop_api_bp
from modules.desktop_api.shipping_center import (
    PORTAL_STATUS,
    PREFIX,
    STATUS_DELIVERED,
    _authorize,
    _company_ids,
    _is_admin,
    _order_row,
    _rows,
    _selections,
    _agent_ids,
    _portal_reports_filter,
    _tables,
    find_order_by_code,
    statement_lines,
)
from utils.permission_checks import employee_can, get_current_employee


def _ok(**data: Any):
    from flask import jsonify

    return jsonify({"ok": True, **data})


# ───────────────────────────── statements, custody, receipts ─────────────────────────────


@desktop_api_bp.get(f"{PREFIX}/<any(carriers, agents):owner>/<int:party_id>/statement")
def shipping_center_statement(owner: str, party_id: int):
    denied = _authorize()
    if denied:
        return denied
    party_type = "carrier" if owner == "carriers" else "agent"
    lines = statement_lines(party_type, party_id)
    debit = sum(line["debit"] for line in lines)
    credit = sum(line["credit"] for line in lines)
    return _ok(lines=lines, debit=debit, credit=credit, balance=debit - credit,
               custody=_agent_custody(party_id) if party_type == "agent" else None)


def _agent_custody(agent_id: int) -> dict[str, int]:
    """What the agent reported as collected in the portal (still open) — money held by the agent."""
    claimed_count, claimed_amount = 0, 0
    seen: set[int] = set()
    for report in ShippingReport.query.filter(ShippingReport.is_executed.is_(False),
                                              _portal_reports_filter(_agent_ids(agent_id))).all():
        selections = _selections(report)
        for raw in _rows(report):
            oid = int(raw.get("id") or raw.get("order_id") or 0)
            if not oid or oid in seen or PORTAL_STATUS.get(selections.get(str(oid), "")) != STATUS_DELIVERED:
                continue
            seen.add(oid)
            order = Invoice.query.get(oid)
            if order is None:
                continue
            remaining = _order_row(order)["remaining"]
            if remaining > 0:
                claimed_count += 1
                claimed_amount += remaining
    lines = statement_lines("agent", agent_id)
    outstanding = lines[-1]["balance"] if lines else 0
    received = sum(line["credit"] for line in lines if line["label"].startswith(("سند قبض", "مبلغ مستلم")))
    return {"claimed_count": claimed_count, "claimed_amount": claimed_amount, "settled_outstanding": outstanding,
            "received_total": received, "in_custody": claimed_amount + outstanding}


def _receipt_payload(receipt) -> dict[str, Any]:
    return {
        "id": receipt.id, "number": receipt.receipt_number,
        "party_type": "agent" if receipt.source_type == "courier" else "carrier", "party_id": receipt.source_id,
        "party_name": receipt.source_name or "", "amount": int(receipt.amount or 0),
        "payment_method": receipt.payment_method or "cash",
        "treasury_account": receipt.treasury_account.name if receipt.treasury_account else "",
        "date": receipt.receipt_date.isoformat() if receipt.receipt_date else "",
        "reference": receipt.reference_number or "", "notes": receipt.notes or "", "status": receipt.status,
        "balance_before": int(receipt.balance_before or 0), "balance_after": int(receipt.balance_after or 0),
        "created_by": receipt.creator.name if receipt.creator else "",
        "allocations": [{"order_id": a.reference_id, "label": a.reference_label or f"#{a.reference_id}",
                         "amount": int(a.allocated_amount or 0)} for a in receipt.allocations],
    }


@desktop_api_bp.get(f"{PREFIX}/receipts")
def shipping_center_receipts():
    denied = _authorize()
    if denied:
        return denied
    _tables()
    from models.receipt import Receipt

    q = Receipt.query.filter(Receipt.receipt_number.like("RCV-SHP-%"))
    owner = request.args.get("party_type")
    party_id = request.args.get("party_id", type=int)
    if owner in ("carrier", "agent") and party_id:
        if owner == "carrier":
            q = q.filter(Receipt.source_type == "shipping_company",
                         Receipt.source_id.in_(_company_ids(party_id) or [party_id]))
        else:
            q = q.filter(Receipt.source_type == "courier", Receipt.source_id.in_(_agent_ids(party_id)))
    search = (request.args.get("search") or "").strip()
    if search:
        q = q.filter(db.or_(Receipt.receipt_number.ilike(f"%{search}%"), Receipt.source_name.ilike(f"%{search}%"),
                            Receipt.reference_number.ilike(f"%{search}%")))
    rows = q.order_by(Receipt.id.desc()).limit(200).all()
    return _ok(rows=[_receipt_payload(r) for r in rows])


@desktop_api_bp.get(f"{PREFIX}/receipts/<int:receipt_id>/print")
def shipping_center_receipt_print(receipt_id: int):
    denied = _authorize()
    if denied:
        return denied
    _tables()
    from models.receipt import Receipt

    receipt = Receipt.query.get(receipt_id)
    if receipt is None or not str(receipt.receipt_number).startswith("RCV-SHP-"):
        return _error("السند غير موجود", 404, "not_found")
    data = _receipt_payload(receipt)
    rows = "".join(f"<tr><td>{escape(a['label'])}</td><td>{a['amount']:,}</td></tr>" for a in data["allocations"])
    method = "تحويل مصرفي" if data["payment_method"] == "bank" else "نقداً"
    html = f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>{escape(data['number'])}</title>
<style>body{{font-family:Tahoma,Arial,sans-serif;margin:32px;color:#1f1f29}}h1{{color:#7a1f3d;margin:0 0 4px}}
table{{width:100%;border-collapse:collapse;margin-top:16px}}td,th{{border:1px solid #ddd;padding:8px;text-align:right}}
th{{background:#f6eef1}}.meta td{{border:none;padding:4px 0}}.total{{font-size:20px;font-weight:bold;color:#7a1f3d}}
.sign{{display:flex;justify-content:space-between;margin-top:56px}}</style></head><body>
<h1>سند قبض</h1><div>{escape(data['number'])}</div>
<table class="meta"><tr><td>استلمنا من: <b>{escape(data['party_name'])}</b></td><td>التاريخ: {escape(data['date'])}</td></tr>
<tr><td>المرجع: {escape(data['reference'])}</td><td>طريقة القبض: {method} — {escape(data['treasury_account'])}</td></tr>
<tr><td colspan="2">البيان: {escape(data['notes'])}</td></tr></table>
<p class="total">المبلغ: {data['amount']:,} د.ع</p>
<table><thead><tr><th>الطلب</th><th>المبلغ المخصص</th></tr></thead><tbody>{rows}</tbody></table>
<p>الرصيد قبل السند: {data['balance_before']:,} د.ع — الرصيد بعده: {data['balance_after']:,} د.ع</p>
<div class="sign"><span>المستلم: {escape(data['created_by'])}</span><span>توقيع المسلِّم: ____________</span></div>
</body></html>"""
    return Response(html, mimetype="text/html")


# ───────────────────────────── carrier settings ─────────────────────────────


CYCLES = ("daily", "weekly", "manifest")


@desktop_api_bp.get(f"{PREFIX}/carriers/<int:company_id>/settings")
def shipping_center_carrier_settings(company_id: int):
    denied = _authorize()
    if denied:
        return denied
    company = ShippingCompany.query.get(company_id)
    if company is None:
        return _error("شركة النقل غير موجودة", 404, "not_found")
    return _ok(settings=_settings_payload(company))


def _settings_payload(company) -> dict[str, Any]:
    from models.shipping_center import ShippingCarrierSetting

    _tables()
    row = ShippingCarrierSetting.query.get(company.id)
    return {"carrier_id": company.id, "price": int(company.price or 0),
            "return_fee": int(row.return_fee or 0) if row else 0,
            "settlement_cycle": row.settlement_cycle if row else "manifest",
            "payment_method": row.payment_method if row else "cash",
            "treasury_account_id": row.treasury_account_id if row else None,
            "notes": (row.notes or "") if row else "",
            "updated_by": (row.updated_by or "") if row else "",
            "updated_at": row.updated_at.strftime("%Y-%m-%d %H:%M") if row and row.updated_at else ""}


@desktop_api_bp.post(f"{PREFIX}/carriers/<int:company_id>/settings")
def shipping_center_carrier_settings_save(company_id: int):
    denied = _authorize("can_manage_shipping")
    if denied:
        return denied
    company = ShippingCompany.query.get(company_id)
    if company is None:
        return _error("شركة النقل غير موجودة", 404, "not_found")
    data = request.get_json(silent=True) or {}
    try:
        price = int(data.get("price", company.price or 0) or 0)
        return_fee = int(data.get("return_fee") or 0)
    except (TypeError, ValueError):
        return _error("أدخل مبالغ صحيحة", 400, "validation")
    if price < 0 or return_fee < 0:
        return _error("المبالغ لا تكون سالبة", 400, "validation")
    cycle = str(data.get("settlement_cycle") or "manifest")
    method = str(data.get("payment_method") or "cash")
    if cycle not in CYCLES or method not in ("cash", "bank"):
        return _error("اختر دورة التسديد وطريقة الاستلام من القائمة", 400, "validation")
    from models.shipping_center import ShippingCarrierSetting

    _tables()
    row = ShippingCarrierSetting.query.get(company.id) or ShippingCarrierSetting(carrier_id=company.id)
    row.return_fee, row.settlement_cycle, row.payment_method = return_fee, cycle, method
    row.treasury_account_id = int(data["treasury_account_id"]) if str(data.get("treasury_account_id") or "").isdigit() else None
    row.notes = str(data.get("notes") or "").strip()[:500]
    row.updated_by = session.get("name", "")
    row.updated_at = datetime.utcnow()
    db.session.add(row)
    company.price = price  # FINORA's own default delivery fee for new orders of this carrier
    db.session.commit()
    return _ok(settings=_settings_payload(company))


# ───────────────────────────── returns: awaiting → received → inspected & closed ─────────────────────────────


def _return_payload(row, *, details: bool = False) -> dict[str, Any]:
    order = Invoice.query.get(row.order_id)
    live = _order_row(order) if order else {}
    data = {
        "id": row.id, "order_id": row.order_id, "state": row.state,
        "manifest_id": row.manifest_id, "manifest_number": row.manifest_number or "",
        "party_type": row.party_type, "party_id": row.party_id, "party_name": row.party_name or "",
        "order_amount": int(row.order_amount or 0),
        "customer_name": live.get("customer_name", ""), "customer_city": live.get("customer_city", ""),
        "order_status": live.get("status", ""), "waybills": live.get("waybills", []),
        "reported_at": row.reported_at.strftime("%Y-%m-%d %H:%M") if row.reported_at else "",
        "received_at": row.received_at.strftime("%Y-%m-%d %H:%M") if row.received_at else "",
        "received_by": row.received_by or "",
        "closed_at": row.closed_at.strftime("%Y-%m-%d %H:%M") if row.closed_at else "",
        "closed_by": row.closed_by or "", "branch_id": row.branch_id, "packaging_ok": row.packaging_ok,
        "inspection": json.loads(row.inspection_json or "[]"), "writeoffs": json.loads(row.writeoffs_json or "[]"),
        "note": row.note or "",
    }
    if details and order is not None:
        data["items"] = _return_items(order)
        data["branches"] = _branches()
    return data


def _return_items(order) -> list[dict[str, Any]]:
    from utils.order_shipping import SHIPPING_PRODUCT_NAME

    return [{"item_id": item.id, "product_id": item.product_id, "name": item.product_name or "",
             "variant": item.variant_color or "", "quantity": int(item.quantity or 0),
             "branch_id": item.fulfillment_branch_id}
            for item in order.items if (item.product_name or "") != SHIPPING_PRODUCT_NAME and int(item.quantity or 0) > 0]


def _branches() -> list[dict[str, Any]]:
    from modules.inventory_audit.stock import locations

    try:
        return [{"id": row["branch_id"], "name": row["name"]} for row in locations("branch")]
    except Exception:
        return []


@desktop_api_bp.get(f"{PREFIX}/returns")
def shipping_center_returns():
    denied = _authorize()
    if denied:
        return denied
    _tables()
    from models.shipping_center import ShippingReturn

    q = ShippingReturn.query
    state = (request.args.get("state") or "open").strip()
    if state == "open":
        q = q.filter(ShippingReturn.state != "closed")
    elif state in ("awaiting", "received", "closed"):
        q = q.filter(ShippingReturn.state == state)
    party_type = request.args.get("party_type")
    party_id = request.args.get("party_id", type=int)
    if party_type in ("carrier", "agent") and party_id:
        ids = (_company_ids(party_id) or [party_id]) if party_type == "carrier" else _agent_ids(party_id)
        q = q.filter(ShippingReturn.party_type == party_type, ShippingReturn.party_id.in_(ids))
    search = (request.args.get("search") or "").strip()
    if search.isdigit():
        q = q.filter(ShippingReturn.order_id == int(search))
    elif search:
        q = q.filter(db.or_(ShippingReturn.party_name.ilike(f"%{search}%"),
                            ShippingReturn.manifest_number.ilike(f"%{search}%")))
    rows = q.order_by(ShippingReturn.id.desc()).limit(300).all()
    base = ShippingReturn.query
    counts = {"awaiting": base.filter(ShippingReturn.state == "awaiting").count(),
              "received": base.filter(ShippingReturn.state == "received").count(),
              "closed": base.filter(ShippingReturn.state == "closed").count()}
    return _ok(rows=[_return_payload(r) for r in rows], counts=counts)


@desktop_api_bp.get(f"{PREFIX}/returns/<int:return_id>")
def shipping_center_return(return_id: int):
    denied = _authorize()
    if denied:
        return denied
    _tables()
    from models.shipping_center import ShippingReturn

    row = ShippingReturn.query.get(return_id)
    if row is None:
        return _error("المرتجع غير موجود", 404, "not_found")
    return _ok(item=_return_payload(row, details=True), can_writeoff=_can_writeoff())


def _can_writeoff() -> bool:
    employee = get_current_employee()
    return bool(employee) and all(employee_can(employee, p) for p in ("edit_current_stock", "finance.approve", "finance.view"))


@desktop_api_bp.post(f"{PREFIX}/returns/receive")
def shipping_center_return_receive():
    """Parcel physically received (scan the order number / barcode / waybill, or pass a return id)."""
    denied = _authorize("can_manage_shipping")
    if denied:
        return denied
    _tables()
    from models.shipping_center import ShippingReturn

    data = request.get_json(silent=True) or {}
    row = None
    if data.get("return_id"):
        row = ShippingReturn.query.get(int(data["return_id"]))
    elif data.get("code"):
        order = find_order_by_code(str(data["code"]))
        if order is not None:
            row = (ShippingReturn.query.filter(ShippingReturn.order_id == order.id, ShippingReturn.state != "closed")
                   .order_by(ShippingReturn.id.desc()).first())
    if row is None:
        return _error("لا يوجد مرتجع مفتوح بهذا الرقم", 404, "not_found")
    if row.state == "closed":
        return _error("المرتجع مغلق مسبقاً", 409, "conflict")
    if row.state == "awaiting":
        row.state = "received"
        row.received_at = datetime.utcnow()
        row.received_by = session.get("name", "")
        db.session.commit()
    return _ok(item=_return_payload(row, details=True))


@desktop_api_bp.post(f"{PREFIX}/returns/<int:return_id>/close")
def shipping_center_return_close(return_id: int):
    """Inspection decision: all quantities go back to the chosen branch through FINORA's return; damaged
    quantities then leave sellable stock with a write-off voucher (inventory-loss journal)."""
    denied = _authorize("can_manage_shipping")
    if denied:
        return denied
    _tables()
    from models.shipping_center import ShippingReturn

    row = ShippingReturn.query.get(return_id)
    if row is None:
        return _error("المرتجع غير موجود", 404, "not_found")
    if row.state == "closed":
        return _error("المرتجع مغلق مسبقاً", 409, "conflict")
    if row.state != "received":
        return _error("سجّل استلام الطرد قبل الفحص", 409, "conflict")
    order = Invoice.query.get(row.order_id)
    if order is None:
        return _error("الطلب لم يعد موجوداً", 404, "not_found")
    data = request.get_json(silent=True) or {}
    branches = {b["id"] for b in _branches()}
    try:
        branch_id = int(data.get("branch_id") or 0)
    except (TypeError, ValueError):
        branch_id = 0
    if branch_id not in branches:
        return _error("اختر الفرع الذي تعود إليه البضاعة", 400, "validation")
    items = {i["item_id"]: i for i in _return_items(order)}
    damaged: dict[int, int] = {}
    for line in data.get("lines") or []:
        try:
            item_id, qty = int(line.get("item_id")), int(line.get("damaged") or 0)
        except (TypeError, ValueError, AttributeError):
            return _error("بيانات الفحص غير صالحة", 400, "validation")
        if item_id not in items:
            return _error("بند غير موجود في الطلب", 400, "validation")
        if qty < 0 or qty > items[item_id]["quantity"]:
            return _error(f"كمية التالف في «{items[item_id]['name']}» أكبر من المرتجع", 400, "validation")
        if qty:
            damaged[item_id] = qty
    if damaged and not _can_writeoff():
        return _error("تسجيل التالف يحتاج صلاحية سندات التلف (تعديل المخزون + اعتماد مالي)", 403, "forbidden")
    if damaged:
        from modules.finance.schema import ensure_schema as ensure_finance_schema

        ensure_finance_schema()  # chart-of-accounts mappings (inventory / inventory loss) — before any change

    from utils.order_lifecycle import OrderLifecycleError, process_order_return

    inspection = [{**i, "damaged": damaged.get(i["item_id"], 0),
                   "sellable": i["quantity"] - damaged.get(i["item_id"], 0)} for i in items.values()]
    writeoff_numbers: list[str] = []
    try:
        process_order_return(order, str(order.id), return_branch_id=branch_id)
        db.session.flush()
        for item_id, qty in damaged.items():
            writeoff_numbers.append(_write_off(order, items[item_id], qty, branch_id))
        row.state = "closed"
        row.branch_id = branch_id
        row.packaging_ok = bool(data.get("packaging_ok", True))
        row.note = str(data.get("note") or "").strip()[:1000]
        row.inspection_json = json.dumps(inspection, ensure_ascii=False)
        row.writeoffs_json = json.dumps(writeoff_numbers, ensure_ascii=False)
        row.closed_at = datetime.utcnow()
        row.closed_by = session.get("name", "")
        db.session.commit()
    except OrderLifecycleError as exc:
        db.session.rollback()
        return _error(str(exc), 409, "conflict")
    except Exception as exc:  # AuditError / FinanceError / period closed carry a user-facing message
        db.session.rollback()
        message = str(exc) if exc.__class__.__name__ in ("AuditError", "FinanceError", "PeriodClosedError") else \
            "تعذر إغلاق المرتجع — لم يتغير شيء"
        return _error(message, 409, "conflict")
    try:
        from utils.activity_logger import log_activity

        log_activity("update", "shipping", f"فحص وإغلاق مرتجع الطلب #{order.id}", entity_type="invoice",
                     entity_id=order.id, payload={"branch_id": branch_id, "damaged": damaged, "writeoffs": writeoff_numbers})
    except Exception:
        pass
    return _ok(item=_return_payload(row, details=True))


def _business_date() -> str:
    from modules.finance.common import today

    return today().isoformat()


def _write_off(order, item: dict[str, Any], quantity: int, branch_id: int) -> str:
    """Damaged quantity → FINORA stock write-off voucher at the branch the goods were just returned to."""
    from modules.inventory_audit.common import actor
    from modules.stock_operations import writeoffs
    from modules.stock_operations.common import balance, item as stock_item, location
    from modules.stock_operations.schema import ensure_schema

    ensure_schema()
    place = location("branch", f"branch:{branch_id}")
    line, product = stock_item("branch", place, item["product_id"], item["variant"] or "")
    stamp = balance("branch", place, line, product)[3]
    body = {"location_key": place["key"], "product_id": item["product_id"], "variant_name": item["variant"] or "",
            "quantity": quantity, "reason": f"تالف من مرتجع الطلب #{order.id} (فحص مركز الشحن)",
            "stock_revision": stamp, "business_date": _business_date()}
    result, _evidence = writeoffs.post("branch", body, actor())
    from models.stock_operations import InventoryWriteOff

    document = db.session.get(InventoryWriteOff, int(result["id"]))
    return document.number if document else str(result["id"])


@desktop_api_bp.get(f"{PREFIX}/agents/<int:agent_id>/portal")
def shipping_center_agent_portal(agent_id: int):
    """Preview of what the agent reported in the portal (before importing it as a settlement)."""
    denied = _authorize()
    if denied:
        return denied
    if DeliveryAgent.query.get(agent_id) is None:
        return _error("المندوب غير موجود", 404, "not_found")
    from modules.desktop_api.shipping_center import _portal_claims

    rows, claims = _portal_claims(agent_id)
    counts: dict[str, int] = {}
    for status in claims.values():
        counts[status] = counts.get(status, 0) + 1
    return _ok(count=len(rows), counts=counts, amount=sum(int(r.get("remaining") or 0) for r in rows),
               can_approve=_is_admin())
