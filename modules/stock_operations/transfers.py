from datetime import datetime
from uuid import uuid4
from sqlalchemy import inspect
from extensions import db
from models.branch import StockTransfer,StockTransferLine
from models.product import Product
from .common import actor,require,kind,locations,location,item,balance,integer,text,fingerprint,cost_visible,money,AuditError


def model(ledger):
    if ledger=='branch':return StockTransfer
    from modules.wholesale.models.warehouse import WarehouseTransfer
    return WarehouseTransfer


def places(row,ledger):
    return (f'branch:{row.from_branch_id}',f'branch:{row.to_branch_id}') if ledger=='branch' else (
        f'warehouse:{row.from_warehouse_id}',f'warehouse:{row.to_warehouse_id}')


def get(ledger,document_id):
    kind(ledger);integer(document_id,minimum=1)
    row=db.session.get(model(ledger),document_id)
    allowed={entry['key'] for entry in locations(ledger)}
    if not row or not allowed.intersection(places(row,ledger)):
        raise AuditError("التحويل غير موجود أو خارج نطاقك","not_found",404)
    return row


def revision(row,ledger):
    return fingerprint({'kind':ledger,'id':row.id,'status':row.status,'places':places(row,ledger),
        'note':row.note,'lines':[(line.id,line.product_id,line.quantity,getattr(line,'variant_color',None),
            getattr(line,'quantity_received',0)) for line in row.lines]})


def serialize(row,ledger,detail=False):
    from models.branch import Branch
    if ledger=='branch':
        source=db.session.get(Branch,row.from_branch_id);target=db.session.get(Branch,row.to_branch_id)
    else:
        from modules.wholesale.models.warehouse import Warehouse
        source=db.session.get(Warehouse,row.from_warehouse_id);target=db.session.get(Warehouse,row.to_warehouse_id)
    result={'id':row.id,'ledger_kind':ledger,'number':row.transfer_no or f'TR-{row.id}',
        'from_location':places(row,ledger)[0],'to_location':places(row,ledger)[1],
        'from_name':source.name if source else '—','to_name':target.name if target else '—',
        'status':row.status,'quantity':sum(line.quantity for line in row.lines),'note':row.note or '',
        'created_at':row.created_at.isoformat() if row.created_at else None,'revision':revision(row,ledger)}
    if detail:
        from utils.inventory_transfer_valuation import layers
        result['lines']=[]
        for line in row.lines:
            product=Product.query.execution_options(skip_branch_scope=True).filter_by(id=line.product_id).first()
            evidence=layers(row.id,line.id,kind=ledger)
            result['lines'].append({'id':line.id,'product_id':line.product_id,'name':product.name if product else '—',
                'variant_name':getattr(line,'variant_color','') or '','quantity':line.quantity,
                'received':(getattr(line,'quantity_received',line.quantity if row.status=='received' else 0) or 0),
                'cost':money(sum(p.quantity*p.unit_cost for p in evidence)) if cost_visible() and evidence else None})
        user=actor()
        allowed={entry['key'] for entry in locations(ledger)}
        result['can_send']=row.status in ('draft','approved') and user.role=='admin' and result['from_location'] in allowed
        result['can_receive']=row.status=='sent' and result['to_location'] in allowed
        result['can_cancel']=row.status in ('draft','approved','sent') and user.role=='admin' and result['from_location'] in allowed
        if ledger=='branch':
            from . import transfer_partial as partial
            result['approval_required']=partial.approval_required()
            result['can_approve']=row.status=='draft' and user.role=='admin' and result['from_location'] in allowed
            result['can_receive_partial']=result['can_receive']
            result['can_reject']=result['can_receive']
            result['can_resolve']=row.status=='partially_received' and user.role=='admin' and result['to_location'] in allowed
            for entry,line in zip(result['lines'],row.lines):
                state=partial.line_state(row.id,line.id)
                entry['sent']=line.quantity
                entry['residual']=state['residual'] if state['has_layers'] else (line.quantity if row.status=='sent' else 0)
    return result


def listing(ledger,status='',q=''):
    table=model(kind(ledger))
    if not inspect(db.session.connection()).has_table(table.__tablename__):return []
    allowed={row['key'] for row in locations(ledger)}
    # Scope before materializing, including parent documents visible from either end.
    ids=[int(key.split(':')[1]) for key in allowed]
    from sqlalchemy import or_
    source=table.from_branch_id if ledger=='branch' else table.from_warehouse_id
    target=table.to_branch_id if ledger=='branch' else table.to_warehouse_id
    query=table.query.filter(or_(source.in_(ids),target.in_(ids)))
    if status:query=query.filter(table.status==status)
    if q:query=query.filter(table.transfer_no.contains(q,autoescape=True))
    return query.order_by(table.id.desc())


def create(ledger,body,user):
    require('edit_current_stock')
    source=location(ledger,body.get('from_location'));destination=location(ledger,body.get('to_location'))
    if source['key']==destination['key']:raise AuditError("اختر موقعين مختلفين للتحويل")
    note=text(body.get('reason',''),required=True,limit=1000)
    lines=body.get('lines')
    if not isinstance(lines,list) or not 1<=len(lines)<=100:raise AuditError("أضف من1 إلى100 صنف للتحويل")
    normalized=[];seen=set()
    for entry in lines:
        if not isinstance(entry,dict):raise AuditError("بيانات صنف التحويل غير صحيحة")
        line,product=item(ledger,source,entry.get('product_id'),entry.get('variant_name',''))
        identity=(product.id,line.variant_name)
        if identity in seen:raise AuditError("الصنف والخيار مكرر في التحويل")
        seen.add(identity);quantity=integer(entry.get('quantity'),minimum=1)
        if quantity>balance(ledger,source,line,product)[1]:raise AuditError("الكمية أكبر من المتاح بعد الحجوزات","stock_conflict",409)
        normalized.append({'product_id':product.id,'variant_color':line.variant_name or None,'quantity':quantity})
    if ledger=='branch':
        row=StockTransfer(transfer_no=f'TR-{uuid4().hex[:12].upper()}',from_branch_id=source['branch_id'],
            to_branch_id=destination['branch_id'],status='draft',note=note,created_by_id=user.id)
        db.session.add(row);db.session.flush()
        for entry in normalized:db.session.add(StockTransferLine(transfer_id=row.id,**entry))
    else:
        from modules.wholesale.services.warehouse_service import create_transfer
        row=create_transfer(None,from_warehouse_id=source['warehouse_id'],to_warehouse_id=destination['warehouse_id'],
            lines=normalized,note=note,created_by=user.id)
    db.session.flush()
    return {'id':row.id,'type':'stock_transfer','ledger_kind':ledger,'status':row.status},{'reason':note,'after':serialize(row,ledger)}


def phase(ledger,row,action,body,user):
    require('edit_current_stock')
    source,target=places(row,ledger)
    location(ledger,target if action=='receive' else source)
    if action!='receive' and user.role!='admin':raise AuditError("إرسال التحويل وإلغاؤه للمدير المخول","forbidden",403)
    if body.get('revision')!=revision(row,ledger):raise AuditError("تغير التحويل؛ حدّث السند","conflict",409)
    reason=text(body.get('reason',''),required=True,limit=1000)
    before=serialize(row,ledger)
    if ledger=='branch':
        from routes.stock_transfers import _apply_transfer_movements
        from utils.stock_transfer_state import transition
        if action=='send':
            from .transfer_partial import approval_required
            if approval_required() and row.status!='approved':
                raise AuditError("هذه الشركة تشترط اعتماد التحويل قبل إرساله","conflict",409)
        expected={'send':{'draft','approved'},'receive':{'sent'},'cancel':{'draft','approved','sent'}}[action]
        previous=row.status
        transition(row,expected,{'send':'sent','receive':'received','cancel':'cancelled'}[action])
        if action!='cancel' or previous=='sent':_apply_transfer_movements(row,action)
        if action=='send':row.sent_at=datetime.utcnow()
        elif action=='receive':
            row.received_at=datetime.utcnow();row.received_by_id=user.id
            for line in row.lines:line.quantity_received=line.quantity
    else:
        from modules.wholesale.services import warehouse_service as service
        if action=='send':service.send_transfer(None,row.id,created_by=user.id)
        elif action=='receive':service.receive_transfer(None,row.id,received_by=user.id)
        else:service.cancel_transfer(None,row.id,cancelled_by=user.id)
    db.session.flush()
    return {'id':row.id,'type':'stock_transfer','ledger_kind':ledger,'status':row.status},{
        'reason':reason,'before':before,'after':serialize(row,ledger)}

