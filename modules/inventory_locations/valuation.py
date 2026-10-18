"""Read-only value of frozen internal-transfer layers; no actor/session dependency."""
from sqlalchemy import inspect
from extensions import db
from .models import InventoryStorageTransfer, InventoryStorageTransferLayer


def in_transit_value(branch_ids=None):
    if branch_ids is not None:
        branch_ids=list(branch_ids)
        if any(type(value) is not int or value<1 for value in branch_ids):
            raise ValueError('Invalid inventory valuation branch scope')
        if not branch_ids:return 0
    connection=db.session.connection()
    if not all(inspect(connection).has_table(model.__tablename__) for model in
        (InventoryStorageTransfer,InventoryStorageTransferLayer)):
        return 0
    query=db.session.query(InventoryStorageTransferLayer.quantity,InventoryStorageTransferLayer.unit_cost).execution_options(
        skip_branch_scope=True).join(InventoryStorageTransfer,
        InventoryStorageTransferLayer.transfer_id==InventoryStorageTransfer.id).filter(
        InventoryStorageTransfer.status=='sent',InventoryStorageTransferLayer.phase=='send')
    if branch_ids is not None:query=query.filter(InventoryStorageTransfer.branch_id.in_(branch_ids))
    return sum(quantity*unit_cost for quantity,unit_cost in query.all())
