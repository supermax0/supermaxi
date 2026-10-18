"""Explicitly approved draft in the existing transfer workflow. Never moves stock here."""
from extensions import db
from .common import AuditError, check_version, integer, require, text
from .service import get_line, time
from .stock import stock_state


def draft(row, payload, user):
    require("inventory.audit.review")
    require("inventory.audit.system")
    require("can_manage_inventory")
    require("edit_current_stock")
    if row.status not in ("counting", "pending_review"):
        raise AuditError("راجع التحويل قبل اعتماد الجرد", "state", 409)
    line, target = get_line(row, payload.get("line_id")), get_line(row, payload.get("target_line_id"))
    check_version(line, payload.get("version"))
    if payload.get("acknowledge_draft") is not True:
        raise AuditError("أكد مراجعة المستند؛ تطابق الفرقين وحده لا يثبت التحويل")
    reason = text(payload.get("reason"), required=True)
    quantity = integer(payload.get("quantity"), minimum=1)
    for entry in (line, target):
        if entry.counted_quantity is None or entry.excluded or entry.ticket:
            raise AuditError("ثبّت عد الموقعين أولاً", "state", 409)
        if stock_state(entry, lock=True)[1] != entry.counted_stamp:
            raise AuditError("تغيّر المخزون؛ أعد عد الموقعين قبل إنشاء المستند", "stock_conflict", 409)
    if line.catalog_key != target.catalog_key or line.variant_name != target.variant_name or line.location_key == target.location_key:
        raise AuditError("الموقعان لا يمثلان نفس الصنف والمتغير")
    delta, other_delta = line.counted_quantity - line.expected_quantity, target.counted_quantity - target.expected_quantity
    if not delta or not other_delta or delta * other_delta >= 0 or quantity > min(abs(delta), abs(other_delta)):
        raise AuditError("كمية طلب التحويل لا تطابق الفرقين المعاكسين")
    source, destination = (line, target) if delta < 0 else (target, line)
    from .models import InventoryCountEvent
    import json
    for event in InventoryCountEvent.query.filter_by(session_id=row.id, action="transfer_draft").filter(
            InventoryCountEvent.line_id.in_([line.id, target.id])):
        prior = json.loads(event.detail_json)
        if {event.line_id, prior.get("target_line_id")} != {line.id, target.id}:
            continue
        if row.ledger_kind == "warehouse":
            from modules.wholesale.models.warehouse import WarehouseTransfer
            document = db.session.get(WarehouseTransfer, prior["transfer_id"])
        else:
            from models.branch import StockTransfer
            document = db.session.get(StockTransfer, prior["transfer_id"])
        if document and document.status not in ("cancelled", "canceled"):
            raise AuditError("يوجد مستند تحويل لهذا الفرق؛ راجع المستند السابق قبل إنشاء آخر", "duplicate_transfer", 409)
    note = f"مراجعة جرد {row.number}؛ ليس إثبات انتقال: {reason}. تحقق قبل الإرسال والاستلام ثم أعد العد."
    if row.ledger_kind == "warehouse":
        from modules.wholesale.models.warehouse import WarehouseTransfer, WarehouseTransferLine
        from modules.wholesale.services.warehouse_service import get_stock_row
        if source.product_id != destination.product_id:
            raise AuditError("دفتر المخازن يحتاج نفس معرف الصنف في الطرفين؛ راجع ربط نسخ الكتالوج قبل إنشاء المستند")
        stock = get_stock_row(None, source.warehouse_id, source.product_id)
        if not stock or stock.available_quantity < quantity:
            raise AuditError("الكمية غير المحجوزة لا تكفي لمسودة التحويل؛ راجع حجوزات المخزن")
        transfer = WarehouseTransfer(transfer_no=f"IC-{row.id}-{line.id}-{target.id}",
            from_warehouse_id=source.warehouse_id, to_warehouse_id=destination.warehouse_id,
            status="draft", note=note, created_by_id=user.id)
        db.session.add(transfer)
        db.session.flush()
        db.session.add(WarehouseTransferLine(transfer_id=transfer.id, product_id=source.product_id, quantity=quantity))
    else:
        from models.branch import StockTransfer, StockTransferLine
        from models.product import Product
        from routes.stock_transfers import _next_transfer_no, _validate_transfer_line
        product = Product.query.execution_options(skip_branch_scope=True).filter_by(id=source.product_id).one()
        error = _validate_transfer_line(product, quantity, source.variant_name or None, source.branch_id)
        if error:
            raise AuditError(error)
        transfer = StockTransfer(transfer_no=_next_transfer_no(), from_branch_id=source.branch_id,
            to_branch_id=destination.branch_id, status="draft", note=note, created_by_id=user.id)
        db.session.add(transfer)
        db.session.flush()
        db.session.add(StockTransferLine(transfer_id=transfer.id, product_id=source.product_id,
            destination_product_id=destination.product_id, variant_color=source.variant_name or None, quantity=quantity))
    return {"session_id": row.id, "line_id": line.id, "transfer_id": transfer.id, "transfer_kind": row.ledger_kind}, {
        "target_line_id": target.id, "transfer_id": transfer.id, "transfer_kind": row.ledger_kind,
        "quantity": quantity, "reason": reason, "stock_changed": False, "counted_at": time(line.counted_at)}
