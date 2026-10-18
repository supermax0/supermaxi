"""Authorized order dispatch consumes only its durable site choice and original FIFO."""
import pytest
from tests.test_finance_operations import finance
from tests.test_desktop_stock_operations import stock
from tests.test_desktop_order_returns_shipping import shipment,receipt
from tests.test_inventory_storage_locations import context


def moved_site(f,kind='storage'):
    from modules.inventory_locations import service
    with context(f):
        site=service.create_location(f['branch'].id,'BACK','المخزن الخلفي',kind=kind)
        doc=service.create_transfer(f['branch'].id,f['product'].id,3,None,site.id,reason='توزيع موقع')
        f['db'].session.commit()
        service.send(doc.id,service.balance(f['branch'].id,f['product'].id)['revision'],service.document_revision(doc))
        f['db'].session.commit();service.receive(doc.id,service.document_revision(doc));f['db'].session.commit()
        return site


def test_explicit_main_dispatch_does_not_consume_older_child_lots(shipment):
    from modules.inventory_locations import service
    from models.inventory_lot import OrderItemCostLayer
    from modules.inventory_locations.lots import choose_order_item_location
    from models.order_item import OrderItem
    f=shipment;site=moved_site(f);item=OrderItem.query.filter_by(invoice_id=f['order'].id).one()
    choose_order_item_location(item,f['branch'].id,None);f['db'].session.commit()
    response=receipt(f);assert response.status_code==200,response.get_json()
    assert [(row.quantity,row.unit_cost) for row in OrderItemCostLayer.query.all()]==[(2,250)]
    with context(f):
        assert service.balance(f['branch'].id,f['product'].id)['quantity']==1
        assert service.balance(f['branch'].id,f['product'].id,location_id=site.id)['quantity']==3


def test_selected_source_survives_request_boundaries_and_uses_its_original_cost(shipment):
    from modules.inventory_locations.lots import choose_order_item_location
    from models.order_item import OrderItem
    from models.inventory_lot import OrderItemCostLayer
    from models.stock_movement import StockMovement
    f=shipment;site=moved_site(f);item=OrderItem.query.filter_by(invoice_id=f['order'].id).one()
    choose_order_item_location(item,f['branch'].id,site.id);f['db'].session.commit();f['db'].session.expire_all()
    response=receipt(f);assert response.status_code==200,response.get_json()
    assert [(row.quantity,row.unit_cost) for row in OrderItemCostLayer.query.all()]==[(2,100)]
    movement=StockMovement.query.filter_by(source_type='invoice',source_id=f['order'].id,movement_type='order_deduct').one()
    assert movement.total_cost==200
    assert str(site.id) in movement.details_json
    from utils.inventory_lots import InventoryLotError
    with pytest.raises(InventoryLotError,match='مصدر|المصدر'):
        choose_order_item_location(item,f['branch'].id,None)
    f['db'].session.rollback()


def test_insufficient_main_site_does_not_invent_fallback_or_dispatch_an_order(shipment):
    from models.order_item import OrderItem
    from models.inventory_lot import InventoryLot,OrderItemCostLayer
    from utils.order_stock_lock import check_invoice_stock
    from modules.inventory_locations.lots import choose_order_item_location
    f=shipment;moved_site(f);item=OrderItem.query.filter_by(invoice_id=f['order'].id).one()
    item.quantity=4;f['db'].session.commit()
    choose_order_item_location(item,f['branch'].id,None);f['db'].session.commit()
    with context(f):
        check=check_invoice_stock(f['order'])
        assert check.can_fulfill is False and 'المصدر' in check.reason_text
    before=[(row.id,row.remaining_quantity) for row in InventoryLot.query.all()]
    response=receipt(f)
    assert not f['order'].stock_is_deducted
    assert before==[(row.id,row.remaining_quantity) for row in InventoryLot.query.all()]
    assert OrderItemCostLayer.query.count()==0


@pytest.mark.parametrize('kind',['damaged','returns'])
def test_non_sale_locations_cannot_be_selected_as_an_order_source(shipment,kind):
    from modules.inventory_locations.lots import choose_order_item_location
    from utils.inventory_lots import InventoryLotError
    from models.order_item import OrderItem
    f=shipment;site=moved_site(f,kind);item=OrderItem.query.filter_by(invoice_id=f['order'].id).one()
    with pytest.raises(InventoryLotError,match='لا تتاح للبيع'):
        choose_order_item_location(item,f['branch'].id,site.id)


def test_caller_rollback_keeps_fifo_and_source_choice_unchanged_after_consumption(shipment):
    from utils.inventory_lots import consume_lots_for_order_item
    from modules.inventory_locations.lots import order_item_location
    from models.order_item import OrderItem
    from models.inventory_lot import InventoryLot,OrderItemCostLayer
    f=shipment;site=moved_site(f);item=OrderItem.query.filter_by(invoice_id=f['order'].id).one()
    before=[(row.id,row.remaining_quantity) for row in InventoryLot.query.all()]
    assert consume_lots_for_order_item(item,branch_id=f['branch'].id,storage_location_id=site.id)==200
    f['db'].session.rollback()
    assert before==[(row.id,row.remaining_quantity) for row in InventoryLot.query.all()]
    assert OrderItemCostLayer.query.count()==0 and order_item_location(item.id) is None


def test_return_from_child_source_receives_main_or_review_site_at_original_cost(shipment):
    from modules.inventory_locations import service
    from modules.inventory_locations.lots import choose_order_item_location
    from models.order_item import OrderItem
    from models.inventory_lot import InventoryLot,OrderItemCostLayer
    from utils.accounting_calculations import calculate_inventory_value
    f=shipment;site=moved_site(f);item=OrderItem.query.filter_by(invoice_id=f['order'].id).one()
    choose_order_item_location(item,f['branch'].id,site.id);f['db'].session.commit()
    assert receipt(f).status_code==200
    origin=OrderItemCostLayer.query.filter_by(order_item_id=item.id).one().inventory_lot.created_at
    f['product'].buy_price=999;f['db'].session.commit()
    with context(f):
        review=service.create_location(f['branch'].id,'REVIEW','رواجع للفحص',kind='returns');f['db'].session.commit()
    result=f['order_request']('/orders/bulk-return',{'order_ids':[f['order'].id],
        'return_branch_id':f['branch'].id,'return_location_id':review.id})
    assert result.get_json()['updated_ids']==[f['order'].id],result.get_json()
    with context(f):
        assert service.balance(f['branch'].id,f['product'].id)['quantity']==3
        assert service.balance(f['branch'].id,f['product'].id,location_id=site.id)['quantity']==1
        received=service.balance(f['branch'].id,f['product'].id,location_id=review.id)
        assert received['quantity']==2 and received['cost']==200 and received['available']==0
        assert calculate_inventory_value()==1200
    returned_lot=InventoryLot.query.order_by(InventoryLot.id.desc()).first()
    assert returned_lot.unit_cost==100 and returned_lot.created_at==origin


def test_cross_branch_return_uses_local_product_fifo_and_movement_without_false_value(shipment):
    from models.branch import BranchStock
    from models.product import Product
    from models.inventory_lot import InventoryLot
    from models.stock_movement import StockMovement
    from utils.accounting_calculations import calculate_inventory_value
    f=shipment;assert receipt(f).status_code==200
    result=f['order_request']('/orders/bulk-return',{'order_ids':[f['order'].id],
        'return_branch_id':f['destination'].id})
    assert result.get_json()['updated_ids']==[f['order'].id],result.get_json()
    local=Product.query.execution_options(skip_branch_scope=True).filter_by(
        branch_id=f['destination'].id,catalog_group_id=f['product'].catalog_group_id).one()
    assert local.quantity==2 and f['product'].quantity==4
    assert BranchStock.query.filter_by(branch_id=f['destination'].id,product_id=local.id).one().quantity==2
    lot=InventoryLot.query.filter_by(branch_id=f['destination'].id,product_id=local.id).one()
    assert lot.remaining_quantity==2 and lot.unit_cost==100
    movement=StockMovement.query.filter_by(source_type='invoice',source_id=f['order'].id,movement_type='order_restore').one()
    assert movement.product_id==local.id and movement.total_cost==200
    with context(f):assert calculate_inventory_value()==1200


def test_purchase_receipt_assigns_only_received_fifo_to_its_selected_location(stock):
    from types import SimpleNamespace
    from modules.inventory_locations import service
    from utils.inventory_lots import create_purchase_lot
    from utils.branch_stock_service import receive_stock
    f=stock
    with context(f):
        site=service.create_location(f['branch'].id,'INCOMING','مخزن الاستلام')
        receive_stock(f['branch'].id,f['product'].id,2)
        create_purchase_lot(SimpleNamespace(id=None,product_id=f['product'].id,quantity=2,
            final_unit_cost=77,variant_color=None),f['branch'].id,storage_location_id=site.id)
        f['db'].session.commit()
        assert service.balance(f['branch'].id,f['product'].id)['quantity']==6
        incoming=service.balance(f['branch'].id,f['product'].id,location_id=site.id)
        assert incoming['quantity']==2 and incoming['cost']==154


def test_empty_site_cannot_be_disabled_while_a_deferred_order_has_selected_it(shipment):
    from modules.inventory_locations import service
    from modules.inventory_locations.lots import choose_order_item_location
    from modules.inventory_audit.common import AuditError
    from models.order_item import OrderItem
    f=shipment;item=OrderItem.query.filter_by(invoice_id=f['order'].id).one()
    with context(f):
        site=service.create_location(f['branch'].id,'WAIT','مخزن طلب مؤجل');f['db'].session.commit()
        choose_order_item_location(item,f['branch'].id,site.id);f['db'].session.commit()
        with pytest.raises(AuditError) as rejected:
            service.update_location(f['branch'].id,site.id,code=site.code,name=site.name,kind=site.kind,
                is_active=False,revision=service.location_revision(site))
        assert rejected.value.code=='location_in_use'
        choose_order_item_location(item,f['branch'].id,None);f['db'].session.commit()
        assert service.update_location(f['branch'].id,site.id,code=site.code,name=site.name,kind=site.kind,
            is_active=False,revision=service.location_revision(site)).is_active is False


def test_color_size_dispatch_uses_local_variant_in_selected_fulfillment_branch(shipment):
    from models.product_color_variant import ProductColorVariant
    from models.inventory_lot import InventoryLot,OrderItemCostLayer
    from models.order_item import OrderItem
    from models.stock_movement import StockMovement
    from utils.branch_product_service import product_for_branch
    from utils.product_color_service import sync_product_total_from_colors
    from modules.inventory_locations.lots import choose_order_item_location
    f=shipment
    with context(f):
        for lot in f['lots']:lot.remaining_quantity=0
        variant=ProductColorVariant(product_id=f['product'].id,color_name='أسود | L',quantity=0)
        f['db'].session.add(variant);f['db'].session.flush()
        sync_product_total_from_colors(f['product'].id,branch_id=f['branch'].id)
        local=product_for_branch(f['product'],f['destination'].id)
        local_variant=ProductColorVariant.query.filter_by(product_id=local.id,color_name=variant.color_name).one()
        local_variant.quantity=4;f['db'].session.flush()
        sync_product_total_from_colors(local.id,branch_id=f['destination'].id)
        f['db'].session.add(InventoryLot(product_id=local.id,branch_id=f['destination'].id,variant_color=variant.color_name,
            quantity=4,remaining_quantity=4,unit_cost=100))
        item=OrderItem.query.filter_by(invoice_id=f['order'].id).one();item.variant_color=variant.color_name
        f['db'].session.commit();choose_order_item_location(item,f['destination'].id,None);f['db'].session.commit()
    response=receipt(f);assert response.status_code==200,response.get_json()
    assert f['order'].stock_is_deducted is True
    assert local_variant.quantity==2 and variant.quantity==0
    assert [(row.product_id,row.quantity,row.unit_cost) for row in OrderItemCostLayer.query.all()]==[(local.id,2,100)]
    movement=StockMovement.query.filter_by(source_type='invoice',source_id=f['order'].id,movement_type='order_deduct').one()
    assert movement.product_id==local.id and movement.branch_id==f['destination'].id and movement.total_cost==200


def test_database_cannot_reassign_source_while_dispatched_cost_layers_exist(shipment):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from modules.inventory_locations.lots import choose_order_item_location,order_item_location
    from models.order_item import OrderItem
    f=shipment;site=moved_site(f);item=OrderItem.query.filter_by(invoice_id=f['order'].id).one()
    choose_order_item_location(item,f['branch'].id,site.id);f['db'].session.commit();assert receipt(f).status_code==200
    with pytest.raises(IntegrityError):
        f['db'].session.execute(text('UPDATE inventory_order_item_location SET location_id=NULL WHERE order_item_id=:item'),{'item':item.id})
    f['db'].session.rollback();assert order_item_location(item.id).location_id==site.id


def test_staff_cannot_redirect_physical_return_to_an_unassigned_branch(shipment):
    from uuid import uuid4
    from models.employee import Employee
    from models.role import Role,Permission
    from models.inventory_lot import InventoryLot
    f=shipment;assert receipt(f).status_code==200
    role=Role(name='return-staff-'+uuid4().hex)
    for name in ('can_see_orders','manage_orders','return_orders'):
        permission=Permission.query.filter_by(name=name).first()
        if not permission:permission=Permission(name=name);f['db'].session.add(permission)
        role.permissions.append(permission)
    user=Employee(username=uuid4().hex,name='موظف الإرجاع',password='test',role='cashier',branch_id=f['branch'].id,is_active=True)
    user.roles.append(role);f['db'].session.add(user);f['db'].session.commit()
    before=[(row.id,row.remaining_quantity) for row in InventoryLot.query.all()]
    response=f['order_request']('/orders/bulk-return',{'order_ids':[f['order'].id],
        'return_branch_id':f['destination'].id},employee=user)
    result=response.get_json();assert result['updated']==0 and result['failed'],result
    assert f['order'].stock_is_deducted and f['order'].status!='راجع'
    assert before==[(row.id,row.remaining_quantity) for row in InventoryLot.query.all()]


def test_automatic_dispatch_combines_eligible_sites_and_preserves_real_fifo(shipment):
    from models.order_item import OrderItem
    from models.inventory_lot import OrderItemCostLayer
    from modules.inventory_locations import service
    f=shipment;site=moved_site(f);item=OrderItem.query.filter_by(invoice_id=f['order'].id).one()
    item.quantity=4;item.total=1600;f['order'].total=1600;f['db'].session.commit()
    response=receipt(f);assert response.status_code==200,response.get_json()
    assert f['order'].stock_is_deducted
    assert sum(row.quantity*row.unit_cost for row in OrderItemCostLayer.query.all())==700
    with context(f):
        # The original main lot precedes the transferred fragment when their ages match.
        assert service.balance(f['branch'].id,f['product'].id)['quantity']==1
        assert service.balance(f['branch'].id,f['product'].id,location_id=site.id)['quantity']==1


def test_explicit_main_is_protected_before_automatic_line_in_same_order(shipment):
    from models.order_item import OrderItem
    from models.inventory_lot import OrderItemCostLayer
    from modules.inventory_locations.lots import choose_order_item_location
    f=shipment;moved_site(f);automatic=OrderItem.query.filter_by(invoice_id=f['order'].id).one()
    automatic.quantity=3;automatic.total=1200
    main=OrderItem(invoice_id=f['order'].id,product_id=f['product'].id,product_name=f['product'].name,
        quantity=3,price=400,cost=250,total=1200)
    f['db'].session.add(main);f['order'].total=2400;f['db'].session.commit()
    choose_order_item_location(main,f['branch'].id,None);f['db'].session.commit()
    response=receipt(f);assert response.status_code==200,response.get_json()
    assert f['order'].stock_is_deducted
    assert sum(row.quantity*row.unit_cost for row in OrderItemCostLayer.query.filter_by(order_item_id=main.id))==750
    assert sum(row.quantity*row.unit_cost for row in OrderItemCostLayer.query.filter_by(order_item_id=automatic.id))==450


@pytest.mark.parametrize('kind',['damaged','returns'])
def test_automatic_source_excludes_non_sale_goods_in_availability_and_dispatch(shipment,kind):
    from models.order_item import OrderItem
    from models.inventory_lot import OrderItemCostLayer
    from utils.order_stock_lock import check_invoice_stock
    f=shipment;moved_site(f,kind);item=OrderItem.query.filter_by(invoice_id=f['order'].id).one()
    item.quantity=4;item.total=1600;f['order'].total=1600;f['db'].session.commit()
    with context(f):
        check=check_invoice_stock(f['order']);assert check.can_fulfill is False
    receipt(f);assert f['order'].stock_is_deducted is False and OrderItemCostLayer.query.count()==0


def test_enabling_locations_for_one_product_does_not_disable_legacy_sales_of_another(stock):
    from models.product import Product
    from models.branch import BranchStock
    from models.invoice import Invoice
    from models.customer import Customer
    from models.order_item import OrderItem
    from utils.order_stock_lock import check_invoice_stock,apply_stock_actions
    f=stock;moved_site(f)
    with context(f):
        product=Product(name='مخزون قديم مستقل',buy_price=30,sale_price=50,quantity=3,branch_id=f['branch'].id,active=True)
        customer=Customer(name='عميل قديم',phone='07700000300',branch_id=f['branch'].id)
        f['db'].session.add_all([product,customer]);f['db'].session.flush()
        f['db'].session.add(BranchStock(branch_id=f['branch'].id,product_id=product.id,quantity=3))
        invoice=Invoice(customer_id=customer.id,customer_name=customer.name,total=50,status='مسدد',payment_status='مسدد',
            branch_id=f['branch'].id,stock_is_deducted=False)
        f['db'].session.add(invoice);f['db'].session.flush()
        f['db'].session.add(OrderItem(invoice_id=invoice.id,product_id=product.id,product_name=product.name,
            quantity=1,price=50,cost=30,total=50));f['db'].session.commit()
        check=check_invoice_stock(invoice);assert check.can_fulfill,check.reason_text
        apply_stock_actions(check.actions,invoice=invoice);f['db'].session.commit()
        assert product.quantity==2


def test_catalog_aliases_cannot_reserve_same_local_color_quantity_twice(stock):
    from models.product_color_variant import ProductColorVariant
    from utils.branch_product_service import product_for_branch
    from utils.product_color_service import sync_product_total_from_colors
    from utils.order_stock_lock import check_stock_rows
    f=stock
    with context(f):
        f['db'].session.add_all([ProductColorVariant(product_id=f['product'].id,color_name='أسود | L',quantity=3),
            ProductColorVariant(product_id=f['product'].id,color_name='أبيض | L',quantity=3)])
        f['db'].session.flush();local=product_for_branch(f['product'],f['destination'].id)
        for variant in ProductColorVariant.query.filter_by(product_id=local.id):variant.quantity=3
        f['db'].session.flush();sync_product_total_from_colors(local.id,branch_id=f['destination'].id);f['db'].session.commit()
        rows=[{'product':product,'product_id':product.id,'quantity':2,'variant_color':'أسود | L',
            'fulfillment_branch_id':f['destination'].id} for product in (f['product'],local)]
        checked=check_stock_rows(rows,preferred_branch_id=f['branch'].id)
        assert checked.can_fulfill is False and 'المتوفر 3 والمطلوب 4' in checked.reason_text
