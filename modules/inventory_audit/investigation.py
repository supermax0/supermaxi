"""Evidence-based investigation. No balance changes and no invented custody proof."""
import json

from sqlalchemy import or_

from extensions import db
from models.branch import StockTransfer, StockTransferLine
from models.delivery_agent import DeliveryAgent
from models.invoice import Invoice
from models.order_item import OrderItem
from models.purchase import Purchase
from models.purchase_item import PurchaseItem
from models.stock_movement import StockMovement
from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES
from .common import AuditError, can, dumps, require, visible_branches
from .models import InventoryCountLine
from .service import get_line, line_data, lines, time
from .stock import stock_state


def _details(raw):
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def movements(line, *, before_id=None, limit=40):
    if line.warehouse_id:
        from modules.wholesale.models.warehouse import WarehouseMovement
        q = WarehouseMovement.query.filter_by(warehouse_id=line.warehouse_id, product_id=line.product_id)
        if before_id:
            q = q.filter(WarehouseMovement.id < before_id)
        rows = q.order_by(WarehouseMovement.id.desc()).limit(limit + 1).all()
        items = [{"id": row.id, "kind": row.movement_type, "quantity": row.quantity,
            "before": row.quantity_before, "after": row.quantity_after, "created_at": time(row.created_at),
            "actor_id": row.created_by, "reason": row.note or "", "source_type": row.reference_type,
            "source_id": row.reference_id, **({"unit_cost": row.unit_cost} if can("inventory.audit.cost") else {})}
            for row in rows[:limit]]
    else:
        q = StockMovement.query.execution_options(skip_branch_scope=True).filter_by(
            branch_id=line.branch_id, product_id=line.product_id)
        if before_id:
            q = q.filter(StockMovement.id < before_id)
        # Detailed movements persist the existing immutable option selection key.
        if line.variant_name:
            # Source-free aggregate records cannot prove a particular option's movement.
            from sqlalchemy import func
            q = q.filter(func.json_extract(StockMovement.details_json, "$.variant_color") == line.variant_name)
        rows = q.order_by(StockMovement.id.desc()).limit(limit + 1).all()
        from models.inventory_audit import InventoryQuantityAudit
        audits = {audit.movement_id: audit for audit in InventoryQuantityAudit.query.filter(
            InventoryQuantityAudit.movement_id.in_([row.id for row in rows]))}
        items = []
        for row in rows[:limit]:
            audit = audits.get(row.id)
            details = _details(row.details_json)
            before, after = (audit.before_quantity, audit.after_quantity) if audit else (None, None)
            if line.variant_name:
                # Legacy audit balances describe the whole product, not this option.
                before, after = (details.get("expected"), details.get("counted")) if row.source_type == "inventory_count" else (None, None)
            items.append({"id": row.id, "kind": row.movement_type,
                "quantity": row.quantity * (1 if row.direction == "in" else -1),
                "before": before, "after": after,
                "created_at": time(row.created_at), "actor_id": audit.employee_id if audit else None,
                "reason": audit.reason if audit else _details(row.details_json).get("reason", ""),
                "source_type": row.source_type, "source_id": row.source_id,
                **({"unit_cost": row.unit_cost, "total_cost": row.total_cost} if can("inventory.audit.cost") else {})})
    if not can("inventory.audit.system"):
        for item in items:
            item["before"] = item["after"] = None
    # Document references are not a substitute for document-view permission.
    for item in items:
        if item["source_type"] == "invoice" and not can("can_see_orders"):
            item["source_id"] = None
        if item["source_type"] == "purchase" and not can("can_manage_suppliers"):
            item["source_id"] = None
    return {"items": items, "next_before_id": rows[limit - 1].id if len(rows) > limit else None}


def analyze(row, line):
    require("inventory.audit.investigate")
    require("inventory.audit.system")
    if line.counted_quantity is None or line.excluded:
        raise AuditError("عد الصنف أولاً قبل تشغيل التحقيق")
    current, stamp = stock_state(line)
    delta = line.counted_quantity - line.expected_quantity
    counterpart_lines = lines(row).filter(InventoryCountLine.catalog_key == line.catalog_key,
        InventoryCountLine.variant_name == line.variant_name).all()
    comparisons, counterparts, evidence = [], [], []
    complete = True
    for peer in counterpart_lines:
        data = line_data(peer)
        observed = peer.counted_quantity is not None and not peer.excluded and not data["conflict"]
        complete = complete and observed
        comparisons.append({"line_id": peer.id, "location_key": peer.location_key,
            "system_quantity": peer.expected_quantity if observed else peer.baseline_quantity,
            "counted_quantity": peer.counted_quantity, "difference": data["difference"],
            "observed": observed, "conflict": data["conflict"]})
        if peer.id != line.id and observed and delta and data["difference"] and delta * data["difference"] < 0:
            counterparts.append({"line_id": peer.id, "location_key": peer.location_key,
                                 "quantity": min(abs(delta), abs(data["difference"]))})
    if counterparts:
        evidence.append({"kind": "opposite_count", "classification": "possible",
            "message": "يوجد فرق معاكس في موقع آخر؛ تطابق العدد قرينة تحتاج إثبات انتقال، ولا ينشئ تحويلاً تلقائياً",
            "references": counterparts})
    allowed = visible_branches()
    transfers = []
    if line.warehouse_id:
        from modules.wholesale.models.warehouse import Warehouse, WarehouseTransfer, WarehouseTransferLine
        warehouses = Warehouse.query.filter(Warehouse.branch_id.in_(allowed)).with_entities(Warehouse.id)
        q = WarehouseTransfer.query.join(WarehouseTransferLine).filter(
            WarehouseTransferLine.product_id == line.product_id,
            or_(WarehouseTransfer.from_warehouse_id == line.warehouse_id, WarehouseTransfer.to_warehouse_id == line.warehouse_id),
            WarehouseTransfer.from_warehouse_id.in_(warehouses), WarehouseTransfer.to_warehouse_id.in_(warehouses),
            WarehouseTransfer.status.in_(["sent", "approved", "draft"]))
        for transfer in q.order_by(WarehouseTransfer.id.desc()).limit(31):
            transfers.append({"kind": "warehouse_transfer", "id": transfer.id, "number": transfer.transfer_no or str(transfer.id),
                "status": transfer.status, "from_location": f"warehouse:{transfer.from_warehouse_id}",
                "to_location": f"warehouse:{transfer.to_warehouse_id}"})
    else:
        q = StockTransferLine.query.join(StockTransfer).filter(or_(
            StockTransferLine.product_id == line.product_id, StockTransferLine.destination_product_id == line.product_id),
            or_(StockTransfer.from_branch_id == line.branch_id, StockTransfer.to_branch_id == line.branch_id),
            StockTransfer.from_branch_id.in_(allowed), StockTransfer.to_branch_id.in_(allowed),
            StockTransfer.status.in_(["sent", "approved", "draft", "partial"]))
        if line.variant_name:
            q = q.filter(StockTransferLine.variant_color == line.variant_name)
        for transfer_line in q.order_by(StockTransfer.id.desc()).limit(31):
            transfer = transfer_line.transfer
            transfers.append({"kind": "stock_transfer", "id": transfer.id, "number": transfer.transfer_no or str(transfer.id),
                "status": transfer.status, "from_location": f"branch:{transfer.from_branch_id}",
                "to_location": f"branch:{transfer.to_branch_id}", "quantity": transfer_line.quantity,
                "received": transfer_line.quantity_received})
    if transfers:
        evidence.append({"kind": "transfers", "classification": "possible", "references": transfers[:30],
            "message": "توجد تحويلات تحتاج مراجعة الإرسال والاستلام؛ مخزون النقل لا يعد تلقائياً موجوداً على الرف"})
    order_refs, custody_refs, return_refs = [], [], []
    orders_allowed = can("can_see_orders")
    if orders_allowed:
        q = OrderItem.query.join(Invoice).execution_options(skip_branch_scope=True).filter(
            OrderItem.product_id == line.product_id, Invoice.branch_id.in_(allowed))
        if line.warehouse_id:
            q = q.filter(OrderItem.warehouse_id == line.warehouse_id)
        else:
            q = q.filter(OrderItem.warehouse_id.is_(None), or_(OrderItem.fulfillment_branch_id == line.branch_id,
                (OrderItem.fulfillment_branch_id.is_(None) & (Invoice.branch_id == line.branch_id))))
        if line.variant_name:
            q = q.filter(OrderItem.variant_color == line.variant_name)
        items = q.order_by(Invoice.id.desc()).limit(31).all()
        for item in items[:30]:
            invoice = item.invoice
            if line.warehouse_id:
                from modules.wholesale.models.warehouse import WarehouseMovement
                qmove = WarehouseMovement.query.filter_by(warehouse_id=line.warehouse_id, product_id=line.product_id,
                    reference_type="wholesale_sale", reference_id=invoice.id)
                outgoing = qmove.filter(WarehouseMovement.quantity < 0).count()
                incoming = qmove.filter(WarehouseMovement.quantity > 0).count()
            else:
                qmove = StockMovement.query.execution_options(skip_branch_scope=True).filter_by(
                    product_id=line.product_id, branch_id=line.branch_id, source_type="invoice", source_id=invoice.id, source_line_id=item.id)
                outgoing = qmove.filter_by(direction="out").count()
                incoming = qmove.filter_by(direction="in").count()
            ref = {"kind": "invoice", "id": invoice.id, "number": invoice.barcode or str(invoice.id),
                "quantity": item.quantity, "status": invoice.status, "payment_status": invoice.payment_status,
                "stock_deducted": bool(invoice.stock_is_deducted), "outgoing_movements": outgoing,
                "incoming_movements": incoming, "created_at": time(invoice.created_at)}
            order_refs.append(ref)
            if invoice.status in RETURN_STATUSES and outgoing and not incoming:
                return_refs.append(ref)
            if invoice.delivery_agent_id and invoice.status not in CANCELED_STATUSES | {"تم التوصيل"}:
                agent = db.session.get(DeliveryAgent, invoice.delivery_agent_id)
                custody_refs.append({**ref, "agent_id": invoice.delivery_agent_id,
                                    "agent_name": agent.name if agent else str(invoice.delivery_agent_id), "verified_custody": False})
        if order_refs:
            evidence.append({"kind": "orders", "classification": "possible", "references": order_refs,
                "message": "الطلبات مرتبطة بالصنف وحركاته؛ حالة الدفع أو الشحن وحدها لا تثبت موقع القطعة الفعلي"})
        if custody_refs:
            evidence.append({"kind": "couriers", "classification": "possible", "references": custody_refs,
                "message": "توجد طلبات مرتبطة بمندوب؛ لا يوجد في هذا المصدر إيصال عهدة يثبت وجود القطعة عنده، تحقق من التسليم"})
        if return_refs:
            evidence.append({"kind": "returns", "classification": "possible", "references": return_refs,
                "message": "حالة مرتجع دون حركة استلام مرتبطة؛ تحقق هل وصل المرتجع فعلياً قبل تصحيح الرصيد"})
    purchase_refs = []
    purchases_allowed = can("can_manage_suppliers")
    if purchases_allowed:
        q = PurchaseItem.query.join(Purchase).execution_options(skip_branch_scope=True).filter(
            PurchaseItem.product_id == line.product_id, Purchase.branch_id == line.branch_id)
        q = q.filter(Purchase.warehouse_id == line.warehouse_id) if line.warehouse_id else q.filter(Purchase.warehouse_id.is_(None))
        if line.variant_name:
            q = q.filter(PurchaseItem.variant_color == line.variant_name)
        for item in q.order_by(Purchase.id.desc()).limit(31):
            purchase = item.purchase
            purchase_refs.append({"kind": "purchase", "id": purchase.id, "number": purchase.invoice_no or str(purchase.id),
                "quantity": item.quantity, "status": purchase.status, "stock_applied": bool(purchase.stock_applied)})
        if purchase_refs:
            evidence.append({"kind": "purchases", "classification": "possible", "references": purchase_refs[:30],
                "message": "راجع استلام الشراء وموقعه وحركته؛ مسودة الشراء لا تثبت استلام القطعة"})
    conflict = stamp != line.counted_stamp
    return {"classification": "conflict" if conflict else "possible" if evidence else "unexplained" if delta else "matched",
        "message": "تغيّر المخزون بعد العد؛ أعد العد" if conflict else
            "العدد مطابق عند تثبيت العد" if not delta else "توجد قرائن تحتاج تحققاً" if evidence else "لم يتم تحديد سبب الفرق",
        "difference": delta, "system_quantity": line.expected_quantity, "counted_quantity": line.counted_quantity,
        "current_quantity": current, "comparisons": comparisons, "evidence": evidence,
        "company_comparison": {"scope": "session", "complete": complete,
            "system_total": sum(peer.expected_quantity for peer in counterpart_lines) if complete else None,
            "counted_total": sum(peer.counted_quantity for peer in counterpart_lines) if complete else None,
            "net_difference": sum(peer.counted_quantity - peer.expected_quantity for peer in counterpart_lines) if complete else None,
            "note": "المجموع يخص مواقع الجلسة فقط؛ العد مؤرخ لكل موقع، وليس إثبات نقص الشركة أو تحويل مثبت"},
        "coverage": {"locations": "checked" if complete else "incomplete", "transfers": "limited" if len(transfers) > 30 else "checked",
            "orders": "restricted" if not orders_allowed else "checked_recent", "purchases": "restricted" if not purchases_allowed else "checked_recent",
            "courier_custody": "no_signed_custody_registry", "serials": "not_available"},
        "actions": ["recount", "review_source", "request_manager_review"], "auto_transfer": False}


def investigate(row, payload, user):
    if row.status == "posted":
        raise AuditError("الجرد المرحّل محفوظ؛ التحقيق السابق للعرض فقط", "state", 409)
    line = get_line(row, payload.get("line_id"))
    analysis = analyze(row, line)
    _quantity, stamp = stock_state(line)
    line.investigation_json, line.investigation_stamp = dumps(analysis), stamp
    return {"session_id": row.id, "line_id": line.id}, {
        "classification": analysis["classification"], "evidence_kinds": [entry["kind"] for entry in analysis["evidence"]]}


def visible_analysis(stored):
    """A cached manager investigation does not grant access to its source documents."""
    result = json.loads(json.dumps(stored))
    evidence = []
    for entry in result.get("evidence", []):
        if entry["kind"] in ("orders", "couriers", "returns") and not can("can_see_orders"):
            continue
        if entry["kind"] == "purchases" and not can("can_manage_suppliers"):
            continue
        if entry["kind"] == "transfers":
            from .stock import locations
            keys = {location["key"] for kind in ("branch", "warehouse") for location in locations(kind)}
            entry["references"] = [reference for reference in entry["references"]
                                   if reference["from_location"] in keys and reference["to_location"] in keys]
            if not entry["references"]:
                continue
        evidence.append(entry)
    result["evidence"] = evidence
    if not can("can_see_orders"):
        result["coverage"]["orders"] = "restricted"
        result["coverage"]["courier_custody"] = "restricted"
    if not can("can_manage_suppliers"):
        result["coverage"]["purchases"] = "restricted"
    return result
