"""Optional sale-source input and read-only company capability for checkout clients."""
import json
from sqlalchemy import inspect,text
from extensions import db
from utils.inventory_lots import InventoryLotError
from .lots import validate_location
from .models import InventoryStorageLocation

FEATURE='core_storage_locations_enabled'


def enabled():
    connection=db.session.connection();schema=inspect(connection)
    if not schema.has_table('system_settings') or 'ui_flags' not in {column['name'] for column in schema.get_columns('system_settings')}:
        return False
    raw=db.session.execute(text('SELECT ui_flags FROM system_settings ORDER BY id LIMIT 1')).scalar()
    try:flags=json.loads(raw or '{}')
    except (ValueError,TypeError):return False
    return isinstance(flags,dict) and flags.get(FEATURE) is True


def parse(branch_id,raw):
    provided='storage_location_id' in raw or 'storage_automatic' in raw
    if not provided:return {'provided':False,'location_id':None,'automatic':True}
    if type(branch_id) is not int or branch_id<1:raise InventoryLotError('اختر فرع مصدر القطع')
    if not enabled():raise InventoryLotError('اختيار مصدر المخزون غير مفعّل للشركة')
    location_id=raw.get('storage_location_id');automatic=raw.get('storage_automatic',False)
    if type(automatic) is not bool or (automatic and location_id is not None):
        raise InventoryLotError('اختر طريقة مصدر مخزون صحيحة')
    validate_location(branch_id,location_id,sale=True)
    return {'provided':True,'location_id':location_id,'automatic':automatic}


def choices(branch_id):
    if not enabled() or not branch_id:return []
    rows=[]
    if inspect(db.session.connection()).has_table(InventoryStorageLocation.__tablename__):
        rows=InventoryStorageLocation.query.execution_options(skip_branch_scope=True).filter(
            InventoryStorageLocation.branch_id==branch_id,InventoryStorageLocation.is_active.is_(True),
            InventoryStorageLocation.kind.in_(('sales','storage'))).order_by(InventoryStorageLocation.name).all()
    return [{'key':'auto','id':None,'name':'تلقائي من المواقع المتاحة','automatic':True},
        {'key':'main','id':None,'name':'الموقع الأساسي للفرع','automatic':False}]+[
        {'key':str(row.id),'id':row.id,'name':row.name,'automatic':False} for row in rows]


def describe(item):
    from .lots import order_item_location
    selected=order_item_location(item.id)
    if not selected:return None
    place=db.session.get(InventoryStorageLocation,selected.location_id) if selected.location_id else None
    return {'key':'auto' if selected.automatic else str(selected.location_id) if selected.location_id else 'main',
        'id':selected.location_id,'automatic':selected.automatic,'branch_id':selected.branch_id,
        'name':'تلقائي من المواقع المتاحة' if selected.automatic else place.name if place else 'الموقع الأساسي للفرع'}
