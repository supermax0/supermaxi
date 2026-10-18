from __future__ import annotations

import json
import uuid
import weakref
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from flask import has_request_context, request, session

from extensions import db
from models.inventory_audit import InventoryQuantityAudit, InventoryStockSnapshot
from models.stock_movement import StockMovement


_ready_engines = weakref.WeakSet()


def ensure_inventory_audit_schema() -> None:
    # Use the active transaction connection.  On SQLite an Engine-level
    # schema check may borrow the same DBAPI connection and roll back the
    # caller's uncommitted stock mutation when it closes.
    bind = db.session.connection()
    ensure_inventory_audit_schema_on_engine(bind)


def ensure_inventory_audit_schema_on_engine(bind) -> None:
    if bind in _ready_engines:
        return
    StockMovement.__table__.create(bind=bind, checkfirst=True)
    InventoryQuantityAudit.__table__.create(bind=bind, checkfirst=True)
    InventoryStockSnapshot.__table__.create(bind=bind, checkfirst=True)
    # SQLite tenant databases are also protected at database level. This
    # catches legacy routes and maintenance scripts that still write quantity
    # directly instead of going through branch_stock_service.
    if bind.dialect.name == "sqlite":
        trigger_statements = (
            """
            CREATE TRIGGER IF NOT EXISTS trg_inventory_audit_branch_stock_insert
            AFTER INSERT ON branch_stock
            WHEN NEW.quantity <> 0
            BEGIN
              INSERT INTO inventory_quantity_audit
                (event_key, product_id, branch_id, operation, before_quantity,
                 delta_quantity, after_quantity, source_type, source_id,
                 reason, metadata_json, created_at)
              VALUES
                (lower(hex(randomblob(16))), NEW.product_id, NEW.branch_id,
                 'database_guard', 0, NEW.quantity, NEW.quantity,
                 'database_trigger', NEW.product_id,
                 'التقاط تلقائي لتغيير كمية المخزون',
                 '{"database_guard":true,"scope":"branch_stock"}', CURRENT_TIMESTAMP);
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_inventory_audit_branch_stock_update
            AFTER UPDATE OF quantity ON branch_stock
            WHEN OLD.quantity <> NEW.quantity
            BEGIN
              INSERT INTO inventory_quantity_audit
                (event_key, product_id, branch_id, operation, before_quantity,
                 delta_quantity, after_quantity, source_type, source_id,
                 reason, metadata_json, created_at)
              VALUES
                (lower(hex(randomblob(16))), NEW.product_id, NEW.branch_id,
                 'database_guard', OLD.quantity, NEW.quantity - OLD.quantity,
                 NEW.quantity, 'database_trigger', NEW.product_id,
                 'التقاط تلقائي لتغيير كمية المخزون',
                 '{"database_guard":true,"scope":"branch_stock"}', CURRENT_TIMESTAMP);
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_inventory_audit_product_quantity_update
            AFTER UPDATE OF quantity ON product
            WHEN OLD.quantity <> NEW.quantity
              AND (
                NOT EXISTS (SELECT 1 FROM branch_stock WHERE product_id = NEW.id)
                OR NEW.quantity <> COALESCE((SELECT SUM(quantity) FROM branch_stock WHERE product_id = NEW.id), 0)
              )
            BEGIN
              INSERT INTO inventory_quantity_audit
                (event_key, product_id, branch_id, operation, before_quantity,
                 delta_quantity, after_quantity, source_type, source_id,
                 reason, metadata_json, created_at)
              VALUES
                (lower(hex(randomblob(16))), NEW.id, NULL,
                 'database_guard', OLD.quantity, NEW.quantity - OLD.quantity,
                 NEW.quantity, 'database_trigger', NEW.id,
                 'تغيير مباشر في بطاقة المنتج خارج مجموع الفروع',
                 '{"database_guard":true,"scope":"product_card"}', CURRENT_TIMESTAMP);
            END
            """,
        )
        if hasattr(bind, "exec_driver_sql"):
            for statement in trigger_statements:
                bind.exec_driver_sql(statement)
        else:
            with bind.begin() as connection:
                for statement in trigger_statements:
                    connection.exec_driver_sql(statement)
    _ready_engines.add(bind)


def _request_identity() -> Dict[str, Any]:
    if not has_request_context():
        return {"employee_id": None, "employee_name": None, "request_path": None}
    return {
        "employee_id": session.get("user_id"),
        "employee_name": session.get("name") or session.get("employee_name"),
        "request_path": request.path[:500],
    }


def _pending_movement(
    product_id: int,
    branch_id: Optional[int],
    delta: int,
) -> Optional[StockMovement]:
    direction = "in" if delta > 0 else "out"
    quantity = abs(int(delta))
    try:
        for candidate in reversed(list(db.session.new)):
            if not isinstance(candidate, StockMovement):
                continue
            if (
                int(candidate.product_id) == int(product_id)
                and (int(candidate.branch_id) if candidate.branch_id else None)
                == (int(branch_id) if branch_id else None)
                and candidate.direction == direction
                and int(candidate.quantity) == quantity
            ):
                return candidate
    except Exception:
        pass

    threshold = datetime.utcnow() - timedelta(seconds=45)
    query = StockMovement.query.filter(
        StockMovement.product_id == int(product_id),
        StockMovement.direction == direction,
        StockMovement.quantity == quantity,
        StockMovement.created_at >= threshold,
    )
    query = query.filter(
        StockMovement.branch_id == int(branch_id)
        if branch_id
        else StockMovement.branch_id.is_(None)
    )
    for movement in query.order_by(StockMovement.id.desc()).limit(8).all():
        used = InventoryQuantityAudit.query.filter_by(movement_id=movement.id).first()
        if not used:
            return movement
    return None


def record_stock_mutation(
    *,
    product_id: int,
    branch_id: Optional[int],
    before_quantity: int,
    after_quantity: int,
    operation: str,
    audit_context: Optional[Dict[str, Any]] = None,
) -> Optional[InventoryQuantityAudit]:
    """Record evidence without ever making the stock operation fail."""
    before = int(before_quantity or 0)
    after = int(after_quantity or 0)
    delta = after - before
    if delta == 0:
        return None
    try:
        ensure_inventory_audit_schema()
        context = dict(audit_context or {})
        movement = _pending_movement(product_id, branch_id, delta)
        identity = _request_identity()
        if movement is None:
            direction = "in" if delta > 0 else "out"
            movement = StockMovement(
                movement_key=f"unclassified:{uuid.uuid4().hex}",
                movement_type="unclassified_adjustment",
                direction=direction,
                product_id=int(product_id),
                branch_id=int(branch_id) if branch_id else None,
                quantity=abs(delta),
                unit_cost=int(context.get("unit_cost") or 0),
                total_cost=abs(delta) * int(context.get("unit_cost") or 0),
                source_type=str(context.get("source_type") or "direct_stock_change")[:50],
                source_id=int(context.get("source_id") or product_id),
                source_line_id=(int(context["source_line_id"]) if context.get("source_line_id") else None),
                details_json=json.dumps({
                    "auto_captured": True,
                    "operation": operation,
                    "before_quantity": before,
                    "after_quantity": after,
                    "reason": context.get("reason"),
                    "request_path": identity.get("request_path"),
                }, ensure_ascii=False, sort_keys=True),
            )
            db.session.add(movement)
            db.session.flush()

        db.session.flush()
        trigger_audit = InventoryQuantityAudit.query.filter(
            InventoryQuantityAudit.movement_id.is_(None),
            InventoryQuantityAudit.product_id == int(product_id),
            InventoryQuantityAudit.branch_id == (int(branch_id) if branch_id else None),
            InventoryQuantityAudit.before_quantity == before,
            InventoryQuantityAudit.after_quantity == after,
            InventoryQuantityAudit.created_at >= datetime.utcnow() - timedelta(seconds=10),
        ).order_by(InventoryQuantityAudit.id.desc()).first()

        metadata = {
            "movement_key": movement.movement_key,
            "movement_type": movement.movement_type,
            "direction": movement.direction,
            "auto_captured": movement.movement_type == "unclassified_adjustment",
            **{key: value for key, value in context.items() if key not in {"reason"}},
        }
        audit = trigger_audit or InventoryQuantityAudit(event_key=uuid.uuid4().hex)
        audit.movement_id = movement.id
        audit.product_id = int(product_id)
        audit.branch_id = int(branch_id) if branch_id else None
        audit.operation = str(operation or "stock_change")[:50]
        audit.before_quantity = before
        audit.delta_quantity = delta
        audit.after_quantity = after
        audit.source_type = movement.source_type
        audit.source_id = movement.source_id
        audit.source_line_id = movement.source_line_id
        audit.employee_id = identity.get("employee_id")
        audit.employee_name = identity.get("employee_name")
        audit.request_path = identity.get("request_path")
        audit.reason = str(context.get("reason") or "").strip() or audit.reason
        audit.set_metadata(metadata)
        if trigger_audit is None:
            db.session.add(audit)
        return audit
    except Exception:
        # Auditing must never block a legitimate stock mutation. The forensic
        # report will expose a missing audit trail as a risk by itself.
        return None


def capture_product_snapshot(
    product_id: int,
    *,
    session_id: Optional[str] = None,
    source: str = "forensic_scan",
) -> list[InventoryStockSnapshot]:
    from models.branch import BranchStock
    from models.product import Product

    ensure_inventory_audit_schema()
    rows = BranchStock.query.filter_by(product_id=int(product_id)).all()
    snapshots = []
    if rows:
        for row in rows:
            snapshot = InventoryStockSnapshot(
                snapshot_key=uuid.uuid4().hex,
                product_id=int(product_id),
                branch_id=int(row.branch_id),
                quantity=int(row.quantity or 0),
                session_id=session_id,
                source=source,
            )
            db.session.add(snapshot)
            snapshots.append(snapshot)
    else:
        product = Product.query.get(int(product_id))
        if product:
            snapshot = InventoryStockSnapshot(
                snapshot_key=uuid.uuid4().hex,
                product_id=int(product_id),
                branch_id=None,
                quantity=int(product.quantity or 0),
                session_id=session_id,
                source=source,
            )
            db.session.add(snapshot)
            snapshots.append(snapshot)
    return snapshots
