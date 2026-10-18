import json
from types import SimpleNamespace
from sqlalchemy import inspect
from extensions import db
from models.branch import BranchStock
from models.product import Product
from models.product_color_variant import ProductColorVariant
from models.stock_operations import StockReorderRule
from modules.inventory_audit.common import AuditError, actor, fingerprint, integer, text
from modules.inventory_audit.stock import locations as audit_locations, planned_products, stock_state, product_data, product_identity
from utils.permission_checks import employee_can
from utils.inventory_lots import _lot_query


def require(permission):
    if not employee_can(actor(),permission):raise AuditError("ليست لديك صلاحية هذا الإجراء المخزني","forbidden",403)


def kind(value):
    if value not in ("branch","warehouse"):raise AuditError("اختر نوع موقع صحيحاً")
    if value=="warehouse":
        from modules.wholesale.guards import is_wholesale_tenant, employee_can_wholesale
        if not is_wholesale_tenant() or not employee_can_wholesale(actor(),"wholesale_warehouses"):
            raise AuditError("مخازن الجملة تخص نشاط الجملة والصلاحية الممنوحة له","forbidden",403)
    return value


def locations(ledger):
    return audit_locations(kind(ledger))


def location(ledger,key):
    found=next((row for row in locations(ledger) if row['key']==key),None)
    if not found:raise AuditError("الموقع غير متاح أو خارج نطاقك","forbidden",403)
    return found


def cost_visible():
    return employee_can(actor(),"finance.view") or employee_can(actor(),"inventory.audit.cost")


def money(value):
    return str(value) if value is not None and abs(value)>9007199254740991 else value


def item(ledger,place,product_id,variant_name="",*,lock=False):
    integer(product_id,minimum=1)
    variant_name=text(variant_name,limit=80)
    candidates=planned_products(place,ledger)
    product,variants=next(((p,v) for p,v in candidates if p.id==product_id),(None,None))
    if product is None:raise AuditError("الصنف غير متاح في الموقع المحدد","not_found",404)
    variant=next((v for v in variants if v.color_name==variant_name),None) if variants else None
    if (variants and not variant) or (not variants and variant_name):
        raise AuditError("اختر خيار الصنف الصحيح قبل التسجيل")
    return SimpleNamespace(product_id=product.id,branch_id=place['branch_id'],warehouse_id=place['warehouse_id'],
        variant_id=variant.id if variant else None,variant_name=variant.color_name if variant else "",
        product_snapshot_json="{}",catalog_key=product_identity(product)),product


def balance(ledger,place,line,product):
    quantity,stamp=stock_state(line)
    if ledger=="warehouse":
        from modules.wholesale.models.warehouse import WarehouseStock
        row=WarehouseStock.query.filter_by(warehouse_id=place['warehouse_id'],product_id=product.id).first()
        available=int(row.available_quantity) if row else 0
        transit=int(row.in_transit_quantity or 0) if row else 0
    else:
        from utils.branch_sales import available_fulfillment_qty
        available=int(available_fulfillment_qty(place['branch_id'],product.id,line.variant_name or None))
        transit=0
        from models.branch import StockTransfer,StockTransferLine
        source_ids=db.session.query(Product.id).execution_options(skip_branch_scope=True).filter(
            Product.catalog_group_id==product.catalog_group_id) if product.catalog_group_id else [product.id]
        transit=int(db.session.query(db.func.coalesce(db.func.sum(StockTransferLine.quantity),0)).join(
            StockTransfer,StockTransfer.id==StockTransferLine.transfer_id).filter(StockTransfer.status=="sent",
            StockTransfer.to_branch_id==place['branch_id'],StockTransferLine.product_id.in_(source_ids),
            db.func.coalesce(StockTransferLine.variant_color,"")==line.variant_name).scalar() or 0)
    lots=[]
    if ledger=="branch" and inspect(db.session.connection()).has_table("inventory_lot"):
        lots=[(lot.id,lot.remaining_quantity,lot.unit_cost) for lot in _lot_query(product.id,place['branch_id'],line.variant_name or None).all()]
    return quantity,max(0,available),transit,fingerprint({'physical':stamp,'available':available,'transit':transit,'lots':lots})


def rule(ledger,place,line,product):
    found=None
    if inspect(db.session.connection()).has_table(StockReorderRule.__tablename__):
        found=StockReorderRule.query.execution_options(skip_branch_scope=True).filter_by(ledger_kind=ledger,
            location_id=place['warehouse_id'] or place['branch_id'],product_id=product.id,variant_name=line.variant_name).first()
    minimum=int(found.minimum) if found else max(0,int(product.low_stock_threshold if product.low_stock_threshold is not None else 5))
    target=int(found.target) if found else max(minimum,minimum*2)
    return minimum,target,found.version if found else 0


def serialize_stock(ledger,place,line,product):
    qty,available,transit,revision=balance(ledger,place,line,product)
    minimum,target,version=rule(ledger,place,line,product)
    data=product_data(line,saved=False,show_cost=cost_visible())
    if 'unit_cost' in data:data['unit_cost']=money(data['unit_cost'])
    valuation_ready=ledger=='warehouse' or (inspect(db.session.connection()).has_table('inventory_lot') and
        sum(lot.remaining_quantity for lot in _lot_query(product.id,place['branch_id'],line.variant_name or None))==qty)
    return {**data,'id':-line.variant_id if line.variant_id else product.id,'product_id':product.id,
        'location_key':place['key'],'location_name':place['name'],'quantity':qty,'available':available,
        'reserved':max(0,qty-available),'in_transit':transit,'minimum':minimum,'target':target,'rule_version':version,
        'suggested':max(0,target-available-transit) if available<=minimum else 0,'revision':revision,'valuation_ready':valuation_ready}


def stocks(ledger,place,q="",reorder=False):
    q=q.strip().casefold()
    rows=[]
    for product,variants in planned_products(place,ledger):
        for variant in variants or [None]:
            if q and q not in f'{product.name} {product.sku or ""} {product.barcode or ""} {variant.color_name if variant else ""}'.casefold():continue
            line=SimpleNamespace(product_id=product.id,branch_id=place['branch_id'],warehouse_id=place['warehouse_id'],
                variant_id=variant.id if variant else None,variant_name=variant.color_name if variant else "",product_snapshot_json="{}",catalog_key=product_identity(product))
            row=serialize_stock(ledger,place,line,product)
            if not reorder or row['available']<=row['minimum']:rows.append(row)
    return rows

