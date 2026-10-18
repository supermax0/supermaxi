from sqlalchemy import inspect, text
from sqlalchemy import event
from sqlalchemy.orm import Session
from extensions import db
from models.stock_operations import StockTransferCostLayer,InventoryWriteOff,StockReorderRule
from modules.desktop_api.sync import DesktopSyncReceipt


def ensure_schema():
    for model in [StockTransferCostLayer,InventoryWriteOff,StockReorderRule,DesktopSyncReceipt]:
        model.__table__.create(bind=db.session.connection(),checkfirst=True)
    if db.session.connection().dialect.name=="sqlite":
        for model in [StockTransferCostLayer,InventoryWriteOff]:
            name=model.__tablename__
            for action in ['UPDATE','DELETE']:
                condition=' WHEN OLD.sealed = 1' if model is InventoryWriteOff else ''
                db.session.execute(text(f'CREATE TRIGGER IF NOT EXISTS seal_{name}_{action.lower()} '
                    f'BEFORE {action} ON {name}{condition} BEGIN SELECT RAISE(ABORT, "stock document is immutable"); END'))


@event.listens_for(Session,'before_flush')
def immutable_documents(session,context,instances):
    from modules.inventory_audit.common import AuditError
    for row in list(session.dirty)+list(session.deleted):
        if isinstance(row,InventoryWriteOff):
            history=inspect(row).attrs.sealed.history
            previous=history.deleted[0] if history.deleted else row.sealed
            if not previous:continue
        if isinstance(row,(StockTransferCostLayer,InventoryWriteOff)) and (
            row in session.deleted or session.is_modified(row,include_collections=False)):
            raise AuditError("المستند المخزني محفوظ؛ صحح الخطأ بسند عكس موثق","immutable_source",409)

