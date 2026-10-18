import json
from datetime import datetime,date
from uuid import uuid4
from sqlalchemy import inspect,update
from extensions import db
from models.inventory_lot import InventoryLot
from models.journal_entry import JournalEntry
from models.stock_operations import InventoryWriteOff
from modules.finance import ledger
from modules.finance.common import today,money as financial_money
from utils.inventory_lots import _lot_query
from utils.financial_period_guard import assert_date_period_open
from .common import location,item,balance,integer,text,cost_visible,fingerprint,money,AuditError


def serialize(row):
    from models.product import Product
    product=Product.query.execution_options(skip_branch_scope=True).filter_by(id=row.product_id).first()
    reverse=InventoryWriteOff.query.execution_options(skip_branch_scope=True).filter_by(reversal_of_id=row.id,sealed=True).first()
    return {'id':row.id,'number':row.number,'ledger_kind':row.ledger_kind,'location_key':f'warehouse:{row.warehouse_id}' if row.warehouse_id else f'branch:{row.branch_id}',
        'product_id':row.product_id,'product_name':product.name if product else '—','variant_name':row.variant_name,
        'quantity':row.quantity,'cost':money(row.cost) if cost_visible() else None,'reason':row.reason,
        'location_name':location(row.ledger_kind,f'warehouse:{row.warehouse_id}' if row.warehouse_id else f'branch:{row.branch_id}')['name'],
        'business_date':row.business_date.isoformat(),'before_quantity':row.before_quantity,'after_quantity':row.after_quantity,
        'reversal_of_id':row.reversal_of_id,'status':'reversal' if row.reversal_of_id else 'reversed' if reverse else 'posted',
        'revision':fingerprint({'id':row.id,'reverse':reverse.id if reverse else None,'movement':row.movement_id,'journal':row.journal_entry_id})}


def get(document_id):
    integer(document_id,minimum=1)
    row=InventoryWriteOff.query.execution_options(skip_branch_scope=True).filter_by(id=document_id,sealed=True).first()
    if not row:raise AuditError("سند التلف غير موجود","not_found",404)
    location(row.ledger_kind,f'warehouse:{row.warehouse_id}' if row.warehouse_id else f'branch:{row.branch_id}')
    return row


def _take(line,quantity,physical):
    if not inspect(db.session.connection()).has_table('inventory_lot'):
        raise AuditError("راجع كلفة المخزون في الجرد قبل تسجيل التلف","valuation_conflict",409)
    lots=_lot_query(line.product_id,line.branch_id,line.variant_name or None).with_for_update().populate_existing().all()
    if sum(lot.remaining_quantity for lot in lots)!=physical:
        raise AuditError("طبقات الكلفة لا تطابق الرصيد؛ راجع أساس التقييم قبل التلف","valuation_conflict",409)
    if any(lot.unit_cost<0 for lot in lots):raise AuditError("كلفة دفعة مخزون غير صالحة؛ راجع التقييم")
    remaining=quantity;proof=[]
    for lot in lots:
        take=min(remaining,lot.remaining_quantity)
        if not take:continue
        changed=db.session.execute(update(InventoryLot).where(InventoryLot.id==lot.id,
            InventoryLot.remaining_quantity==lot.remaining_quantity).values(
            remaining_quantity=InventoryLot.remaining_quantity-take).execution_options(synchronize_session=False))
        if changed.rowcount!=1:raise AuditError("تغيرت طبقات الكلفة؛ حدّث المخزون","conflict",409)
        db.session.expire(lot)
        proof.append({'lot_id':lot.id,'quantity':take,'unit_cost':lot.unit_cost});remaining-=take
        if not remaining:break
    if remaining:raise AuditError("الكمية المطلوبة لا تغطيها كلفة موثقة","valuation_conflict",409)
    return proof


def _restore(line,proof):
    for saved in proof:
        lot=db.session.get(InventoryLot,saved['lot_id'])
        if not lot or (lot.product_id,lot.branch_id,lot.variant_color or '',lot.unit_cost)!=(line.product_id,line.branch_id,line.variant_name,saved['unit_cost']):
            raise AuditError("مصدر كلفة التلف تغير؛ لم يسجل العكس","valuation_conflict",409)
        if lot.remaining_quantity+saved['quantity']>lot.quantity:
            raise AuditError("طبقة المصدر تغيرت؛ راجع أساس التقييم قبل عكس التلف","valuation_conflict",409)
        changed=db.session.execute(update(InventoryLot).where(InventoryLot.id==lot.id,
            InventoryLot.remaining_quantity==lot.remaining_quantity).values(
            remaining_quantity=InventoryLot.remaining_quantity+saved['quantity']).execution_options(synchronize_session=False))
        if changed.rowcount!=1:raise AuditError("تغيرت الكلفة؛ حدّث السند","conflict",409)
        db.session.expire(lot)


def post(ledger_kind,body,user,original=None):
    place=location(ledger_kind,body.get('location_key'))
    reason=text(body.get('reason',''),required=True,limit=1000)
    if len(reason)<3:raise AuditError("اكتب سبباً واضحاً من ثلاثة أحرف على الأقل")
    product_id=original.product_id if original else body.get('product_id')
    variant=original.variant_name if original else body.get('variant_name','')
    line,product=item(ledger_kind,place,product_id,variant)
    quantity=original.quantity if original else integer(body.get('quantity'),minimum=1)
    physical,available,_,stamp=balance(ledger_kind,place,line,product)
    if original:
        if serialize(original)['status']!='posted' or body.get('revision')!=serialize(original)['revision']:
            raise AuditError("سند التلف تغير أو سبق عكسه؛ حدّث السند","conflict",409)
        if body.get('location_key')!=serialize(original)['location_key']:
            raise AuditError("العكس يرجع لنفس موقع التلف الأصلي")
    elif body.get('stock_revision')!=stamp:raise AuditError("المخزون تغير منذ فتح النموذج؛ حدّث الكمية","conflict",409)
    if not original and quantity>available:raise AuditError("التلف يتجاوز المتاح بعد الحجوزات","reserved_stock",409)
    try:on=date.fromisoformat(body.get('business_date') or today().isoformat())
    except (TypeError,ValueError):raise AuditError("اختر تاريخاً صحيحاً") from None
    if on>today():raise AuditError("لا يمكن تسجيل تلف بتاريخ مستقبلي")
    assert_date_period_open(on,"عكس تلف مخزون" if original else "تسجيل تلف مخزون")
    inventory,loss=ledger.account('inventory'),ledger.account('inventory_loss')
    if inventory.id==loss.id or inventory.account_type!='asset' or loss.account_type!='expense':
        raise AuditError("ربط حساب المخزون والتلف غير صالح؛ راجع الحسابات")
    proof=json.loads(original.layers_json) if original else []
    if ledger_kind=='branch':
        if original:
            if sum(lot.remaining_quantity for lot in _lot_query(line.product_id,line.branch_id,line.variant_name or None))!=physical:
                raise AuditError("رصيد الكلفة لا يطابق الموجود؛ راجع التقييم قبل عكس التلف","valuation_conflict",409)
            _restore(line,proof)
        else:proof=_take(line,quantity,physical)
    elif not original:proof=[{'quantity':quantity,'unit_cost':int(product.buy_price or 0)}]
    cost=sum(saved['quantity']*saved['unit_cost'] for saved in proof)
    if not 0<=cost<=9223372036854775807:raise AuditError("كلفة السند تتجاوز المجال المسموح؛ راجع الكمية والكلفة")
    financial_money(cost,minimum=0)
    document=InventoryWriteOff(number=f"{'WOR' if original else 'WO'}-{uuid4().hex[:12].upper()}",
        ledger_kind=ledger_kind,branch_id=place['branch_id'],warehouse_id=place['warehouse_id'],product_id=product.id,
        variant_name=line.variant_name,quantity=quantity,cost=cost,reason=reason,layers_json=json.dumps(proof),
        before_quantity=physical,after_quantity=physical+(quantity if original else -quantity),
        reversal_of_id=original.id if original else None,employee_id=user.id,business_date=on,sealed=False)
    db.session.add(document);db.session.flush()
    delta=quantity if original else -quantity
    if ledger_kind=='warehouse':
        from modules.wholesale.services.warehouse_service import apply_movement
        from modules.wholesale.models.warehouse import WarehouseMovement
        apply_movement(None,warehouse_id=place['warehouse_id'],product_id=product.id,quantity_delta=delta,
            movement_type='writeoff_reversal' if original else 'writeoff',reference_type='inventory_writeoff',
            reference_id=document.id,unit_cost=cost//quantity,note=reason,created_by=user.id)
        movement=WarehouseMovement.query.filter_by(reference_type='inventory_writeoff',reference_id=document.id).one()
    else:
        from utils.stock_movement_guard import claim_stock_movement
        from utils.product_color_service import adjust_color_stock
        from utils.branch_stock_service import adjust_branch_stock
        claim=claim_stock_movement(f'writeoff:{document.id}',movement_type='writeoff_reversal' if original else 'writeoff',
            direction='in' if original else 'out',product_id=product.id,branch_id=place['branch_id'],quantity=quantity,
            unit_cost=cost//quantity,source_type='inventory_writeoff',source_id=document.id,
            source_line_id=None,reversal_of_key=f'writeoff:{original.id}' if original else None,
            details={'reason':reason,'variant_color':line.variant_name,'valuation_layers':proof,'exact_total_cost':cost})
        if not claim.applied:raise AuditError("حركة التلف موجودة دون سند مكتمل؛ راجع السجل","conflict",409)
        movement=claim.movement;movement.total_cost=cost
        context={'source_type':'inventory_writeoff','source_id':document.id,'reason':reason,'unit_cost':cost//quantity}
        if line.variant_id:adjust_color_stock(product.id,line.variant_name,delta,branch_id=place['branch_id'])
        else:adjust_branch_stock(place['branch_id'],product.id,delta,audit_context=context)
        from models.inventory_audit import InventoryQuantityAudit
        audit=InventoryQuantityAudit.query.execution_options(skip_branch_scope=True).filter_by(movement_id=movement.id).first()
        if not audit:
            audit=InventoryQuantityAudit(event_key=uuid4().hex,movement_id=movement.id,product_id=product.id,
                branch_id=place['branch_id'],operation='writeoff_reversal' if original else 'writeoff',
                before_quantity=physical,after_quantity=physical+delta,delta_quantity=delta,
                source_type='inventory_writeoff',source_id=document.id)
            db.session.add(audit)
        audit.reason=reason;audit.employee_id=user.id;audit.employee_name=user.name
        audit.set_metadata({'variant_name':line.variant_name,'exact_total_cost':cost,'layers':proof})
    db.session.flush();document.movement_id=movement.id
    if balance(ledger_kind,place,line,product)[0]!=physical+delta:
        raise AuditError("لم يطابق الرصيد سند التلف؛ لم تحفظ العملية","stock_conflict",409)
    if cost:
        entry=JournalEntry(entry_number=f'WO-{document.id}',reference_type='inventory_writeoff',reference_id=document.id,
            description=reason,debit_account_id=inventory.id if original else loss.id,
            credit_account_id=loss.id if original else inventory.id,amount=cost,
            entry_date=datetime.combine(on,datetime.min.time()),created_by=user.id)
        db.session.add(entry);db.session.flush();document.journal_entry_id=entry.id
    document.sealed=True;db.session.flush()
    return {'id':document.id,'type':'inventory_writeoff','ledger_kind':ledger_kind,'status':'reversal' if original else 'posted'}, {
        'reason':reason,'before_quantity':physical,'after_quantity':physical+delta,'cost':cost,
        'layers':proof,'reversal_of_id':original.id if original else None,'non_cash':True}

