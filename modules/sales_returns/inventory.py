"""Flush-only physical receipt from validated original-sale allocations."""
from datetime import datetime
from flask import g
from extensions import db
from models.inventory_lot import InventoryLot
from models.product import Product
from utils.branch_product_service import product_for_branch
from utils.branch_stock_service import receive_stock
from utils.branch_mode import independent_branches_enabled
from utils.product_color_service import restore_color_stock
from utils.stock_movement_guard import claim_stock_movement
from modules.inventory_locations.lots import attach, validate_location
from .models import SalesReturnCost, ReturnEvidenceError


def restore_line(document, line, source, proposal):
    if not db.session.info.get("sales_return_atomic"):
        raise ReturnEvidenceError("استلام المرتجع يلزم أن يكون داخل عملية كاملة ذرية")
    if document.tenant_key != getattr(g, "tenant", None) or line.document_id != document.id:
        raise ReturnEvidenceError("دليل الاستلام لا يخص الشركة أو المستند الحالي")
    if source["id"] != line.order_item_id or proposal["id"] != line.order_item_id:
        raise ReturnEvidenceError("تخصيص الاستلام لا يخص سطر الأصل")
    if proposal["quantity"] != line.quantity or proposal["cost"] != line.cost_amount:
        raise ReturnEvidenceError("قيمة أو كمية الاستلام تختلف عن المعاينة المعتمدة")
    validate_location(document.branch_id, document.return_location_id)
    product = Product.query.execution_options(skip_branch_scope=True).get(source["product_id"])
    if product is None:
        raise ReturnEvidenceError("صنف الأصل غير موجود؛ يلزم ربط الصنف قبل الاستلام")
    if independent_branches_enabled():
        product = product_for_branch(product, document.branch_id)
    key = f"sales-return:{document.id}:line:{line.id}"
    claim = claim_stock_movement(key, movement_type="sales_return", direction="in",
        product_id=product.id, branch_id=document.branch_id, quantity=line.quantity,
        unit_cost=line.cost_amount // line.quantity, source_type="sales_return", source_id=document.id,
        source_line_id=line.id, details={"invoice_id": document.invoice_id,
            "order_item_id": line.order_item_id, "location_id": document.return_location_id,
            "variant": source["variant"]})
    if not claim.applied:
        return
    claim.movement.total_cost = line.cost_amount
    originals = {row["id"]: row for row in source["cost_layers"]}
    parts = proposal["portions"] or [{"layer_id": None, "lot_id": None,
        "quantity": line.quantity, "unit_cost": source["saved_unit_cost"]}]
    if sum(part["quantity"] for part in parts) != line.quantity or sum(
            part["quantity"] * part["unit_cost"] for part in parts) != line.cost_amount:
        raise ReturnEvidenceError("تخصيص الكلفة لا يغطي الاستلام؛ لم تنشأ دفعة بديلة")
    for part in parts:
        original = originals.get(part["layer_id"])
        if part["layer_id"] is not None and original is None:
            raise ReturnEvidenceError("طبقة الكلفة لا تخص دليل الأصل")
        if original and (part["lot_id"] != original["lot_id"] or part["unit_cost"] != original["unit_cost"]):
            raise ReturnEvidenceError("دفعة أو سعر الكلفة لا يطابق دليل الأصل")
        if not original and (part["lot_id"] is not None or part["unit_cost"] != source["saved_unit_cost"]):
            raise ReturnEvidenceError("كلفة البند القديم لا تطابق دليله المحفوظ")
        received_at = datetime.fromisoformat(original["received_at"]) if original and original["received_at"] else None
        lot = InventoryLot(product_id=product.id, branch_id=document.branch_id,
            variant_color=source["variant"] or None, quantity=part["quantity"],
            remaining_quantity=part["quantity"], unit_cost=part["unit_cost"])
        if received_at:
            lot.created_at = received_at
        db.session.add(lot)
        db.session.flush()
        attach(lot, document.return_location_id)
        db.session.add(SalesReturnCost(line_id=line.id, original_layer_id=part["layer_id"],
            original_lot_id=part["lot_id"], restored_lot_id=lot.id, quantity=part["quantity"],
            unit_cost=part["unit_cost"], original_received_at=received_at,
            cost_basis=original["basis"] if original else "saved_line_cost"))
    receive_stock(document.branch_id, product.id, line.quantity, audit_context={
        "movement_id": claim.movement.id, "operation": "sales_return", "source_type": "sales_return",
        "source_id": document.id, "source_line_id": line.id,
        "metadata": {"invoice_id": document.invoice_id, "location_id": document.return_location_id}})
    if source["variant"]:
        restore_color_stock(product.id, source["variant"], line.quantity, branch_id=document.branch_id)
    db.session.flush()
