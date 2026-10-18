from sqlalchemy import event, inspect, text
from sqlalchemy.orm import Session
from extensions import db
from modules.inventory_audit.common import AuditError
from .models import InventoryStorageLocation, InventoryLotPlacement, InventoryStorageTransfer, InventoryStorageTransferLayer,InventoryOrderItemLocation


def ensure_schema():
    for model in (InventoryStorageLocation, InventoryLotPlacement, InventoryStorageTransfer, InventoryStorageTransferLayer,InventoryOrderItemLocation):
        model.__table__.create(bind=db.session.connection(), checkfirst=True)
    if db.session.connection().dialect.name == "sqlite":
        for model in (InventoryStorageTransferLayer,InventoryLotPlacement):
            table=model.__tablename__
            for action in ("UPDATE", "DELETE"):
                db.session.execute(text(f'CREATE TRIGGER IF NOT EXISTS seal_{table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, "storage cost proof is immutable"); END'))
        table = InventoryStorageTransfer.__tablename__
        fields = 'number,branch_id,from_location_id,to_location_id,product_id,variant_name,product_snapshot_json,quantity,reason,created_by,created_at'
        db.session.execute(text(f'CREATE TRIGGER IF NOT EXISTS seal_{table}_payload BEFORE UPDATE OF {fields} ON {table} WHEN OLD.status <> "draft" BEGIN SELECT RAISE(ABORT, "sent storage document is immutable"); END'))
        db.session.execute(text(f'CREATE TRIGGER IF NOT EXISTS seal_{table}_delete BEFORE DELETE ON {table} WHEN OLD.status <> "draft" BEGIN SELECT RAISE(ABORT, "sent storage document is immutable"); END'))
        table=InventoryOrderItemLocation.__tablename__
        for action in ('UPDATE','DELETE'):
            db.session.execute(text(f'CREATE TRIGGER IF NOT EXISTS seal_{table}_{action.lower()} BEFORE {action} ON {table} WHEN EXISTS (SELECT 1 FROM order_item_cost_layer WHERE order_item_id=OLD.order_item_id) BEGIN SELECT RAISE(ABORT, "dispatched stock source is immutable"); END'))


@event.listens_for(Session, "before_flush")
def protect_cost_proof(session, context, instances):
    for row in list(session.dirty) + list(session.deleted):
        if isinstance(row,InventoryOrderItemLocation) and (row in session.deleted or session.is_modified(row,include_collections=False)):
            from models.inventory_lot import OrderItemCostLayer
            if session.query(OrderItemCostLayer.id).filter_by(order_item_id=row.order_item_id).first():
                raise AuditError('مصدر القطع المرسلة محفوظ؛ أعدها بسند مرتبط قبل تغيير المصدر','immutable_source',409)
        if isinstance(row, (InventoryStorageTransferLayer,InventoryLotPlacement)) and (row in session.deleted or session.is_modified(row, include_collections=False)):
            raise AuditError("دليل كلفة النقل محفوظ؛ صحح بسند مرتبط", "immutable_source", 409)
        if isinstance(row, InventoryStorageTransfer):
            state=inspect(row);previous=state.attrs.status.history.deleted
            status=previous[0] if previous else row.status
            fields=('number','branch_id','from_location_id','to_location_id','product_id','variant_name','product_snapshot_json','quantity','reason','created_by','created_at')
            if status!='draft' and (row in session.deleted or any(state.attrs[field].history.has_changes() for field in fields)):
                raise AuditError('بيانات سند النقل المرسل محفوظة', 'immutable_source', 409)
