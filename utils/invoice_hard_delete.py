"""Transactional hard-delete for sales invoices and their operational effects."""
from __future__ import annotations

import json

from extensions import db
from sqlalchemy import inspect


def _table_exists(model) -> bool:
    try:
        # Inspect through the active transaction. Opening a second inspector
        # connection can roll back the current transaction on in-memory
        # SQLite, whose pool may hand out the same underlying connection.
        return model.__table__.name in inspect(db.session.connection()).get_table_names()
    except Exception:
        return False


def _remove_invoice_from_saved_reports(invoice_id: int) -> None:
    from models.report import Report
    from models.shipping_report import ShippingReport

    def row_invoice_id(row):
        if not isinstance(row, dict):
            return None
        for key in ("invoice_id", "order_id", "id"):
            try:
                value = int(row.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value:
                return value
        return None

    for model in (Report, ShippingReport):
        if not _table_exists(model):
            continue
        for report in model.query.filter(model.orders_data.isnot(None)).all():
            try:
                rows = json.loads(report.orders_data or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(rows, list):
                continue
            kept = [row for row in rows if row_invoice_id(row) != int(invoice_id)]
            if len(kept) == len(rows):
                continue
            report.orders_data = json.dumps(kept, ensure_ascii=False)
            report.orders_count = len(kept)
            total = 0
            for row in kept:
                if not isinstance(row, dict):
                    continue
                for key in ("total", "amount", "total_amount"):
                    try:
                        if row.get(key) is not None:
                            total += int(row.get(key) or 0)
                            break
                    except (TypeError, ValueError):
                        continue
            report.total_amount = total
            if isinstance(report, ShippingReport) and report.order_status_selections:
                try:
                    selections = json.loads(report.order_status_selections)
                    if isinstance(selections, dict):
                        selections.pop(str(invoice_id), None)
                        selections.pop(invoice_id, None)
                        report.order_status_selections = json.dumps(
                            selections, ensure_ascii=False
                        )
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass


def hard_delete_invoice(invoice, *, allow_paid_commission: bool = False) -> dict:
    """Remove one invoice and reverse every in-scope stock/accounting effect.

    This function is flush-only.  The HTTP route owns commit/rollback and the
    activity log, so all cleanup either succeeds together or is fully rolled
    back.
    """
    from models.beauty_appointment import BeautyAppointment
    from models.customer_credit import (
        CustomerCreditPayment,
        CustomerCreditPlan,
        CustomerInstallment,
    )
    from models.inventory_lot import OrderItemCostLayer
    from models.inventory_audit import InventoryQuantityAudit
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.journal_entry import JournalEntry
    from models.order_item import OrderItem
    from models.pos_ai_log import POSAILog
    from models.shipping_payment import ShippingPayment
    from models.stock_movement import StockMovement
    from models.trade_in_receipt import TradeInReceipt
    from utils.delivery_expense_service import remove_delivery_expense_for_invoice
    from utils.order_lifecycle import restore_order_stock_once
    from utils.payroll_service import remove_commission_lines_for_deleted_invoice
    from utils.trade_in_service import reverse_trade_in_receipt

    from modules.sales_returns.facts import documents
    linked_returns = documents(invoice.id)
    if linked_returns is not None and linked_returns.first() is not None:
        raise ValueError("الفاتورة مرتبطة بمرتجع معتمد؛ لا يمكن حذف أصل البيع أو مصادر تحصيله")
    invoice_id = int(invoice.id)
    removed_food_snapshots = 0

    # A paid exchange invoice may have added the customer's old item to stock.
    # Take it back out before removing the receipt row.
    receipts = TradeInReceipt.query.filter_by(invoice_id=invoice_id).all()
    for receipt in receipts:
        if receipt.status == "received":
            reverse_trade_in_receipt(receipt)
        db.session.delete(receipt)

    restored_stock = bool(restore_order_stock_once(invoice))
    remove_delivery_expense_for_invoice(invoice_id)
    removed_commissions = remove_commission_lines_for_deleted_invoice(
        invoice_id,
        allow_paid=allow_paid_commission,
    )

    removed_shipping_payments = ShippingPayment.query.filter_by(
        invoice_id=invoice_id
    ).delete(synchronize_session=False)
    removed_ledger_rows = InvoicePaymentLedger.query.filter_by(
        invoice_id=invoice_id
    ).delete(synchronize_session=False)

    # Installment payments allocated specifically to this invoice are part of
    # its financial trace; remove them before deleting the plans/installments.
    plans = CustomerCreditPlan.query.filter_by(invoice_id=invoice_id).all()
    for plan in plans:
        CustomerCreditPayment.query.filter_by(plan_id=plan.id).delete(
            synchronize_session=False
        )
        CustomerInstallment.query.filter_by(plan_id=plan.id).delete(
            synchronize_session=False
        )
        db.session.delete(plan)

    if _table_exists(JournalEntry):
        JournalEntry.query.filter(
            JournalEntry.reference_id == invoice_id,
            JournalEntry.reference_type.in_(("invoice", "invoice_payment")),
        ).delete(synchronize_session=False)
    if _table_exists(POSAILog):
        POSAILog.query.filter_by(invoice_id=invoice_id).delete(synchronize_session=False)
    if _table_exists(BeautyAppointment):
        BeautyAppointment.query.filter_by(invoice_id=invoice_id).update(
            {BeautyAppointment.invoice_id: None},
            synchronize_session=False,
        )

    # Query ids directly: an invoice relationship loaded before new lines were
    # flushed can legitimately be stale inside the same transaction.
    item_ids = [
        int(row[0])
        for row in db.session.query(OrderItem.id).filter_by(invoice_id=invoice_id).all()
    ]
    if item_ids:
        OrderItemCostLayer.query.filter(
            OrderItemCostLayer.order_item_id.in_(item_ids)
        ).delete(synchronize_session=False)

    from modules.food.models import (
        FoodInventoryMovement,
        FoodSaleBatchAllocation,
        FoodSaleItemSnapshot,
    )

    if str(getattr(invoice, "source_module", "") or "").lower() == "food":
        # Food snapshots reference order items and must be removed explicitly
        # before the core invoice cascade. Ordinary cancellation keeps them.
        food_snapshot_rows = FoodSaleItemSnapshot.query.join(
                OrderItem, OrderItem.id == FoodSaleItemSnapshot.order_item_id
            ).filter(OrderItem.invoice_id == invoice_id).all()
        snapshot_ids = [int(row.id) for row in food_snapshot_rows]
        allocation_rows = FoodSaleBatchAllocation.query.filter(
            FoodSaleBatchAllocation.sale_snapshot_id.in_(snapshot_ids or [-1])
        ).all()
        movement_rows = FoodInventoryMovement.query.filter_by(
            reference_type="invoice",
            reference_id=invoice_id,
        ).all()
        if allocation_rows:
            db.session.execute(
                FoodSaleBatchAllocation.__table__.delete().where(
                    FoodSaleBatchAllocation.id.in_([row.id for row in allocation_rows])
                )
            )
        if snapshot_ids:
            delete_result = db.session.execute(
                FoodSaleItemSnapshot.__table__.delete().where(
                    FoodSaleItemSnapshot.id.in_(snapshot_ids)
                )
            )
            removed_food_snapshots = int(delete_result.rowcount or 0)
        if movement_rows:
            db.session.execute(
                FoodInventoryMovement.__table__.delete().where(
                    FoodInventoryMovement.id.in_([row.id for row in movement_rows])
                )
            )
        # Core deletes intentionally bypass ORM cascades. Detach any loaded
        # food history objects so a later flush cannot try to persist them.
        for loaded in [*allocation_rows, *food_snapshot_rows, *movement_rows]:
            if inspect(loaded).persistent:
                db.session.expunge(loaded)
        db.session.flush()

    # The inventory quantities were restored above.  Removing the immutable
    # rows is intentional for a hard delete and also prevents SQLite id reuse
    # from colliding with old movement keys.
    movement_query = StockMovement.query.filter_by(
        source_type="invoice",
        source_id=invoice_id,
    )
    movement_ids = [int(row[0]) for row in movement_query.with_entities(StockMovement.id).all()]
    if _table_exists(InventoryQuantityAudit):
        audit_filter = db.or_(
            db.and_(
                InventoryQuantityAudit.source_type == "invoice",
                InventoryQuantityAudit.source_id == invoice_id,
            ),
            InventoryQuantityAudit.movement_id.in_(movement_ids or [-1]),
        )
        InventoryQuantityAudit.query.filter(audit_filter).delete(
            synchronize_session=False
        )
        db.session.flush()
    # Some migrated SQLite databases enforce a self-FK from reversal_of_key to
    # movement_key.  Detach the reversal links before removing both sides.
    movement_query.update(
        {StockMovement.reversal_of_key: None},
        synchronize_session=False,
    )
    db.session.flush()
    movement_query.delete(synchronize_session=False)
    _remove_invoice_from_saved_reports(invoice_id)

    db.session.delete(invoice)
    db.session.flush()
    return {
        "restored_stock": restored_stock,
        "removed_ledger_rows": int(removed_ledger_rows or 0),
        "removed_shipping_payments": int(removed_shipping_payments or 0),
        "removed_commissions": int(removed_commissions or 0),
        "removed_credit_plans": len(plans),
        "removed_food_snapshots": int(removed_food_snapshots or 0),
    }
