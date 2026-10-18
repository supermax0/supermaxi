"""Non-cash stock losses from sealed documents; never synthesize cash expenses."""
from flask import has_request_context,g
from sqlalchemy import inspect
from extensions import db
from models.stock_operations import InventoryWriteOff
from models.journal_entry import JournalEntry


def inventory_writeoff_loss(date_from=None,date_to=None,*,branch_id=None,employee_id=None):
    if not inspect(db.session.connection()).has_table(InventoryWriteOff.__tablename__):return 0
    query=db.session.query(InventoryWriteOff.cost,InventoryWriteOff.reversal_of_id).join(
        JournalEntry,JournalEntry.id==InventoryWriteOff.journal_entry_id).filter(
        InventoryWriteOff.sealed.is_(True),InventoryWriteOff.ledger_kind=='branch',
        JournalEntry.reference_type=='inventory_writeoff',JournalEntry.reference_id==InventoryWriteOff.id,
        JournalEntry.amount==InventoryWriteOff.cost)
    if has_request_context():
        from utils.branch_scope import current_employee
        employee=current_employee()
        if employee is not None and employee.role!='admin':
            query=query.filter(InventoryWriteOff.branch_id==employee.branch_id)
        elif getattr(g,'branch',None) is not None and not getattr(g,'view_all_branches',False):
            query=query.filter(InventoryWriteOff.branch_id==g.branch.id)
    if date_from is not None:query=query.filter(InventoryWriteOff.business_date>=date_from)
    if date_to is not None:query=query.filter(InventoryWriteOff.business_date<=date_to)
    if branch_id is not None:query=query.filter(InventoryWriteOff.branch_id==branch_id)
    if employee_id is not None:query=query.filter(InventoryWriteOff.employee_id==employee_id)
    return sum(-cost if reversal is not None else cost for cost,reversal in query.all())
