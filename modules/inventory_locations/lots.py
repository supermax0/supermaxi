"""Site provenance for authorized sale/receipt callers; no independent quantity ledger."""
from sqlalchemy import inspect
from extensions import db
from models.inventory_lot import InventoryLot,OrderItemCostLayer
from utils.inventory_lots import InventoryLotError,_lot_query
from .models import InventoryStorageLocation,InventoryLotPlacement,InventoryOrderItemLocation


def _exists(model):return inspect(db.session.connection()).has_table(model.__tablename__)


def validate_location(branch_id,location_id,*,sale=False):
    if location_id is None:return None
    if type(location_id) is not int or location_id<1 or not branch_id or not _exists(InventoryStorageLocation):
        raise InventoryLotError('اختر مخزناً صالحاً في فرع مصدر القطع')
    row=InventoryStorageLocation.query.execution_options(skip_branch_scope=True).filter_by(
        id=location_id,branch_id=branch_id,is_active=True).first()
    if row is None:raise InventoryLotError('المخزن غير متاح في فرع مصدر القطع')
    if sale and row.kind not in ('sales','storage'):
        raise InventoryLotError('قطع التالف والرواجع للمراجعة لا تتاح للبيع')
    return row


def placement(lot):
    if not _exists(InventoryLotPlacement):return None
    row=db.session.get(InventoryLotPlacement,lot.id)
    return row.location_id if row else None


def partitioned(branch_id,product_id=None):
    if not _exists(InventoryLotPlacement) or not _exists(InventoryLot):return False
    query=db.session.query(InventoryLotPlacement.inventory_lot_id).join(InventoryLot,
        InventoryLot.id==InventoryLotPlacement.inventory_lot_id)
    query=query.filter(InventoryLot.branch_id==branch_id)
    if product_id is not None:query=query.filter(InventoryLot.product_id==product_id)
    return query.first() is not None


def query_lots(product_id,branch_id,variant,location_id,*,sale=False,automatic=False,all_variants=False):
    validate_location(branch_id,location_id,sale=sale)
    if automatic and location_id is not None:raise InventoryLotError('المصدر التلقائي لا يحدد مخزناً واحداً')
    query=_lot_query(product_id,branch_id,variant) if not all_variants else InventoryLot.query.filter(
        InventoryLot.product_id==product_id,InventoryLot.branch_id==branch_id,InventoryLot.remaining_quantity>0).order_by(
            InventoryLot.created_at.asc(),InventoryLot.id.asc())
    if not _exists(InventoryLotPlacement):return query
    query=query.outerjoin(InventoryLotPlacement,InventoryLotPlacement.inventory_lot_id==InventoryLot.id)
    if automatic:
        query=query.outerjoin(InventoryStorageLocation,InventoryStorageLocation.id==InventoryLotPlacement.location_id)
        return query.filter(InventoryLotPlacement.location_id.is_(None) | (
            (InventoryStorageLocation.branch_id==branch_id) & InventoryStorageLocation.is_active.is_(True) & InventoryStorageLocation.kind.in_(('storage','sales'))))
    return query.filter(InventoryLotPlacement.location_id.is_(None) if location_id is None else
        InventoryLotPlacement.location_id==location_id)


def order_item_location(item_id):
    if not _exists(InventoryOrderItemLocation):return None
    return db.session.get(InventoryOrderItemLocation,item_id)


def available(product_id,branch_id,variant,location_id,*,automatic=False):
    from utils.branch_stock_service import _branch_product_id,get_branch_stock,get_available_branch_stock
    product_id=_branch_product_id(branch_id,product_id) if branch_id else product_id
    from models.product import Product
    from utils.product_color_service import product_has_colors
    product=Product.query.execution_options(skip_branch_scope=True).get(product_id)
    rows=query_lots(product_id,branch_id,variant,location_id,sale=True,automatic=automatic,
        all_variants=variant is None and product is not None and product_has_colors(product)).all()
    if any(lot.unit_cost<0 for lot in rows):raise InventoryLotError('راجع دليل كلفة قطع المخزن قبل البيع')
    reserved=max(0,get_branch_stock(branch_id,product_id)-get_available_branch_stock(branch_id,product_id)) if branch_id else 0
    return max(0,sum(lot.remaining_quantity for lot in rows)-reserved)


def choose_order_item_location(item,branch_id,location_id,*,automatic=False):
    from utils.inventory_lots import ensure_inventory_lot_schema
    ensure_inventory_lot_schema()
    if type(branch_id) is not int or branch_id<1:raise InventoryLotError('اختر فرع مصدر القطع')
    validate_location(branch_id,location_id,sale=True)
    if type(automatic) is not bool or (automatic and location_id is not None):raise InventoryLotError('اختر طريقة مصدر صحيحة')
    old=order_item_location(item.id)
    if old and (old.branch_id,old.location_id,old.automatic)==(branch_id,location_id,automatic):return old
    if OrderItemCostLayer.query.filter_by(order_item_id=item.id).first():
        raise InventoryLotError('أعد القطع بسندها قبل تغيير مخزن مصدر السطر')
    from .schema import ensure_schema
    ensure_schema()
    if old:old.branch_id,old.location_id,old.automatic=branch_id,location_id,automatic
    else:
        old=InventoryOrderItemLocation(order_item_id=item.id,branch_id=branch_id,location_id=location_id,automatic=automatic)
        db.session.add(old)
    db.session.flush()
    return old


def attach(lot,location_id):
    validate_location(lot.branch_id,location_id)
    if location_id is None:return
    from .schema import ensure_schema
    ensure_schema()
    old=db.session.get(InventoryLotPlacement,lot.id)
    if old:
        if old.location_id!=location_id:raise InventoryLotError('موضع الدفعة محفوظ؛ انقل القطع بسند نقل')
        return
    db.session.add(InventoryLotPlacement(inventory_lot_id=lot.id,location_id=location_id))
