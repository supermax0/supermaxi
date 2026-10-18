"""Core storage API. This blueprint is registered only after all stock consumers are integrated."""
from flask import Blueprint, jsonify, request
import json
from types import SimpleNamespace
from sqlalchemy import inspect
from extensions import db
from models.branch import Branch
from modules.inventory_audit.common import actor, integer, text, visible_branches, AuditError
from modules.stock_operations.routes import endpoint, paging
from modules.stock_operations.commands import execute
from modules.stock_operations.common import cost_visible
from utils.permission_checks import employee_can
from modules.inventory_audit.stock import planned_products, product_data
from . import service
from .models import InventoryStorageLocation, InventoryStorageTransfer

storage_locations_bp=Blueprint('inventory_storage_locations',__name__,url_prefix='/api/v1/desktop/stock-operations/storage')


def ok(data):return jsonify(success=True,data=data)


def body():
    data=request.get_json(silent=True)
    if not isinstance(data,dict):raise AuditError('بيانات العملية غير صالحة')
    return data


def branch_parameter():
    try:value=int(request.args.get('branch_id',''))
    except (TypeError,ValueError):raise AuditError('اختر فرعاً صحيحاً') from None
    integer(value,minimum=1)
    service._scope(value)
    return value


def location_data(row, branch):
    return {'id':row.id,'key':f'storage:{branch.id}:{row.id if row.id is not None else "main"}',
        'branch_id':branch.id,'branch_name':branch.name,'code':getattr(row,'code','MAIN'),'name':row.name,
        'kind':'main' if row.id is None else row.kind,'is_active':row.is_active,'revision':service.location_revision(row) if row.id is not None else None}


def document_data(row, detail=False):
    user,branch=service._scope(row.branch_id)
    source=service._place(row.branch_id,row.from_location_id,active=False)
    target=service._place(row.branch_id,row.to_location_id,active=False)
    evidence=service.layers(row.id)
    snapshot=json.loads(row.product_snapshot_json or '{}')
    result={'id':row.id,'number':row.number,'branch_id':row.branch_id,'branch_name':branch.name,
        'from_location_id':row.from_location_id,'to_location_id':row.to_location_id,
        'from_name':source.name,'to_name':target.name,'product_id':row.product_id,'variant_name':row.variant_name,
        'product_name':snapshot.get('name') or f'صنف #{row.product_id}','sku':snapshot.get('sku') or '',
        'image_url':snapshot.get('image_url') or '',
        'quantity':row.quantity,'reason':row.reason,'status':row.status,'revision':service.document_revision(row),
        'created_at':row.created_at.isoformat(),'cost':sum(p.quantity*p.unit_cost for p in evidence) if cost_visible() and evidence else None}
    if detail:
        result.update(can_send=row.status=='draft' and employee_can(user,'edit_current_stock'),
            can_receive=row.status=='sent' and employee_can(user,'edit_current_stock'),
            can_cancel=row.status in ('draft','sent') and employee_can(user,'edit_current_stock'))
        result['source']=service.balance(row.branch_id,row.product_id,row.variant_name,row.from_location_id) if row.status=='draft' else None
        if result['source'] is not None and not cost_visible():result['source']['cost']=None
        result['layers']=[{'sequence':p.sequence,'quantity':p.quantity,'unit_cost':p.unit_cost,
            'original_created_at':p.source_created_at.isoformat() if p.source_created_at else None} for p in evidence] if cost_visible() else []
    return result


@storage_locations_bp.get('/meta')
@endpoint
def metadata():
    user=actor();places=[]
    branches=Branch.query.execution_options(skip_branch_scope=True).filter(Branch.id.in_(visible_branches()),Branch.is_active.is_(True)).order_by(Branch.id).all()
    existing=inspect(db.session.connection()).has_table(InventoryStorageLocation.__tablename__)
    for branch in branches:
        places.append(location_data(service._place(branch.id,None),branch))
        if existing:
            rows=InventoryStorageLocation.query.execution_options(skip_branch_scope=True).filter_by(branch_id=branch.id).order_by(InventoryStorageLocation.id).all()
            places.extend(location_data(row,branch) for row in rows)
    return ok({'places':places,'can_edit':employee_can(user,'edit_current_stock'),'show_cost':cost_visible()})


@storage_locations_bp.get('/item')
@endpoint
def item():
    branch=branch_parameter()
    try:
        product_id=int(request.args.get('product_id',''))
        location_id=int(request.args['location_id']) if request.args.get('location_id') else None
    except (TypeError,ValueError):raise AuditError('اختر الصنف والموقع الصحيحين') from None
    data=service.balance(branch,product_id,request.args.get('variant_name',''),location_id)
    if not cost_visible():data['cost']=None
    return ok(data)


@storage_locations_bp.get('/stocks')
@endpoint
def stocks():
    branch=branch_parameter();page,size=paging()
    try:location_id=int(request.args['location_id']) if request.args.get('location_id') else None
    except (TypeError,ValueError):raise AuditError('الموقع غير صالح') from None
    service._place(branch,location_id)
    q=text(request.args.get('q',''),limit=200).casefold()
    candidates=[]
    for product,variants in planned_products({'branch_id':branch},'branch'):
        for variant in variants or [None]:
            name=variant.color_name if variant else ''
            if q and not any(q in str(value or '').casefold() for value in (product.name,product.sku,product.barcode,name)):continue
            candidates.append((product,variant,name))
    rows=[]
    for ordinal,(product,variant,name) in enumerate(candidates[(page-1)*size:page*size],start=(page-1)*size+1):
        line=SimpleNamespace(product_id=product.id,variant_id=variant.id if variant else None,
            variant_name=name,product_snapshot_json='{}')
        row=product_data(line,show_cost=False)
        row.update(service.balance(branch,product.id,name,location_id))
        # List identity is distinct for every variant; mutations use product_id and variant_name.
        row['id']=ordinal
        if not cost_visible():row['cost']=None
        rows.append(row)
    return ok({'items':rows,'total':len(candidates),'page':page,'page_size':size})


@storage_locations_bp.get('/transfers')
@endpoint
def transfers():
    branch=branch_parameter();page,size=paging()
    if not inspect(db.session.connection()).has_table(InventoryStorageTransfer.__tablename__):return ok({'items':[],'total':0,'page':page})
    query=InventoryStorageTransfer.query.filter_by(branch_id=branch)
    total=query.count();rows=query.order_by(InventoryStorageTransfer.id.desc()).offset((page-1)*size).limit(size).all()
    return ok({'items':[document_data(row) for row in rows],'total':total,'page':page})


@storage_locations_bp.get('/transfers/<int:document_id>')
@endpoint
def transfer_detail(document_id):
    # Read permission is sufficient to inspect a document; no mutation permission is inferred.
    if not inspect(db.session.connection()).has_table(InventoryStorageTransfer.__tablename__):raise AuditError('السند غير موجود','not_found',404)
    row=db.session.get(InventoryStorageTransfer,document_id)
    if row is None:raise AuditError('السند غير موجود','not_found',404)
    return ok(document_data(row,True))


@storage_locations_bp.post('/locations')
@endpoint
def create_location():
    data=body();user,branch=service._scope(data.get('branch_id'),write=True)
    def action(user):
        row=service.create_location(branch.id,data.get('code'),data.get('name'),data.get('kind','storage'))
        result=location_data(row,branch)
        return {'id':row.id,'type':'storage_location','location':result},{'after':result}
    return execute(data,branch.id,action)


@storage_locations_bp.post('/locations/<int:location_id>')
@endpoint
def edit_location(location_id):
    data=body();user,branch=service._scope(data.get('branch_id'),write=True)
    def action(user):
        old=location_data(service._place(branch.id,location_id,active=False),branch)
        row=service.update_location(branch.id,location_id,code=data.get('code'),name=data.get('name'),kind=data.get('kind'),
            is_active=data.get('is_active'),revision=data.get('revision'))
        result=location_data(row,branch)
        return {'id':row.id,'type':'storage_location','location':result},{'before':old,'after':result}
    return execute(data,branch.id,action)


@storage_locations_bp.post('/transfers')
@endpoint
def create_transfer():
    data=body();user,branch=service._scope(data.get('branch_id'),write=True)
    def action(user):
        row=service.create_transfer(branch.id,data.get('product_id'),data.get('quantity'),data.get('from_location_id'),
            data.get('to_location_id'),variant_name=data.get('variant_name',''),reason=data.get('reason'))
        result=document_data(row)
        return {'id':row.id,'type':'storage_transfer','document':result},{'after':result}
    return execute(data,branch.id,action)


@storage_locations_bp.post('/transfers/<int:document_id>/<phase>')
@endpoint
def transfer_action(document_id,phase):
    if phase not in ('send','receive','cancel'):raise AuditError('مرحلة نقل غير صالحة')
    data=body();user,branch=service._scope(data.get('branch_id'),write=True)
    # Scope and current permission are checked before replay; revisions are checked only for a new command.
    row=service._document(document_id)
    if row.branch_id!=branch.id:raise AuditError('السند لا يتبع الفرع المحدد','forbidden',403)
    def action(user):
        before=document_data(row)
        if phase=='send':service.send(document_id,data.get('source_revision'),data.get('revision'))
        elif phase=='receive':service.receive(document_id,data.get('revision'))
        else:service.cancel(document_id,data.get('revision'))
        after=document_data(row)
        return {'id':row.id,'type':'storage_transfer','document':after},{'before':before,'after':after,'phase':phase}
    return execute(data,branch.id,action)
