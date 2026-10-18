"""Warehouse stock operations for wholesale tenants only."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, update

from extensions import db
from modules.wholesale.models.warehouse import (
    Warehouse,
    WarehouseMovement,
    WarehouseStock,
    WarehouseTransfer,
    WarehouseTransferLine,
)
from modules.wholesale.services.helpers import WholesaleError, next_doc_no, parse_int


def _wh_query(tenant_id: int | None):
    q = Warehouse.query.filter(Warehouse.deleted_at.is_(None))
    if tenant_id is not None:
        q = q.filter(or_(Warehouse.tenant_id == tenant_id, Warehouse.tenant_id.is_(None)))
    return q


def list_warehouses(tenant_id: int | None, active_only: bool = True) -> list[Warehouse]:
    q = _wh_query(tenant_id)
    if active_only:
        q = q.filter(Warehouse.is_active.is_(True))
    return q.order_by(Warehouse.kind.asc(), Warehouse.name.asc()).all()


def get_warehouse(tenant_id: int | None, warehouse_id: int) -> Warehouse:
    wh = _wh_query(tenant_id).filter(Warehouse.id == warehouse_id).first()
    if not wh:
        raise WholesaleError("المخزن غير موجود", "warehouse_not_found")
    return wh


def create_warehouse(
    tenant_id: int | None,
    *,
    code: str,
    name: str,
    branch_id: int | None = None,
    kind: str = "main",
) -> Warehouse:
    code = (code or "").strip()
    name = (name or "").strip()
    if not code or not name:
        raise WholesaleError("رمز واسم المخزن مطلوبان")
    kind = kind if kind in ("main", "damaged", "returns") else "main"
    exists = _wh_query(tenant_id).filter(Warehouse.code == code).first()
    if exists:
        raise WholesaleError("رمز المخزن مستخدم مسبقاً", "duplicate_code")
    wh = Warehouse(
        tenant_id=tenant_id,
        branch_id=branch_id,
        code=code,
        name=name,
        kind=kind,
        is_active=True,
    )
    db.session.add(wh)
    db.session.flush()
    return wh


def ensure_default_warehouses(tenant_id: int | None, branch_id: int | None = None) -> list[Warehouse]:
    existing = list_warehouses(tenant_id, active_only=False)
    if existing:
        return existing
    defaults = [
        ("MAIN", "المخزن الرئيسي", "main"),
        ("DMG", "مخزن تالف", "damaged"),
        ("RET", "مخزن مرتجعات", "returns"),
    ]
    created = []
    for code, name, kind in defaults:
        created.append(
            create_warehouse(tenant_id, code=code, name=name, branch_id=branch_id, kind=kind)
        )
    return created


def get_stock_row(tenant_id: int | None, warehouse_id: int, product_id: int, *, create: bool = False) -> WarehouseStock | None:
    q = WarehouseStock.query.filter_by(warehouse_id=warehouse_id, product_id=product_id)
    if tenant_id is not None:
        q = q.filter(or_(WarehouseStock.tenant_id == tenant_id, WarehouseStock.tenant_id.is_(None)))
    row = q.first()
    if row or not create:
        return row
    row = WarehouseStock(
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
        product_id=product_id,
        quantity=0,
        opening_stock=0,
        reserved_quantity=0,
        in_transit_quantity=0,
    )
    db.session.add(row)
    db.session.flush()
    return row


def available_qty(tenant_id: int | None, warehouse_id: int, product_id: int) -> int:
    row = get_stock_row(tenant_id, warehouse_id, product_id)
    return row.available_quantity if row else 0


def stock_snapshot(tenant_id: int | None, warehouse_id: int, product_id: int) -> dict:
    row = get_stock_row(tenant_id, warehouse_id, product_id)
    if not row:
        return {"on_hand": 0, "reserved": 0, "available": 0, "in_transit": 0}
    return {
        "on_hand": int(row.quantity or 0),
        "reserved": int(row.reserved_quantity or 0),
        "available": row.available_quantity,
        "in_transit": int(row.in_transit_quantity or 0),
    }


def reserve_stock(tenant_id: int | None, *, warehouse_id: int, product_id: int, quantity: int) -> WarehouseStock:
    if quantity <= 0:
        raise WholesaleError("كمية الحجز يجب أن تكون أكبر من صفر")
    row = get_stock_row(tenant_id, warehouse_id, product_id, create=True)
    assert row is not None
    if row.available_quantity < quantity:
        raise WholesaleError("الكمية المتاحة للحجز غير كافية", "insufficient_available_stock")
    row.reserved_quantity = int(row.reserved_quantity or 0) + quantity
    db.session.flush()
    return row


def release_stock(tenant_id: int | None, *, warehouse_id: int, product_id: int, quantity: int) -> WarehouseStock:
    row = get_stock_row(tenant_id, warehouse_id, product_id, create=True)
    assert row is not None
    row.reserved_quantity = max(0, int(row.reserved_quantity or 0) - max(0, quantity))
    db.session.flush()
    return row


def apply_movement(
    tenant_id: int | None,
    *,
    warehouse_id: int,
    product_id: int,
    quantity_delta: int,
    movement_type: str,
    reference_type: str | None = None,
    reference_id: int | None = None,
    unit_cost: int | None = None,
    note: str | None = None,
    created_by: int | None = None,
    allow_negative: bool = False,
) -> WarehouseStock:
    get_warehouse(tenant_id, warehouse_id)
    row = get_stock_row(tenant_id, warehouse_id, product_id, create=True)
    assert row is not None
    quantity_before = int(row.quantity or 0)
    new_qty = int(row.quantity or 0) + int(quantity_delta)
    if quantity_delta < 0 and int(row.available_quantity) + int(quantity_delta) < 0 and not allow_negative:
        raise WholesaleError("الكمية غير كافية في المخزن", "insufficient_stock")
    changed = db.session.execute(update(WarehouseStock).where(WarehouseStock.id == row.id,
        WarehouseStock.quantity == quantity_before,
        WarehouseStock.reserved_quantity == row.reserved_quantity).values(quantity=new_qty).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise WholesaleError("تغير رصيد المخزن أثناء التسجيل؛ حدّث البيانات وأعد المحاولة", "conflict")
    db.session.expire(row)
    db.session.add(
        WarehouseMovement(
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
            product_id=product_id,
            movement_type=movement_type,
            quantity=int(quantity_delta),
            quantity_before=quantity_before,
            quantity_after=new_qty,
            unit_cost=unit_cost,
            reference_type=reference_type,
            reference_id=reference_id,
            note=note,
            created_by=created_by,
        )
    )
    db.session.flush()
    return row


def adjust_stock(
    tenant_id: int | None,
    *,
    warehouse_id: int,
    product_id: int,
    new_quantity: int,
    created_by: int | None = None,
    note: str | None = None,
) -> WarehouseStock:
    current = available_qty(tenant_id, warehouse_id, product_id)
    delta = int(new_quantity) - current
    return apply_movement(
        tenant_id,
        warehouse_id=warehouse_id,
        product_id=product_id,
        quantity_delta=delta,
        movement_type="adjust",
        note=note or "تسوية مخزون",
        created_by=created_by,
        allow_negative=True,
    )


def create_transfer(
    tenant_id: int | None,
    *,
    from_warehouse_id: int,
    to_warehouse_id: int,
    lines: list[dict],
    note: str | None = None,
    created_by: int | None = None,
    send: bool = False,
) -> WarehouseTransfer:
    if from_warehouse_id == to_warehouse_id:
        raise WholesaleError("لا يمكن التحويل لنفس المخزن")
    get_warehouse(tenant_id, from_warehouse_id)
    get_warehouse(tenant_id, to_warehouse_id)
    tq = WarehouseTransfer.query
    if tenant_id is not None:
        tq = tq.filter(or_(WarehouseTransfer.tenant_id == tenant_id, WarehouseTransfer.tenant_id.is_(None)))
    last = tq.order_by(WarehouseTransfer.id.desc()).first()
    transfer = WarehouseTransfer(
        tenant_id=tenant_id,
        transfer_no=next_doc_no("WHT", last.transfer_no if last else None),
        from_warehouse_id=from_warehouse_id,
        to_warehouse_id=to_warehouse_id,
        status="draft",
        note=note,
        created_by_id=created_by,
    )
    db.session.add(transfer)
    db.session.flush()
    for line in lines:
        pid = parse_int(line.get("product_id"))
        qty = parse_int(line.get("quantity"))
        if pid <= 0 or qty <= 0:
            continue
        db.session.add(
            WarehouseTransferLine(transfer_id=transfer.id, product_id=pid, quantity=qty)
        )
    db.session.flush()
    if send:
        send_transfer(tenant_id, transfer.id, created_by=created_by)
    return transfer


def send_transfer(tenant_id: int | None, transfer_id: int, created_by: int | None = None) -> WarehouseTransfer:
    transfer = WarehouseTransfer.query.filter_by(id=transfer_id).first()
    if not transfer or (tenant_id is not None and transfer.tenant_id not in (tenant_id, None)):
        raise WholesaleError("سند التحويل غير موجود")
    if transfer.status not in ("draft", "approved"):
        raise WholesaleError("لا يمكن إرسال هذا السند")
    from utils.stock_transfer_state import transition
    from utils.warehouse_transfer_valuation import unit_cost
    transition(transfer, {"draft", "approved"}, "sent")
    for line in transfer.lines:
        cost = unit_cost(transfer, line, "send")
        apply_movement(
            tenant_id,
            warehouse_id=transfer.from_warehouse_id,
            product_id=line.product_id,
            quantity_delta=-int(line.quantity),
            movement_type="transfer",
            reference_type="warehouse_transfer",
            reference_id=transfer.id,
            created_by=created_by,
            unit_cost=cost,
        )
        destination = get_stock_row(tenant_id, transfer.to_warehouse_id, line.product_id, create=True)
        assert destination is not None
        db.session.execute(update(WarehouseStock).where(WarehouseStock.id==destination.id).values(
            in_transit_quantity=WarehouseStock.in_transit_quantity+line.quantity).execution_options(synchronize_session=False))
        db.session.expire(destination)
    transfer.status = "sent"
    transfer.sent_at = datetime.utcnow()
    db.session.flush()
    return transfer


def approve_transfer(tenant_id: int | None, transfer_id: int, approved_by: int | None = None) -> WarehouseTransfer:
    transfer = WarehouseTransfer.query.filter_by(id=transfer_id).first()
    if not transfer or (tenant_id is not None and transfer.tenant_id not in (tenant_id, None)):
        raise WholesaleError("سند التحويل غير موجود")
    if transfer.status != "draft":
        raise WholesaleError("لا يمكن اعتماد هذا السند")
    if not transfer.lines:
        raise WholesaleError("أضف صنفاً واحداً على الأقل للتحويل")
    transfer.status = "approved"
    transfer.approved_by_id = approved_by
    transfer.approved_at = datetime.utcnow()
    db.session.flush()
    return transfer


def receive_transfer(tenant_id: int | None, transfer_id: int, received_by: int | None = None) -> WarehouseTransfer:
    transfer = WarehouseTransfer.query.filter_by(id=transfer_id).first()
    if not transfer or (tenant_id is not None and transfer.tenant_id not in (tenant_id, None)):
        raise WholesaleError("سند التحويل غير موجود")
    if transfer.status != "sent":
        raise WholesaleError("السند غير جاهز للاستلام")
    from utils.stock_transfer_state import transition
    from utils.warehouse_transfer_valuation import unit_cost
    transition(transfer, {"sent"}, "received")
    for line in transfer.lines:
        cost = unit_cost(transfer, line, "receive")
        apply_movement(
            tenant_id,
            warehouse_id=transfer.to_warehouse_id,
            product_id=line.product_id,
            quantity_delta=int(line.quantity),
            movement_type="transfer",
            reference_type="warehouse_transfer",
            reference_id=transfer.id,
            created_by=received_by,
            unit_cost=cost,
        )
        destination = get_stock_row(tenant_id, transfer.to_warehouse_id, line.product_id, create=True)
        assert destination is not None
        changed=db.session.execute(update(WarehouseStock).where(WarehouseStock.id==destination.id,
            WarehouseStock.in_transit_quantity>=line.quantity).values(
            in_transit_quantity=WarehouseStock.in_transit_quantity-line.quantity).execution_options(synchronize_session=False))
        if changed.rowcount!=1:raise WholesaleError("رصيد قيد النقل لا يطابق السند؛ راجع التحويل", "conflict")
        db.session.expire(destination)
    transfer.status = "received"
    transfer.received_by_id = received_by
    transfer.received_at = datetime.utcnow()
    db.session.flush()
    return transfer


def cancel_transfer(tenant_id: int | None, transfer_id: int, cancelled_by: int | None = None) -> WarehouseTransfer:
    transfer = WarehouseTransfer.query.filter_by(id=transfer_id).first()
    if not transfer or (tenant_id is not None and transfer.tenant_id not in (tenant_id, None)):
        raise WholesaleError("سند التحويل غير موجود")
    if transfer.status in ("received", "cancelled"):
        raise WholesaleError("لا يمكن إلغاء هذا السند")
    previous = transfer.status
    from utils.stock_transfer_state import transition
    from utils.warehouse_transfer_valuation import unit_cost
    transition(transfer, {"draft", "approved", "sent"}, "cancelled")
    if previous == "sent":
        for line in transfer.lines:
            cost = unit_cost(transfer, line, "cancel")
            apply_movement(
                tenant_id,
                warehouse_id=transfer.from_warehouse_id,
                product_id=line.product_id,
                quantity_delta=int(line.quantity),
                movement_type="transfer_cancel",
                reference_type="warehouse_transfer",
                reference_id=transfer.id,
                created_by=cancelled_by,
                unit_cost=cost,
            )
            destination = get_stock_row(tenant_id, transfer.to_warehouse_id, line.product_id, create=True)
            assert destination is not None
            changed=db.session.execute(update(WarehouseStock).where(WarehouseStock.id==destination.id,
                WarehouseStock.in_transit_quantity>=line.quantity).values(
                in_transit_quantity=WarehouseStock.in_transit_quantity-line.quantity).execution_options(synchronize_session=False))
            if changed.rowcount!=1:raise WholesaleError("رصيد قيد النقل تغير؛ راجع السند", "conflict")
            db.session.expire(destination)
    transfer.status = "cancelled"
    db.session.flush()
    return transfer


def list_movements(tenant_id: int | None, warehouse_id: int | None = None, product_id: int | None = None, limit: int = 200):
    q = WarehouseMovement.query
    if tenant_id is not None:
        q = q.filter(or_(WarehouseMovement.tenant_id == tenant_id, WarehouseMovement.tenant_id.is_(None)))
    if warehouse_id:
        q = q.filter(WarehouseMovement.warehouse_id == warehouse_id)
    if product_id:
        q = q.filter(WarehouseMovement.product_id == product_id)
    return q.order_by(WarehouseMovement.id.desc()).limit(limit).all()


def list_transfers(tenant_id: int | None, warehouse_id: int | None = None, limit: int = 200):
    q = WarehouseTransfer.query.filter(WarehouseTransfer.deleted_at.is_(None))
    if tenant_id is not None:
        q = q.filter(or_(WarehouseTransfer.tenant_id == tenant_id, WarehouseTransfer.tenant_id.is_(None)))
    if warehouse_id:
        q = q.filter(
            or_(
                WarehouseTransfer.from_warehouse_id == warehouse_id,
                WarehouseTransfer.to_warehouse_id == warehouse_id,
            )
        )
    return q.order_by(WarehouseTransfer.id.desc()).limit(limit).all()


def transfer_to_dict(transfer: WarehouseTransfer) -> dict:
    return {
        "id": transfer.id,
        "transfer_no": transfer.transfer_no,
        "from_warehouse_id": transfer.from_warehouse_id,
        "to_warehouse_id": transfer.to_warehouse_id,
        "status": transfer.status,
        "note": transfer.note,
        "created_by_id": transfer.created_by_id,
        "approved_by_id": transfer.approved_by_id,
        "received_by_id": transfer.received_by_id,
        "created_at": transfer.created_at.isoformat() if transfer.created_at else None,
        "sent_at": transfer.sent_at.isoformat() if transfer.sent_at else None,
        "received_at": transfer.received_at.isoformat() if transfer.received_at else None,
        "lines": [{"product_id": line.product_id, "quantity": int(line.quantity or 0)} for line in transfer.lines],
    }
