"""Core location balances and internal FIFO transfers. The caller owns commit/rollback."""
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4
from sqlalchemy import inspect, update
from extensions import db
from models.branch import Branch, BranchStock
from models.inventory_lot import InventoryLot
from models.product import Product
from models.product_color_variant import ProductColorVariant
from modules.inventory_audit.common import AuditError, actor, dumps, fingerprint, integer, text, visible_branches
from utils.permission_checks import employee_can
from utils.inventory_lots import _lot_query
from utils.branch_stock_service import _branch_product_id, get_branch_stock, receive_stock, deduct_stock
from utils.product_color_service import get_branch_product_colors, sync_product_total_from_colors
from utils.stock_transfer_state import transition
from .models import InventoryStorageLocation, InventoryLotPlacement, InventoryStorageTransfer, InventoryStorageTransferLayer,InventoryOrderItemLocation
from .schema import ensure_schema


def _scope(branch_id, *, write=False):
    integer(branch_id, minimum=1)
    user=actor()
    if not employee_can(user, 'can_manage_inventory') or (write and not employee_can(user, 'edit_current_stock')):
        raise AuditError('ليست لديك صلاحية إدارة مواقع المخزون', 'forbidden', 403)
    branch=Branch.query.execution_options(skip_branch_scope=True).filter_by(id=branch_id, is_active=True).first()
    if branch is None or branch_id not in visible_branches():
        raise AuditError('الفرع غير متاح ضمن صلاحياتك', 'forbidden', 403)
    return user, branch


def _place(branch_id, location_id, *, active=True):
    if location_id is None:
        return SimpleNamespace(id=None, branch_id=branch_id, name='الموقع الأساسي للفرع', kind='sales', is_active=True)
    integer(location_id, minimum=1)
    if not inspect(db.session.connection()).has_table(InventoryStorageLocation.__tablename__):
        raise AuditError('المخزن غير موجود', 'not_found', 404)
    row=InventoryStorageLocation.query.execution_options(skip_branch_scope=True).filter_by(id=location_id, branch_id=branch_id).first()
    if row is None or (active and not row.is_active):
        raise AuditError('المخزن غير متاح في هذا الفرع', 'not_found', 404)
    return row


def _product(branch_id, product_id, variant_name):
    integer(product_id, minimum=1)
    variant_name=text(variant_name, limit=80)
    local_id=_branch_product_id(branch_id, product_id)
    row=Product.query.execution_options(skip_branch_scope=True).filter_by(id=local_id, active=True).first()
    if row is None:
        raise AuditError('الصنف غير متاح في الفرع', 'not_found', 404)
    choices=get_branch_product_colors(local_id, branch_id)
    if (choices and variant_name not in {choice['name'] for choice in choices}) or (not choices and variant_name):
        raise AuditError('اختر خيار الصنف الصحيح')
    return row, variant_name


def _lots(product_id, branch_id, variant_name, *, lock=False):
    if not inspect(db.session.connection()).has_table(InventoryLot.__tablename__):
        return [], {}
    query=_lot_query(product_id, branch_id, variant_name or None)
    rows=(query.with_for_update() if lock else query).populate_existing().all()
    placement={}
    if rows and inspect(db.session.connection()).has_table(InventoryLotPlacement.__tablename__):
        placement={row.inventory_lot_id:row.location_id for row in InventoryLotPlacement.query.filter(
            InventoryLotPlacement.inventory_lot_id.in_([lot.id for lot in rows])).all()}
    return rows, placement


def _physical(product_id, branch_id, variant_name):
    if variant_name:
        return next((row['qty'] for row in get_branch_product_colors(product_id, branch_id) if row['name']==variant_name), 0)
    return get_branch_stock(branch_id, product_id)


def balance(branch_id, product_id, variant_name='', location_id=None):
    _scope(branch_id)
    place=_place(branch_id, location_id)
    product, variant=_product(branch_id, product_id, variant_name)
    lots, placement=_lots(product.id, branch_id, variant)
    physical=_physical(product.id, branch_id, variant)
    allocated=sum(lot.remaining_quantity for lot in lots if lot.id in placement)
    quantity=sum(lot.remaining_quantity for lot in lots if placement.get(lot.id)==location_id) if location_id is not None else physical-allocated
    valid=quantity>=0 and sum(lot.remaining_quantity for lot in lots)==physical and all(isinstance(lot.unit_cost,int) and lot.unit_cost>=0 for lot in lots)
    selected=[lot for lot in lots if placement.get(lot.id)==location_id]
    # Old reservations have no site provenance: preserve their protection until that provenance is migrated.
    stock=BranchStock.query.filter_by(branch_id=branch_id, product_id=product.id).first()
    from utils.desktop_stock_reservations import reserved_for_stock
    reserved=reserved_for_stock(stock.id) if stock else 0
    movable=max(0, quantity-reserved)
    return {'product_id':product.id,'variant_name':variant,'location_id':location_id,'quantity':quantity,
        'available':movable if place.kind in ('sales','storage') else 0,'movable':movable,
        'basis_valid':valid,'cost':sum(lot.remaining_quantity*lot.unit_cost for lot in selected) if valid else None,
        'revision':fingerprint({'physical':physical,'reserved':reserved,'site':(place.id,place.kind,place.is_active),
            'layers':[(lot.id,lot.remaining_quantity,lot.unit_cost,lot.created_at.isoformat() if lot.created_at else None,placement.get(lot.id)) for lot in lots]})}


def create_location(branch_id, code, name, kind='storage'):
    user, branch=_scope(branch_id, write=True)
    code=text(code, limit=60, required=True).upper();name=text(name, limit=150, required=True)
    if kind not in ('storage','sales','damaged','returns'):
        raise AuditError('اختر نوع موقع صحيحاً')
    ensure_schema()
    if InventoryStorageLocation.query.filter_by(branch_id=branch_id, code=code).first():
        raise AuditError('رمز المخزن مستخدم بهذا الفرع', 'duplicate', 409)
    row=InventoryStorageLocation(branch_id=branch_id,code=code,name=name,kind=kind,created_by=user.id)
    db.session.add(row);db.session.flush()
    return row


def location_revision(row):
    return fingerprint({'id':row.id,'branch':row.branch_id,'code':row.code,'name':row.name,'kind':row.kind,'active':row.is_active})


def update_location(branch_id, location_id, *, code, name, kind, is_active, revision):
    _scope(branch_id,write=True)
    row=_place(branch_id,location_id,active=False)
    if location_id is None:raise AuditError('الموقع الأساسي ثابت؛ لا يمكن تعطيله')
    if location_revision(row)!=revision:raise AuditError('تغيرت بيانات المخزن؛ حدّثها قبل الحفظ', 'source_changed', 409)
    code=text(code,limit=60,required=True).upper();name=text(name,limit=150,required=True)
    if kind not in ('storage','sales','damaged','returns') or not isinstance(is_active,bool):raise AuditError('بيانات المخزن غير صالحة')
    if kind!=row.kind or not is_active:
        occupied=db.session.query(InventoryLot.id).join(InventoryLotPlacement,
            InventoryLotPlacement.inventory_lot_id==InventoryLot.id).filter(
                InventoryLotPlacement.location_id==location_id,InventoryLot.remaining_quantity>0).first()
        pending=InventoryStorageTransfer.query.filter(InventoryStorageTransfer.branch_id==branch_id,
            InventoryStorageTransfer.status.in_(('draft','sent')),
            (InventoryStorageTransfer.from_location_id==location_id)|(InventoryStorageTransfer.to_location_id==location_id)).first()
        pending_order=None
        if inspect(db.session.connection()).has_table(InventoryOrderItemLocation.__tablename__):
            from models.order_item import OrderItem
            from models.invoice import Invoice
            pending_order=db.session.query(InventoryOrderItemLocation.order_item_id).join(OrderItem,
                OrderItem.id==InventoryOrderItemLocation.order_item_id).join(Invoice,Invoice.id==OrderItem.invoice_id).filter(
                InventoryOrderItemLocation.location_id==location_id,Invoice.stock_is_deducted.is_(False),
                Invoice.status.notin_(('راجع','ملغي'))).first()
        if occupied or pending or pending_order:raise AuditError('انقل الرصيد وأكمل التحويلات والطلبات المعلقة قبل تغيير النوع أو التعطيل', 'location_in_use', 409)
    duplicate=InventoryStorageLocation.query.filter(InventoryStorageLocation.branch_id==branch_id,
        InventoryStorageLocation.code==code,InventoryStorageLocation.id!=location_id).first()
    if duplicate:raise AuditError('رمز المخزن مستخدم بهذا الفرع', 'duplicate', 409)
    changed=db.session.execute(update(InventoryStorageLocation).where(
        InventoryStorageLocation.id==row.id,InventoryStorageLocation.branch_id==branch_id,
        InventoryStorageLocation.code==row.code,InventoryStorageLocation.name==row.name,
        InventoryStorageLocation.kind==row.kind,InventoryStorageLocation.is_active==row.is_active
    ).values(code=code,name=name,kind=kind,is_active=is_active).execution_options(synchronize_session=False))
    if changed.rowcount!=1:
        raise AuditError('تغيرت بيانات المخزن؛ حدّثها قبل الحفظ', 'source_changed', 409)
    db.session.expire(row)
    return row


def create_transfer(branch_id, product_id, quantity, from_location_id, to_location_id, *, variant_name='', reason):
    user, branch=_scope(branch_id, write=True)
    integer(quantity, minimum=1);reason=text(reason, required=True)
    _place(branch_id, from_location_id);_place(branch_id, to_location_id)
    if from_location_id==to_location_id:
        raise AuditError('اختر موقعين مختلفين')
    product, variant=_product(branch_id,product_id,variant_name)
    from modules.inventory_audit.stock import product_data
    option=ProductColorVariant.query.filter_by(product_id=product.id,color_name=variant).first() if variant else None
    snapshot=product_data(SimpleNamespace(product_id=product.id,variant_id=option.id if option else None,
        variant_name=variant,product_snapshot_json='{}'),show_cost=False)
    ensure_schema()
    row=InventoryStorageTransfer(number='ST-'+uuid4().hex[:12].upper(),branch_id=branch_id,
        product_id=product.id,variant_name=variant,product_snapshot_json=dumps(snapshot),quantity=quantity,from_location_id=from_location_id,
        to_location_id=to_location_id,reason=reason,created_by=user.id)
    db.session.add(row);db.session.flush()
    return row


def layers(document_id, phase='send'):
    return InventoryStorageTransferLayer.query.filter_by(transfer_id=document_id,phase=phase).order_by(
        InventoryStorageTransferLayer.sequence).all()


def _movement(document, phase, proof):
    from utils.stock_movement_guard import claim_stock_movement
    total=sum(row.quantity*row.unit_cost for row in proof)
    claim=claim_stock_movement(f'storage-transfer:{document.id}:{phase}',movement_type=f'storage_transfer_{phase}',
        direction='out' if phase=='send' else 'in',product_id=document.product_id,branch_id=document.branch_id,
        quantity=document.quantity,unit_cost=total//document.quantity,source_type='inventory_storage_transfer',source_id=document.id,
        reversal_of_key=f'storage-transfer:{document.id}:send' if phase=='cancel' else None,
        details={'from_location_id':document.from_location_id,'to_location_id':document.to_location_id,
            'variant_color':document.variant_name or None,'reason':document.reason,'exact_total_cost':total,
            'valuation_layers':[(row.inventory_lot_id,row.quantity,row.unit_cost) for row in proof]})
    if not claim.applied:raise AuditError('حركة النقل موجودة دون حالة متوافقة؛ راجع السند', 'already_posted', 409)
    claim.movement.total_cost=total
    return {'movement_id':claim.movement.id,'source_type':'inventory_storage_transfer','source_id':document.id,
        'reason':document.reason,'operation':f'storage_transfer_{phase}'}


def _adjust(document, quantity, audit_context):
    if not document.variant_name:
        if quantity>0: receive_stock(document.branch_id,document.product_id,quantity,audit_context=audit_context)
        else: deduct_stock(document.branch_id,document.product_id,-quantity,audit_context=audit_context)
        return
    row=ProductColorVariant.query.filter_by(product_id=document.product_id,color_name=document.variant_name).with_for_update().populate_existing().one()
    if row.quantity+quantity<0: raise AuditError('رصيد الخيار غير كافٍ')
    before=row.quantity
    changed=db.session.execute(update(ProductColorVariant).where(ProductColorVariant.id==row.id,
        ProductColorVariant.quantity==row.quantity).values(quantity=ProductColorVariant.quantity+quantity).execution_options(synchronize_session=False))
    if changed.rowcount!=1:raise AuditError('تغيّر مخزون الخيار؛ حدّث السند', 'source_changed', 409)
    db.session.expire(row)
    sync_product_total_from_colors(document.product_id,branch_id=document.branch_id)
    from utils.inventory_audit_trail import record_stock_mutation
    record_stock_mutation(product_id=document.product_id,branch_id=document.branch_id,before_quantity=before,
        after_quantity=before+quantity,operation=audit_context['operation'],audit_context={**audit_context,
            'metadata':{'variant_id':row.id,'variant_name':document.variant_name}})


def _document(document_id):
    integer(document_id, minimum=1)
    if not inspect(db.session.connection()).has_table(InventoryStorageTransfer.__tablename__):
        raise AuditError('السند غير موجود', 'not_found', 404)
    row=db.session.get(InventoryStorageTransfer,document_id)
    if row is None:raise AuditError('السند غير موجود', 'not_found', 404)
    _scope(row.branch_id, write=True)
    return row


def document_revision(document):
    source=_place(document.branch_id,document.from_location_id,active=False)
    target=_place(document.branch_id,document.to_location_id,active=False)
    return fingerprint({'id':document.id,'branch':document.branch_id,'source':(source.id,source.name,source.kind,source.is_active),
        'target':(target.id,target.name,target.kind,target.is_active),'product':document.product_id,
        'variant':document.variant_name,'snapshot':document.product_snapshot_json,'quantity':document.quantity,'reason':document.reason,'status':document.status})


def _revision(document, expected):
    if document_revision(document)!=expected:
        raise AuditError('تغيرت بيانات السند؛ افتحه وحدّث المراجعة', 'source_changed', 409)


def send(document_id, expected_source_revision, expected_document_revision):
    document=_document(document_id)
    _revision(document, expected_document_revision)
    _place(document.branch_id,document.from_location_id);_place(document.branch_id,document.to_location_id)
    state=balance(document.branch_id,document.product_id,document.variant_name,document.from_location_id)
    if state['revision']!=expected_source_revision:raise AuditError('تغيّر رصيد المصدر؛ حدّث السند', 'source_changed', 409)
    if not state['basis_valid']:raise AuditError('راجع تطابق دفعات الكلفة مع رصيد الفرع قبل النقل', 'valuation_review_required', 409)
    if state['movable']<document.quantity:raise AuditError('المتاح في الموقع لا يغطي كمية النقل', 'insufficient_stock', 409)
    lots, placement=_lots(document.product_id,document.branch_id,document.variant_name,lock=True)
    remaining=document.quantity;selected=[]
    for lot in lots:
        if placement.get(lot.id)!=document.from_location_id:continue
        take=min(remaining,lot.remaining_quantity)
        if take:selected.append((lot,take));remaining-=take
        if not remaining:break
    if remaining:raise AuditError('دفعات الموقع لا تغطي الكمية', 'valuation_review_required', 409)
    if sum(lot.unit_cost*take for lot,take in selected)>9_000_000_000_000_000:
        raise AuditError('قيمة النقل خارج المجال المحاسبي')
    with db.session.begin_nested():
        transition(document,{'draft'},'sent')
        for sequence,(lot,take) in enumerate(selected):
            changed=db.session.execute(update(InventoryLot).where(InventoryLot.id==lot.id,
                InventoryLot.remaining_quantity==lot.remaining_quantity).values(
                    remaining_quantity=InventoryLot.remaining_quantity-take).execution_options(synchronize_session=False))
            if changed.rowcount!=1:raise AuditError('تغيّرت دفعة المخزون؛ حدّث المصدر', 'source_changed', 409)
            db.session.expire(lot)
            db.session.add(InventoryStorageTransferLayer(transfer_id=document.id,phase='send',sequence=sequence,
                inventory_lot_id=lot.id,location_id=document.from_location_id,quantity=take,unit_cost=lot.unit_cost,source_created_at=lot.created_at))
        db.session.flush()
        _adjust(document,-document.quantity,_movement(document,'send',layers(document.id)))
        document.sent_at=datetime.utcnow();db.session.flush()
    return document


def _settle(document_id, phase, expected_document_revision):
    document=_document(document_id)
    _revision(document, expected_document_revision)
    target=document.to_location_id if phase=='receive' else document.from_location_id
    _place(document.branch_id,target)
    original=layers(document.id)
    if sum(row.quantity for row in original)!=document.quantity:raise AuditError('دليل النقل غير مكتمل', 'valuation_review_required', 409)
    with db.session.begin_nested():
        transition(document,{'sent'},'received' if phase=='receive' else 'cancelled')
        for proof in original:
            old=db.session.get(InventoryLot,proof.inventory_lot_id)
            if old is None or old.product_id!=document.product_id or old.unit_cost!=proof.unit_cost or old.branch_id!=document.branch_id:
                raise AuditError('دفعة المصدر تغيّرت؛ راجع دليل النقل', 'source_changed', 409)
            if phase=='receive':
                lot=InventoryLot(product_id=document.product_id,branch_id=document.branch_id,variant_color=document.variant_name or None,
                    quantity=proof.quantity,remaining_quantity=proof.quantity,unit_cost=proof.unit_cost,created_at=proof.source_created_at)
                db.session.add(lot);db.session.flush()
                if proof.source_created_at is None:lot.created_at=None
                if target is not None:db.session.add(InventoryLotPlacement(inventory_lot_id=lot.id,location_id=target))
            else:
                lot=old
                changed=db.session.execute(update(InventoryLot).where(InventoryLot.id==lot.id,
                    InventoryLot.remaining_quantity==lot.remaining_quantity).values(
                        remaining_quantity=InventoryLot.remaining_quantity+proof.quantity).execution_options(synchronize_session=False))
                if changed.rowcount!=1:raise AuditError('تغيّر رصيد المصدر؛ حدّث السند', 'source_changed', 409)
                db.session.expire(lot)
            db.session.add(InventoryStorageTransferLayer(transfer_id=document.id,phase=phase,sequence=proof.sequence,
                inventory_lot_id=lot.id,location_id=target,quantity=proof.quantity,unit_cost=proof.unit_cost,source_created_at=proof.source_created_at))
        _adjust(document,document.quantity,_movement(document,phase,original))
        if phase=='receive':document.received_at=datetime.utcnow()
        else:document.cancelled_at=datetime.utcnow()
        db.session.flush()
    return document


def receive(document_id, expected_document_revision):return _settle(document_id,'receive',expected_document_revision)


def cancel(document_id, expected_document_revision):
    document=_document(document_id)
    _revision(document, expected_document_revision)
    if document.status=='draft':
        transition(document,{'draft'},'cancelled');document.cancelled_at=datetime.utcnow()
        return document
    return _settle(document_id,'cancel',expected_document_revision)


def in_transit_value(branch_id):
    _scope(branch_id)
    from .valuation import in_transit_value as value
    return value([branch_id])
