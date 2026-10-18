"""Scoped JSON/print routes for native stock operations; GET never migrates stock."""
from functools import wraps
from flask import jsonify,request,render_template
from sqlalchemy import inspect,or_,update
from sqlalchemy.exc import IntegrityError,OperationalError
from extensions import db
from models.stock_operations import StockReorderRule,InventoryWriteOff
from modules.desktop_api.routes import desktop_api_bp
from modules.finance.common import FinanceError,today
from modules.wholesale.services.helpers import WholesaleError
from utils.financial_period_guard import PeriodClosedError
from .common import actor,require,kind,locations,location,item,stocks,rule,balance,serialize_stock,integer,text,cost_visible,money,AuditError
from .commands import execute
from . import transfers,writeoffs


def endpoint(fn):
    @wraps(fn)
    def run(*args,**kwargs):
        try:
            actor();require('can_manage_inventory')
            return fn(*args,**kwargs)
        except (AuditError,FinanceError) as error:
            db.session.rollback();return jsonify(success=False,error=str(error),code=error.code),error.status
        except (WholesaleError,ValueError,PeriodClosedError) as error:
            db.session.rollback();return jsonify(success=False,error=str(error),code='conflict'),409
        except IntegrityError:
            db.session.rollback();return jsonify(success=False,error='تعارض في المستند؛ حدّث البيانات قبل التسجيل',code='conflict'),409
        except OperationalError:
            db.session.rollback();return jsonify(success=False,error='قاعدة البيانات مشغولة؛ أعد المحاولة بنفس معرّف العملية',code='temporary'),503
    return run


def ok(data):return jsonify(success=True,data=data)


def paging():
    try:page=int(request.args.get('page',1));size=int(request.args.get('page_size',25))
    except (ValueError,TypeError):raise AuditError('اختر صفحة وحجم قائمة صحيحين') from None
    integer(page,minimum=1,maximum=1000000);integer(size,minimum=1,maximum=100)
    return page,size


@desktop_api_bp.get('/stock-operations/meta')
@endpoint
def metadata():
    ledger=kind(request.args.get('kind','branch'));user=actor()
    kinds=['branch']
    from modules.wholesale.guards import is_wholesale_tenant,employee_can_wholesale
    if is_wholesale_tenant() and employee_can_wholesale(user,'wholesale_warehouses'):kinds.append('warehouse')
    from utils.permission_checks import employee_can
    edit=employee_can(user,'edit_current_stock')
    places=locations(ledger)
    return ok({'kind':ledger,'kinds':kinds,'locations':places,'branches':locations('branch'),'today':today().isoformat(),
        'can_create_transfer':edit and len(places)>1,'can_send':edit and user.role=='admin','can_receive':edit,
        'can_writeoff':ledger=='branch' and edit and employee_can(user,'finance.approve') and employee_can(user,'finance.view'),
        'can_edit_rules':employee_can(user,'edit_product'),'can_manage_locations':ledger=='warehouse' and edit,
        'show_cost':cost_visible()})


@desktop_api_bp.get('/stock-operations/item')
@endpoint
def stock_item():
    ledger=kind(request.args.get('kind','branch'));place=location(ledger,request.args.get('location',''))
    try:product_id=int(request.args.get('product_id',''))
    except ValueError:raise AuditError('رقم الصنف غير صحيح') from None
    line,product=item(ledger,place,product_id,request.args.get('variant_name',''))
    return ok(serialize_stock(ledger,place,line,product))


@desktop_api_bp.get('/stock-operations/valuation')
@endpoint
def valuation_preview():
    if not cost_visible():raise AuditError('ليست لديك صلاحية معاينة الكلفة','forbidden',403)
    ledger=kind(request.args.get('kind','branch'));place=location(ledger,request.args.get('location',''))
    try:product_id=int(request.args.get('product_id',''));quantity=int(request.args.get('quantity',''))
    except ValueError:raise AuditError('الصنف والكمية يجب أن يكونا عددين صحيحين') from None
    integer(quantity,minimum=1)
    line,product=item(ledger,place,product_id,request.args.get('variant_name',''))
    physical,available,_,stamp=balance(ledger,place,line,product)
    blocked='الكمية تتجاوز المتاح بعد الحجوزات' if quantity>available else ''
    cost=0;remaining=quantity
    if ledger=='branch':
        from utils.inventory_lots import _lot_query
        lots=_lot_query(product.id,place['branch_id'],line.variant_name or None).all() if inspect(db.session.connection()).has_table('inventory_lot') else []
        if sum(lot.remaining_quantity for lot in lots)!=physical:blocked='راجع أساس كلفة المخزون في الجرد قبل التسجيل'
        if any(lot.unit_cost<0 for lot in lots):blocked='كلفة المخزون غير صالحة؛ راجع أساس التقييم'
        for lot in lots:
            take=min(remaining,lot.remaining_quantity);cost+=take*lot.unit_cost;remaining-=take
            if not remaining:break
        if remaining:blocked=blocked or 'لا تغطي طبقات الكلفة الكمية المطلوبة'
    else:cost=quantity*int(product.buy_price or 0)
    if not 0<=cost<=9223372036854775807:blocked='كلفة السند تتجاوز المجال المسموح'
    if cost>9_000_000_000_000_000:blocked='كلفة التلف تتجاوز مجال المبالغ المحاسبية؛ راجع الكمية والكلفة'
    return ok({'cost':None if blocked else money(cost),'quantity':physical,'available':available,
        'stock_revision':stamp,'eligible':not blocked,'blocked_reason':blocked})


@desktop_api_bp.get('/stock-operations/stocks')
@endpoint
def stock_list():
    ledger=kind(request.args.get('kind','branch'));place=location(ledger,request.args.get('location',''))
    page,size=paging();q=text(request.args.get('q',''),limit=120)
    rows=stocks(ledger,place,q,reorder=request.args.get('reorder')=='1')
    return ok({'items':rows[(page-1)*size:page*size],'total':len(rows),'page':page,'page_size':size,
        'stats':{'items':len(rows),'quantity':sum(row['quantity'] for row in rows),
            'reserved':sum(row['reserved'] for row in rows),'reorder':sum(row['available']<=row['minimum'] for row in rows)}})


@desktop_api_bp.get('/stock-operations/warehouse/movements')
@endpoint
def warehouse_movements():
    from modules.wholesale.models.warehouse import WarehouseMovement
    from models.product import Product
    place=location('warehouse',request.args.get('location',''));page,size=paging()
    if not inspect(db.session.connection()).has_table(WarehouseMovement.__tablename__):
        return ok({'items':[],'total':0,'page':page,'page_size':size})
    query=WarehouseMovement.query.filter_by(warehouse_id=place['warehouse_id'])
    product=request.args.get('product_id')
    if product:
        try:product=int(product)
        except ValueError:raise AuditError('رقم الصنف غير صحيح') from None
        integer(product,minimum=1);query=query.filter_by(product_id=product)
    total=query.count();items=[]
    for row in query.order_by(WarehouseMovement.created_at.desc(),WarehouseMovement.id.desc()).offset((page-1)*size).limit(size):
        product=Product.query.execution_options(skip_branch_scope=True).filter_by(id=row.product_id).first()
        document='transfers' if row.reference_type=='warehouse_transfer' else 'writeoffs' if row.reference_type=='inventory_writeoff' else None
        items.append({'id':row.id,'product_id':row.product_id,'product_name':product.name if product else 'صنف مؤرشف',
            'quantity':row.quantity,'before':row.quantity_before,'after':row.quantity_after,'operation':row.movement_type,
            'created_at':row.created_at.isoformat()+'Z','note':row.note or '',
            'document':document,'document_id':row.reference_id if document else None,
            'cost':money(abs(row.quantity)*int(row.unit_cost or 0)) if cost_visible() else None})
    return ok({'items':items,'total':total,'page':page,'page_size':size})


@desktop_api_bp.get('/stock-operations/transfers')
@endpoint
def transfer_list():
    ledger=kind(request.args.get('kind','branch'));page,size=paging()
    status=text(request.args.get('status',''),limit=12)
    if status and status not in ('draft','approved','sent','received','cancelled'):raise AuditError('حالة التحويل غير صحيحة')
    query=transfers.listing(ledger,status,text(request.args.get('q',''),limit=80))
    selected=request.args.get('location')
    if selected and not isinstance(query,list):
        place=location(ledger,selected);table=transfers.model(ledger)
        key=place['warehouse_id'] or place['branch_id']
        source=table.from_branch_id if ledger=='branch' else table.from_warehouse_id
        target=table.to_branch_id if ledger=='branch' else table.to_warehouse_id
        query=query.filter(or_(source==key,target==key))
    if isinstance(query,list):return ok({'items':[],'total':0,'page':page,'page_size':size})
    return ok({'items':[transfers.serialize(row,ledger) for row in query.offset((page-1)*size).limit(size)],
        'total':query.count(),'page':page,'page_size':size})


@desktop_api_bp.get('/stock-operations/<ledger>/transfers/<int:document_id>')
@endpoint
def transfer_detail(ledger,document_id):return ok(transfers.serialize(transfers.get(ledger,document_id),ledger,True))


@desktop_api_bp.post('/stock-operations/<ledger>/transfers')
@endpoint
def transfer_create(ledger):
    kind(ledger);require('edit_current_stock');body=request.get_json(silent=True)
    if not isinstance(body,dict):raise AuditError('بيانات التحويل غير صحيحة')
    place=location(ledger,body.get('from_location'))
    location(ledger,body.get('to_location'))
    return execute(body,place['branch_id'],lambda user:transfers.create(ledger,body,user))


@desktop_api_bp.post('/stock-operations/<ledger>/transfers/<int:document_id>/<action>')
@endpoint
def transfer_phase(ledger,document_id,action):
    extra=('approve','reject','receive_partial','resolve')
    if action not in ('send','receive','cancel')+extra:raise AuditError('إجراء التحويل غير صالح')
    require('edit_current_stock');row=transfers.get(ledger,document_id)
    source,target=transfers.places(row,ledger)
    receiver_side=action in ('receive','reject','receive_partial','resolve')
    place=location(ledger,target if receiver_side else source)
    if action in extra:
        from . import transfer_partial
        body=request.get_json(silent=True)
        return execute(body,place['branch_id'],lambda user:transfer_partial.run(ledger,row,action,body,user))
    if action!='receive' and actor().role!='admin':raise AuditError('هذا الإجراء للمدير المخول','forbidden',403)
    body=request.get_json(silent=True)
    return execute(body,place['branch_id'],lambda user:transfers.phase(ledger,row,action,body,user))


@desktop_api_bp.get('/stock-operations/writeoffs')
@endpoint
def writeoff_list():
    ledger=kind(request.args.get('kind','branch'));place=location(ledger,request.args.get('location',''))
    page,size=paging()
    if not inspect(db.session.connection()).has_table(InventoryWriteOff.__tablename__):
        return ok({'items':[],'total':0,'page':page,'page_size':size})
    query=InventoryWriteOff.query.execution_options(skip_branch_scope=True).filter_by(ledger_kind=ledger,
        branch_id=place['branch_id'],warehouse_id=place['warehouse_id'],sealed=True)
    q=text(request.args.get('q',''),limit=80)
    if q:query=query.filter(InventoryWriteOff.number.contains(q,autoescape=True))
    return ok({'items':[writeoffs.serialize(row) for row in query.order_by(InventoryWriteOff.id.desc()).offset((page-1)*size).limit(size)],
        'total':query.count(),'page':page,'page_size':size})


@desktop_api_bp.get('/stock-operations/writeoffs/<int:document_id>')
@endpoint
def writeoff_detail(document_id):return ok(writeoffs.serialize(writeoffs.get(document_id)))


def writeoff_permissions():
    require('edit_current_stock');require('finance.approve');require('finance.view')


@desktop_api_bp.post('/stock-operations/<ledger>/writeoffs')
@endpoint
def writeoff_create(ledger):
    kind(ledger);writeoff_permissions();body=request.get_json(silent=True)
    if ledger=='warehouse':raise AuditError('تلف مخازن الجملة يحتاج أساس كلفة مستقل ومراجع قبل الربط بالحسابات','valuation_review_required',409)
    if not isinstance(body,dict):raise AuditError('بيانات التلف غير صحيحة')
    place=location(ledger,body.get('location_key'))
    return execute(body,place['branch_id'],lambda user:writeoffs.post(ledger,body,user))


@desktop_api_bp.post('/stock-operations/writeoffs/<int:document_id>/reverse')
@endpoint
def writeoff_reverse(document_id):
    writeoff_permissions();row=writeoffs.get(document_id)
    body=request.get_json(silent=True)
    return execute(body,row.branch_id,lambda user:writeoffs.post(row.ledger_kind,body,user,row))


@desktop_api_bp.post('/stock-operations/<ledger>/rules')
@endpoint
def reorder_update(ledger):
    kind(ledger);require('edit_product');body=request.get_json(silent=True)
    if not isinstance(body,dict):raise AuditError('بيانات حد الطلب غير صحيحة')
    place=location(ledger,body.get('location_key'));line,product=item(ledger,place,body.get('product_id'),body.get('variant_name',''))
    minimum=integer(body.get('minimum'));target=integer(body.get('target'))
    if target<minimum:raise AuditError('الرصيد المستهدف لا يقل عن حد الطلب')
    version=integer(body.get('rule_version'))
    reason=text(body.get('reason',''),required=True,limit=500)
    def action(user):
        previous=rule(ledger,place,line,product)
        if version!=previous[2]:raise AuditError('تغير حد الطلب؛ حدّث الصنف','conflict',409)
        query=StockReorderRule.query.execution_options(skip_branch_scope=True).filter_by(ledger_kind=ledger,
            location_id=place['warehouse_id'] or place['branch_id'],product_id=product.id,variant_name=line.variant_name)
        row=query.first()
        if row:
            changed=query.filter(StockReorderRule.version==version).update({'minimum':minimum,'target':target,
                'version':version+1,'employee_id':user.id},synchronize_session=False)
            if changed!=1:raise AuditError('تغير حد الطلب؛ حدّث الصنف','conflict',409)
            db.session.expire(row)
        else:
            row=StockReorderRule(ledger_kind=ledger,location_id=place['warehouse_id'] or place['branch_id'],
                branch_id=place['branch_id'],product_id=product.id,variant_name=line.variant_name,
                minimum=minimum,target=target,version=1,employee_id=user.id)
            db.session.add(row);db.session.flush()
        return {'id':row.id,'type':'stock_reorder_rule','ledger_kind':ledger,'status':'saved'}, {
            'reason':reason,'before':{'minimum':previous[0],'target':previous[1],'version':previous[2]},
            'after':{'minimum':minimum,'target':target,'version':version+1},'product_id':product.id,'variant_name':line.variant_name}
    return execute(body,place['branch_id'],action)


@desktop_api_bp.post('/stock-operations/warehouse/locations')
@endpoint
def warehouse_create():
    kind('warehouse');require('edit_current_stock');body=request.get_json(silent=True)
    if not isinstance(body,dict):raise AuditError('بيانات المخزن غير صحيحة')
    branch=location('branch',f"branch:{integer(body.get('branch_id'),minimum=1)}")
    name=text(body.get('name',''),required=True,limit=150);code=text(body.get('code',''),required=True,limit=60)
    reason=text(body.get('reason',''),required=True,limit=1000)
    warehouse_kind=body.get('warehouse_kind','main')
    if warehouse_kind not in ('main','damaged','returns'):raise AuditError('نوع المخزن غير صالح')
    def action(user):
        from modules.wholesale.models.warehouse import Warehouse
        from modules.wholesale.services.warehouse_service import create_warehouse
        if Warehouse.query.filter(db.func.lower(Warehouse.code)==code.lower(),Warehouse.deleted_at.is_(None)).first():
            raise AuditError('رمز المخزن مستخدم؛ اختر رمزاً آخر','conflict',409)
        row=create_warehouse(None,code=code,name=name,kind=warehouse_kind,branch_id=branch['branch_id'])
        db.session.flush()
        return {'id':row.id,'type':'warehouse','ledger_kind':'warehouse','status':'saved'}, {'code':code,'name':name,'kind':warehouse_kind,'reason':reason}
    return execute(body,branch['branch_id'],action)


@desktop_api_bp.get('/stock-operations/<ledger>/<document_type>/<int:document_id>/print')
@endpoint
def document_print(ledger,document_type,document_id):
    kind(ledger)
    if document_type=='transfers':data=transfers.serialize(transfers.get(ledger,document_id),ledger,True)
    elif document_type=='writeoffs':
        row=writeoffs.get(document_id)
        if row.ledger_kind!=ledger:raise AuditError('نوع مخزون السند مختلف')
        data=writeoffs.serialize(row)
    else:raise AuditError('المستند المخزني غير صحيح')
    return render_template('inventory/stock_document_print.html',data=data,document_type=document_type,actor=actor().name)

