from uuid import uuid4
import pytest
from tests.test_finance_operations import finance
from tests.test_desktop_stock_operations import stock
from tests.test_inventory_storage_locations import context
from tests.test_inventory_storage_sales import moved_site


def setup(f,*,deferred=False):
    from models.customer import Customer
    from models.system_settings import SystemSettings
    from modules.inventory_locations.selection import FEATURE
    settings=SystemSettings.get_settings();flags=settings.get_ui_flags()
    flags.update({FEATURE:True,'defer_pending_order_stock':deferred});settings.set_ui_flags(flags)
    customer=Customer(name='عميل مصدر الكاشير',phone='07700000888',city='بغداد',branch_id=f['branch'].id)
    f['db'].session.add(customer);f['db'].session.commit();return customer


def checkout(f,customer,items,**extra):
    from services.pos_checkout import create_pos_order
    with context(f):
        return create_pos_order(employee=f['admin'],customer_id=customer.id,items=items,
            branch_id=f['branch'].id,source='desktop',submission_token=str(uuid4()),**extra)


def test_pos_preview_and_create_use_same_optional_source_and_fifo(stock):
    from services.pos_checkout import preview_pos_order
    from models.inventory_lot import OrderItemCostLayer
    from models.order_item import OrderItem
    from modules.inventory_locations.lots import order_item_location
    f=stock;site=moved_site(f);customer=setup(f)
    lines=[{'product_id':f['product'].id,'qty':2,'storage_location_id':site.id,'storage_automatic':False}]
    with context(f):
        preview=preview_pos_order(employee=f['admin'],customer_id=customer.id,items=lines,
            branch_id=f['branch'].id,source='desktop')
        assert preview['stock_ok'] and preview['total']==800
    result=checkout(f,customer,lines);assert not result['stock_locked']
    item=OrderItem.query.filter_by(invoice_id=result['invoice_id']).one()
    assert order_item_location(item.id).location_id==site.id
    assert [(row.quantity,row.unit_cost) for row in OrderItemCostLayer.query.filter_by(order_item_id=item.id)]==[(2,100)]


def test_pos_deferred_source_is_kept_and_an_edit_can_change_it_before_dispatch(stock):
    from models.order_item import OrderItem
    from modules.inventory_locations.lots import order_item_location
    f=stock;site=moved_site(f);customer=setup(f,deferred=True)
    first=checkout(f,customer,[{'product_id':f['product'].id,'qty':2,'storage_location_id':site.id}])
    old=OrderItem.query.filter_by(invoice_id=first['invoice_id']).one()
    assert order_item_location(old.id).location_id==site.id
    edited=checkout(f,customer,[{'product_id':f['product'].id,'qty':2,'storage_location_id':None,'storage_automatic':False}],
        order_id=first['invoice_id'])
    item=OrderItem.query.filter_by(invoice_id=edited['invoice_id']).one()
    selected=order_item_location(item.id)
    assert selected.location_id is None and selected.automatic is False


def test_pos_rejects_foreign_or_non_sale_source_without_creating_invoice(stock):
    from modules.inventory_locations import service
    from services.pos_checkout import PosCheckoutError
    from models.invoice import Invoice
    f=stock;customer=setup(f)
    with context(f):
        foreign=service.create_location(f['destination'].id,'FOREIGN','مخزن فرع آخر')
        damaged=service.create_location(f['branch'].id,'DAMAGE','تالف',kind='damaged');f['db'].session.commit()
    before=Invoice.query.count()
    for place in (foreign,damaged):
        with pytest.raises(PosCheckoutError) as failed:
            checkout(f,customer,[{'product_id':f['product'].id,'qty':1,'storage_location_id':place.id}])
        assert failed.value.status_code==400 and failed.value.code=='STORAGE_SOURCE_INVALID'
    assert Invoice.query.count()==before and f['product'].quantity==6
