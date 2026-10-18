"""Atomic approved stock adjustments, valuation layers and non-cash journals."""
from datetime import datetime
from uuid import uuid4

from extensions import db
from models.inventory_audit import InventoryQuantityAudit
from models.inventory_lot import InventoryLot
from models.journal_entry import JournalEntry
from models.product import Product
from modules.finance import ledger
from modules.finance.common import today
from utils.branch_stock_service import adjust_branch_stock
from utils.financial_period_guard import assert_date_period_open
from utils.inventory_lots import _lot_query, _create_fallback_lot, ensure_inventory_lot_schema
from utils.product_color_service import adjust_color_stock
from utils.stock_movement_guard import claim_stock_movement
from .common import AuditError, check_version, require
from .service import validate_counts, time
from .stock import product_data, stock_state


def valuation(line, delta):
    """Mirror the established order FIFO + uncovered legacy cost fallback."""
    unit_cost = product_data(line, show_cost=True)["unit_cost"]
    if line.warehouse_id:
        return abs(delta) * unit_cost, [{"kind": "warehouse_unit_cost", "quantity": delta, "unit_cost": unit_cost}]
    ensure_inventory_lot_schema()
    color = line.variant_name or None
    if delta > 0:
        lot = _create_fallback_lot(line.product_id, delta, line.branch_id, color, unit_cost)
        return delta * unit_cost, [{"lot_id": lot.id, "quantity": delta, "unit_cost": unit_cost}]
    remaining, total, layers = -delta, 0, []
    lots = _lot_query(line.product_id, line.branch_id, color).with_for_update().populate_existing().all()
    if sum(int(lot.remaining_quantity) for lot in lots) > line.expected_quantity:
        raise AuditError("طبقات التكلفة تتجاوز رصيد الموقع؛ راجع التقييم قبل ترحيل الجرد", "valuation_conflict", 409)
    for lot in lots:
        take = min(remaining, int(lot.remaining_quantity))
        if not take:
            continue
        lot.remaining_quantity -= take
        total += take * int(lot.unit_cost)
        layers.append({"lot_id": lot.id, "quantity": -take, "unit_cost": int(lot.unit_cost)})
        remaining -= take
        if not remaining:
            break
    if remaining:
        lot = _create_fallback_lot(line.product_id, remaining, line.branch_id, color, unit_cost)
        lot.remaining_quantity = 0
        total += remaining * unit_cost
        layers.append({"lot_id": lot.id, "quantity": -remaining, "unit_cost": unit_cost, "legacy_fallback": True})
    return total, layers


def post(row, payload, user):
    require("inventory.audit.post")
    require("inventory.audit.system")
    require("edit_current_stock")
    require("finance.approve")
    check_version(row, payload.get("version"))
    if row.status != "approved" or not row.approved_by or not row.approved_at:
        raise AuditError("اعتمد الجرد أولاً قبل ترحيل أي تسوية", "state", 409)
    assert_date_period_open(today(), "ترحيل تسوية الجرد")
    counted = validate_counts(row, approval=True)
    reconcile = payload.get("reconcile_valuation", False)
    if not isinstance(reconcile, bool):
        raise AuditError("تأكيد مطابقة التقييم غير صالح")
    from models.branch import BranchStock
    from utils.desktop_stock_reservations import reserved_for_stock
    for line in counted:
        if line.warehouse_id:
            from modules.wholesale.models.warehouse import WarehouseStock
            stock = WarehouseStock.query.filter_by(warehouse_id=line.warehouse_id, product_id=line.product_id).first()
            if stock and line.counted_quantity < stock.reserved_quantity:
                raise AuditError("الموجود الفعلي أقل من المحجوز؛ راجع حجوزات المخزن قبل التسوية", "reserved_stock", 409)
        elif line.counted_quantity != line.expected_quantity or reconcile:
            stock = BranchStock.query.filter_by(branch_id=line.branch_id, product_id=line.product_id).first()
            if stock and reserved_for_stock(stock.id, line.variant_id if line.variant_id else None):
                raise AuditError("توجد حصة جهاز Offline قائمة لهذا الصنف؛ زامن المبيعات وأعد الحصة ثم أعد العد قبل التسوية", "offline_escrow", 409)
    inventory, loss_account, surplus_account = ledger.account("inventory"), ledger.account("inventory_loss"), ledger.account("inventory_surplus")
    if inventory.account_type != "asset" or loss_account.account_type != "expense" or surplus_account.account_type != "revenue" or len({inventory.id, loss_account.id, surplus_account.id}) != 3:
        raise AuditError("ربط حسابات تسوية الجرد غير صالح؛ راجع إعدادات الحسابات")
    basis = None
    if reconcile:
        from .valuation_basis import apply
        basis = apply(counted, payload)
        db.session.flush()
    changes = []
    # All counts/stamps are validated and rows locked before any sibling option moves.
    for line in counted:
        delta = line.counted_quantity - line.expected_quantity
        if line.posted_delta is not None:
            raise AuditError("سطر الجرد مرحّل مسبقاً", "already_posted", 409)
        line.posted_delta = delta
        if not delta:
            line.posted_cost = 0
            continue
        cost, layers = valuation(line, delta)
        reason = f"{row.number} — {line.resolution_note}"
        if line.warehouse_id:
            from modules.wholesale.services.warehouse_service import apply_movement
            from modules.wholesale.models.warehouse import WarehouseMovement
            product = Product.query.execution_options(skip_branch_scope=True).filter_by(id=line.product_id).first()
            apply_movement(product.tenant_id, warehouse_id=line.warehouse_id, product_id=line.product_id,
                quantity_delta=delta, movement_type="count", reference_type="inventory_count", reference_id=line.id,
                unit_cost=(cost // abs(delta)), note=reason, created_by=user.id)
            movement = WarehouseMovement.query.filter_by(warehouse_id=line.warehouse_id, product_id=line.product_id,
                reference_type="inventory_count", reference_id=line.id).one()
        else:
            claim = claim_stock_movement(f"inventory-count:{row.id}:line:{line.id}:post",
                movement_type="inventory_count_adjustment", direction="in" if delta > 0 else "out",
                product_id=line.product_id, branch_id=line.branch_id, quantity=abs(delta), unit_cost=cost // abs(delta),
                source_type="inventory_count", source_id=row.id, source_line_id=line.id,
                details={"variant_color": line.variant_name or None, "reason": reason,
                         "counted_at": time(line.counted_at), "expected": line.expected_quantity,
                         "counted": line.counted_quantity, "valuation_layers": layers, "exact_total_cost": cost})
            if not claim.applied:
                raise AuditError("حركة الجرد موجودة دون حالة ترحيل متوافقة؛ راجع السجل", "already_posted", 409)
            movement = claim.movement
            # FIFO's exact total is authoritative when mixed layer prices do not
            # divide to an integer average. The layers retain each exact price.
            movement.total_cost = cost
            if line.variant_id:
                adjust_color_stock(line.product_id, line.variant_name, delta, branch_id=line.branch_id)
            else:
                adjust_branch_stock(line.branch_id, line.product_id, delta, audit_context={
                    "source_type": "inventory_count", "source_id": row.id, "source_line_id": line.id,
                    "unit_cost": cost // abs(delta), "reason": reason})
            db.session.flush()
            # Observe the exact option/on-hand row, rather than relying on the
            # legacy helper's aggregate mirror (which may already be stale).
            actual, _stamp = stock_state(line, lock=True)
            if actual != line.counted_quantity:
                raise AuditError("لم يتطابق الرصيد الفعلي مع العد؛ لم تحفظ التسوية", "stock_conflict", 409)
            audit = InventoryQuantityAudit.query.execution_options(skip_branch_scope=True).filter_by(movement_id=movement.id).first()
            if not audit:
                # This is mandatory evidence measured inside this transaction;
                # unlike legacy best-effort auditing an insert error propagates.
                audit = InventoryQuantityAudit(event_key=uuid4().hex, movement_id=movement.id,
                    product_id=line.product_id, branch_id=line.branch_id,
                    operation="inventory_count_variant" if line.variant_id else "inventory_count",
                    before_quantity=line.expected_quantity, delta_quantity=delta, after_quantity=actual,
                    source_type="inventory_count", source_id=row.id, source_line_id=line.id)
                audit.set_metadata({"variant_id":line.variant_id, "variant_name":line.variant_name,
                                    "counted_at":time(line.counted_at), "measured_after":actual})
                db.session.add(audit)
            audit.reason, audit.employee_id, audit.employee_name = reason, user.id, user.name
            db.session.flush()
        line.movement_id, line.posted_cost = movement.id, cost
        if cost:
            entry = JournalEntry(entry_number=f"IC-{row.id}-{line.id}", reference_type="inventory_count",
                reference_id=row.id, description=reason,
                debit_account_id=inventory.id if delta > 0 else loss_account.id,
                credit_account_id=surplus_account.id if delta > 0 else inventory.id,
                amount=cost, entry_date=datetime.combine(today(), datetime.min.time()), created_by=user.id)
            db.session.add(entry)
            db.session.flush()
            line.journal_entry_id = entry.id
        changes.append({"line_id": line.id, "difference": delta, "cost": cost,
                        "movement_id": line.movement_id, "journal_entry_id": line.journal_entry_id, "valuation_layers": layers})
    if reconcile:
        db.session.flush()
        for line in counted:
            quantity = sum(int(lot.remaining_quantity) for lot in
                _lot_query(line.product_id, line.branch_id, line.variant_name or None).all())
            if quantity != line.counted_quantity:
                raise AuditError("لم تتطابق طبقات التكلفة مع العد النهائي؛ لم تحفظ التسوية", "valuation_conflict", 409)
    # Finish all line writes while the session is still approved. The posted
    # session's DB triggers then seal the entire result, including uncounted rows.
    db.session.flush()
    row.status, row.posted_by, row.posted_at = "posted", user.id, datetime.utcnow()
    row.version += 1
    return {"session_id": row.id, "version": row.version}, {
        "changes": changes, "non_cash": True, "valuation_reconciliation": basis}
