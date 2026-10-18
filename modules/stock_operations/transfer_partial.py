"""Branch transfers — approval, partial receipt and residual resolution (multi-branch spec, phase 8).

The proven send / full-receive / cancel engine in ``transfers.py`` is left untouched. This module adds:

* ``approve``          draft → approved (only enforced when the company requires approval),
* ``receive_partial``  sent → received | partially_received, per-line quantities taken from the ORIGINAL FIFO
                       layers in order, so cost is carried exactly as in a full receipt,
* ``resolve``          partially_received → received: each remaining quantity is either «late» (arrived later,
                       received at the destination), «return» (goes back to the source's own lots) or «loss»
                       (received at the destination and immediately written off through the stock write-off
                       service, which posts the inventory-loss journal),
* ``reject``           sent → rejected: the receiver refuses, everything returns to the source (reuses the
                       existing cancel movements).

Stock and money never move except through the same primitives the full flow uses: ``claim_stock_movement``
(idempotent keys), ``receive_stock`` and FIFO cost layers. Goods not yet settled stay owned by the sender
(``in_transit_value``).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import update

from extensions import db
from models.branch import StockTransfer, StockTransferLine
from models.inventory_lot import InventoryLot
from models.product import Product
from models.stock_operations import StockTransferCostLayer
from utils.inventory_transfer_valuation import TransferValuationError

from .common import AuditError

APPROVAL_FLAG = "transfer_approval_required"
RECEIVE_PHASES = ("receive", "late")
OPEN_STATUSES = ("sent", "partially_received")


# ───────────────────────────── policy ─────────────────────────────


def approval_required() -> bool:
    try:
        from models.system_settings import SystemSettings

        return bool(SystemSettings.get_settings().get_ui_flags().get(APPROVAL_FLAG))
    except Exception:
        return False


def set_approval_required(enabled: bool) -> bool:
    from models.system_settings import SystemSettings

    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    flags[APPROVAL_FLAG] = bool(enabled)
    settings.set_ui_flags(flags)
    settings.updated_at = datetime.utcnow()
    db.session.add(settings)
    return bool(enabled)


# ───────────────────────────── layer arithmetic ─────────────────────────────


def _rows(transfer_id: int, line_id: int) -> list[StockTransferCostLayer]:
    return (StockTransferCostLayer.query.execution_options(skip_branch_scope=True)
            .filter_by(transfer_kind="branch", transfer_id=transfer_id, line_id=line_id).all())


def line_state(transfer_id: int, line_id: int) -> dict[str, Any]:
    """Sent / received / returned / still-in-transit quantities for one line, derived from the layers."""
    rows = _rows(transfer_id, line_id)
    sent = sum(r.quantity for r in rows if r.phase == "send")
    received = sum(r.quantity for r in rows if r.phase in RECEIVE_PHASES)
    returned = sum(r.quantity for r in rows if r.phase in ("return", "cancel"))
    return {"has_layers": sent > 0, "sent": sent, "received": received, "returned": returned,
            "residual": max(sent - received - returned, 0)}


def _take(transfer_id: int, line_id: int, quantity: int) -> list[tuple[StockTransferCostLayer, int]]:
    """Walk the original layers in FIFO order and take ``quantity`` from what is still unsettled."""
    rows = _rows(transfer_id, line_id)
    used: dict[int, int] = {}
    for row in rows:
        if row.phase != "send":
            used[row.sequence] = used.get(row.sequence, 0) + row.quantity
    remaining, taken = quantity, []
    for layer in sorted((r for r in rows if r.phase == "send"), key=lambda r: r.sequence):
        free = layer.quantity - used.get(layer.sequence, 0)
        if free <= 0:
            continue
        part = min(free, remaining)
        taken.append((layer, part))
        remaining -= part
        if not remaining:
            break
    if remaining:
        raise TransferValuationError("الكمية المطلوبة أكبر من المتبقي بالطريق")
    return taken


# ───────────────────────────── one line, one phase ─────────────────────────────


def _settle_line(transfer: StockTransfer, line: StockTransferLine, quantity: int, phase: str) -> int:
    """Settle ``quantity`` of a line in ``phase`` (receive | late | return). Returns the exact cost moved."""
    from routes.stock_transfers import _branch_color_product_id
    from utils.branch_product_service import product_for_branch
    from utils.branch_stock_service import get_branch_stock, receive_stock
    from utils.product_color_service import receive_color_stock
    from utils.stock_movement_guard import claim_stock_movement

    product = (Product.query.execution_options(skip_branch_scope=True).filter_by(id=line.product_id).first())
    if product is None:
        raise TransferValuationError("المنتج غير موجود؛ راجع التحويل")
    state = line_state(transfer.id, line.id)
    if not state["has_layers"]:
        raise TransferValuationError("هذا تحويل قديم بلا كلفة نقل موثقة؛ لا يدعم الاستلام الجزئي")
    parts = _take(transfer.id, line.id, quantity)
    exact = sum(n * layer.unit_cost for layer, n in parts)
    color = (line.variant_color or "").strip() or None
    receiving = phase in RECEIVE_PHASES
    branch_id = transfer.to_branch_id if receiving else transfer.from_branch_id
    destination = product
    if receiving and hasattr(product, "catalog_group_id"):
        destination = product_for_branch(product, transfer.to_branch_id)
        line.destination_product_id = destination.id
    movement_product_id = destination.id if receiving else line.product_id

    claim = claim_stock_movement(
        f"transfer:{transfer.id}:line:{line.id}:{phase}",
        movement_type="transfer_receive" if receiving else "transfer_cancel",
        direction="in", product_id=movement_product_id, branch_id=branch_id, quantity=quantity,
        unit_cost=exact // quantity, source_type="stock_transfer", source_id=transfer.id, source_line_id=line.id,
        details={"from_branch_id": transfer.from_branch_id, "to_branch_id": transfer.to_branch_id,
                 "variant_color": color, "partial_phase": phase,
                 "valuation_layers": [{"lot_id": layer.lot_id, "quantity": n, "unit_cost": layer.unit_cost}
                                      for layer, n in parts]},
    )
    if not claim.applied:
        return exact  # exact replay of the same operation: nothing to repeat
    claim.movement.total_cost = exact

    for layer, n in parts:
        origin = db.session.get(InventoryLot, layer.lot_id)
        if origin is None:
            raise TransferValuationError("دفعة الكلفة الأصلية غير موجودة؛ راجع التحويل")
        if receiving:
            lot = InventoryLot(product_id=destination.id, branch_id=transfer.to_branch_id, variant_color=color,
                               quantity=n, remaining_quantity=n, unit_cost=layer.unit_cost,
                               created_at=origin.created_at)
            db.session.add(lot)
            db.session.flush()
        else:
            if origin.branch_id != transfer.from_branch_id or origin.product_id != layer.product_id:
                raise TransferValuationError("مصدر الكلفة تغير؛ لم تُعَد الكمية")
            if origin.remaining_quantity + n > origin.quantity:
                raise TransferValuationError("طبقات المصدر تغيرت بعد الإرسال؛ راجع التقييم")
            changed = db.session.execute(
                update(InventoryLot).where(InventoryLot.id == origin.id,
                                           InventoryLot.remaining_quantity == origin.remaining_quantity)
                .values(remaining_quantity=InventoryLot.remaining_quantity + n)
                .execution_options(synchronize_session=False))
            if changed.rowcount != 1:
                raise TransferValuationError("تغيرت طبقات المصدر؛ حدّث السند")
            db.session.expire(origin)
            lot = origin
        db.session.add(StockTransferCostLayer(
            transfer_kind="branch", transfer_id=transfer.id, line_id=line.id, phase=phase,
            sequence=layer.sequence, branch_id=branch_id, product_id=lot.product_id, lot_id=lot.id,
            quantity=n, unit_cost=layer.unit_cost))
    db.session.flush()

    receive_stock(branch_id, movement_product_id, quantity)
    if color and hasattr(destination, "catalog_group_id"):
        color_product = _branch_color_product_id(branch_id, movement_product_id, color)
        receive_color_stock(color_product, color, quantity, branch_id=branch_id)
    if hasattr(destination, "catalog_group_id"):
        target = destination if receiving else product
        target.quantity = get_branch_stock(branch_id, movement_product_id)
    return exact


# ───────────────────────────── public operations ─────────────────────────────


def _claim_status(transfer: StockTransfer, allowed: set[str], target: str) -> None:
    from utils.stock_transfer_state import transition

    try:
        transition(transfer, allowed, target)
    except ValueError as exc:
        raise AuditError(str(exc), "conflict", 409) from None


def approve(transfer: StockTransfer, user) -> None:
    _claim_status(transfer, {"draft"}, "approved")
    transfer.note = transfer.note  # status only; the approver is recorded in the operation audit


def receive_partial(transfer: StockTransfer, quantities: dict[int, int], user) -> str:
    """Receive what actually arrived. Returns the new status."""
    by_id = {line.id: line for line in transfer.lines}
    plan: dict[int, int] = {}
    for line_id, raw in quantities.items():
        line = by_id.get(int(line_id))
        if line is None:
            raise AuditError("بند غير موجود في التحويل", "validation", 400)
        qty = int(raw)
        if qty < 0 or qty > int(line.quantity):
            raise AuditError(f"الكمية المستلمة يجب أن تكون بين 0 و{int(line.quantity)}", "validation", 400)
        plan[line.id] = qty
    if not any(plan.values()):
        raise AuditError("أدخل كمية مستلمة لصنف واحد على الأقل — أو ارفض التحويل", "validation", 400)
    complete = all(plan.get(line.id, 0) == int(line.quantity) for line in transfer.lines)
    target = "received" if complete else "partially_received"
    _claim_status(transfer, {"sent"}, target)
    for line in transfer.lines:
        qty = plan.get(line.id, 0)
        if qty:
            _settle_line(transfer, line, qty, "receive")
        line.quantity_received = qty
    if complete:
        transfer.received_at = datetime.utcnow()
        transfer.received_by_id = user.id
    return target


def residual_lines(transfer: StockTransfer) -> list[tuple[StockTransferLine, int]]:
    out = []
    for line in transfer.lines:
        state = line_state(transfer.id, line.id)
        if state["residual"] > 0:
            out.append((line, state["residual"]))
    return out


def resolve(transfer: StockTransfer, plan: dict[int, str], user, reason: str, write_off) -> list[dict[str, Any]]:
    """Decide the fate of every remaining quantity. ``write_off(transfer, line, qty, reason)`` posts the loss."""
    pending = residual_lines(transfer)
    if not pending:
        raise AuditError("لا توجد كميات متبقية بالطريق", "conflict", 409)
    missing = [line.id for line, _ in pending if plan.get(line.id) not in ("late", "return", "loss")]
    if missing:
        raise AuditError("حدّد مصير كل كمية متبقية: وصلت متأخرة / تُعاد للمصدر / فاقد", "validation", 400)
    _claim_status(transfer, {"partially_received"}, "received")
    report = []
    for line, quantity in pending:
        action = plan[line.id]
        if action == "return":
            _settle_line(transfer, line, quantity, "return")
        else:
            _settle_line(transfer, line, quantity, "late")
            line.quantity_received = int(line.quantity_received or 0) + quantity
            if action == "loss":
                report.append({"line_id": line.id, "writeoff": write_off(transfer, line, quantity, reason)})
        report.append({"line_id": line.id, "action": action, "quantity": quantity})
    transfer.received_at = datetime.utcnow()
    transfer.received_by_id = user.id
    return report


def reject(transfer: StockTransfer, user) -> None:
    """Receiver refuses the whole parcel: same movements as a cancel, different final status."""
    from routes.stock_transfers import _apply_transfer_movements

    _claim_status(transfer, {"sent"}, "rejected")
    _apply_transfer_movements(transfer, "cancel")


# ───────────────────────────── loss + dispatcher ─────────────────────────────


def post_loss(transfer: StockTransfer, line: StockTransferLine, quantity: int, reason: str, user) -> str:
    """Goods lost / damaged in transit: received at the destination, then written off with the stock
    write-off service — one auditable document and one inventory-loss journal. As for every write-off, the
    units are valued at the oldest FIFO layer of the receiving branch (units are fungible)."""
    from models.stock_operations import InventoryWriteOff
    from modules.finance.schema import ensure_schema as ensure_finance_schema
    from modules.stock_operations import writeoffs
    from modules.stock_operations.common import balance, item as stock_item, location

    ensure_finance_schema()
    place = location("branch", f"branch:{transfer.to_branch_id}")
    destination_id = line.destination_product_id or line.product_id
    stock_line, product = stock_item("branch", place, destination_id, line.variant_color or "")
    stamp = balance("branch", place, stock_line, product)[3]
    body = {"location_key": place["key"], "product_id": destination_id, "variant_name": line.variant_color or "",
            "quantity": quantity,
            "reason": f"فاقد/تلف أثناء النقل — تحويل {transfer.transfer_no or transfer.id}: {reason}",
            "stock_revision": stamp, "business_date": _business_date()}
    result, _evidence = writeoffs.post("branch", body, user)
    document = db.session.get(InventoryWriteOff, int(result["id"]))
    return document.number if document else str(result["id"])


def _business_date() -> str:
    from modules.finance.common import today

    return today().isoformat()


def _can_writeoff(user) -> bool:
    from utils.permission_checks import employee_can

    return user.role == "admin" or all(
        employee_can(user, p) for p in ("edit_current_stock", "finance.approve", "finance.view"))


def run(ledger: str, row: StockTransfer, action: str, body: dict[str, Any], user):
    """Entry point for the extra transfer actions; mirrors ``transfers.phase`` (revision check, reason, audit)."""
    from . import transfers
    from .common import location, require, text

    if ledger != "branch":
        raise AuditError("هذا الإجراء لتحويلات الفروع فقط", "validation", 400)
    require("edit_current_stock")
    source, target = transfers.places(row, ledger)
    if body.get("revision") != transfers.revision(row, ledger):
        raise AuditError("تغير التحويل؛ حدّث السند", "conflict", 409)
    reason = text(body.get("reason", ""), required=True, limit=1000)
    before = transfers.serialize(row, ledger)
    details: dict[str, Any] = {}
    if action == "approve":
        location(ledger, source)
        if user.role != "admin":
            raise AuditError("اعتماد التحويل للمدير المخول", "forbidden", 403)
        approve(row, user)
    elif action == "reject":
        location(ledger, target)
        reject(row, user)
    elif action == "receive_partial":
        location(ledger, target)
        raw = body.get("lines")
        if not isinstance(raw, list) or not raw:
            raise AuditError("أدخل الكميات المستلمة لكل صنف", "validation", 400)
        try:
            quantities = {int(entry["line_id"]): int(entry["received"]) for entry in raw}
        except (KeyError, TypeError, ValueError):
            raise AuditError("بيانات الاستلام غير صحيحة", "validation", 400) from None
        details["status"] = receive_partial(row, quantities, user)
    elif action == "resolve":
        location(ledger, target)
        if user.role != "admin":
            raise AuditError("معالجة المتبقي للمدير المخول (قد تُرحَّل خسارة)", "forbidden", 403)
        raw = body.get("lines")
        if not isinstance(raw, list) or not raw:
            raise AuditError("حدّد مصير كل كمية متبقية", "validation", 400)
        try:
            plan = {int(entry["line_id"]): str(entry["action"]) for entry in raw}
        except (KeyError, TypeError, ValueError):
            raise AuditError("بيانات المعالجة غير صحيحة", "validation", 400) from None
        if any(a == "loss" for a in plan.values()) and not _can_writeoff(user):
            raise AuditError("تسجيل الفاقد يحتاج صلاحيات سندات التلف (تعديل المخزون + اعتماد مالي)", "forbidden", 403)
        if any(a == "loss" for a in plan.values()):
            # schema guards may commit: run them before ANY change so the resolution stays all-or-nothing
            from modules.finance.schema import ensure_schema as ensure_finance_schema

            ensure_finance_schema()
        details["resolution"] = resolve(row, plan, user, reason,
                                        lambda t, line, qty, why: post_loss(t, line, qty, why, user))
    else:
        raise AuditError("إجراء التحويل غير صالح", "validation", 400)
    db.session.flush()
    return ({"id": row.id, "type": "stock_transfer", "ledger_kind": ledger, "status": row.status},
            {"reason": reason, "before": before, "after": transfers.serialize(row, ledger), **details})
