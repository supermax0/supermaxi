"""Real order receipt -> dispatch -> split collection -> full return and replay."""
import json
import pytest
from tests.test_finance_operations import finance, balance
from tests.test_desktop_stock_operations import stock


@pytest.fixture
def shipment(stock):
    f = stock
    from extensions import db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.shipping import ShippingCompany
    customer = Customer(name="عميل وصولات", phone="07712345678", city="بغداد")
    carrier = ShippingCompany(name="شركة النقل الاختبارية")
    db.session.add_all([customer, carrier]); db.session.flush()
    order = Invoice(customer_id=customer.id, customer_name=customer.name, total=800,
        paid_amount=0, status="تم الطلب", payment_status="غير مسدد", branch_id=f['branch'].id,
        employee_id=f['admin'].id, employee_name=f['admin'].name, stock_is_deducted=False)
    db.session.add(order); db.session.flush()
    db.session.add(OrderItem(invoice_id=order.id, product_id=f['product'].id,
        product_name=f['product'].name, quantity=2, price=400, cost=250, total=800))
    db.session.commit()
    def request(path, body=None, *, employee=None):
        from flask import g, session
        from routes.orders import _orders_mutations_guard
        user = employee or f['admin']
        method = 'POST' if body is not None else 'GET'
        with f['app'].test_request_context(path, method=method, json=body):
            session.update(user_id=user.id, employee_id=user.id, role=user.role, tenant_slug=f['tenant'])
            g.tenant=f['tenant']; g.branch=f['branch']; g.branches=[f['branch'],f['destination']]
            g.view_all_branches=True; g.independent_branches_enabled=True; g.branch_scope_ready=True
            endpoint, args = f['app'].url_map.bind('localhost').match(path.split('?')[0], method=method)
            denied = _orders_mutations_guard() if path.startswith('/orders/') else None
            return f['app'].make_response(denied or f['app'].view_functions[endpoint](**args))
    f.update(order=order, carrier=carrier, order_request=request)
    return f


def receipt(f, numbers=None):
    return f['order_request'](f"/orders/update-shipping-barcode/{f['order'].id}",
        {'shipping_company_id':f['carrier'].id, 'shipping_barcodes':numbers or ['SHIP-001']})


def returned(f, ids=None):
    return f['order_request']('/orders/bulk-return',
        {'order_ids':ids or [f['order'].id], 'return_branch_id':f['branch'].id})


def test_one_receipt_for_multi_piece_order_full_return_split_cash_and_replay(shipment):
    from models.branch import BranchStock
    from models.inventory_lot import InventoryLot
    from utils.inventory_lots import current_lot_inventory_value
    f=shipment; cash=balance(f); bank=balance(f,'bank')
    response=receipt(f); assert response.status_code==200,response.get_json()
    assert f['order'].status=='جاري الشحن'
    assert json.loads(f['order'].shipping_barcodes_json)==['SHIP-001']
    assert BranchStock.query.filter_by(branch_id=f['branch'].id,product_id=f['product'].id).one().quantity==4
    assert current_lot_inventory_value()==1000
    paid=f['order_request']('/orders/payment', {'id':f['order'].id, 'payment':'مسدد',
        'payment_allocations':[{'treasury_account_id':f['cash'].id,'amount':400},
                               {'treasury_account_id':f['bank'].id,'amount':400}]})
    assert paid.status_code==200,paid.get_json()
    assert balance(f)==cash+400 and balance(f,'bank')==bank+400
    printed=f['order_request'](f"/orders/print-invoices?ids={f['order'].id}")
    assert printed.status_code==200 and 'SHIP-001' in printed.get_data(as_text=True)
    result=returned(f); assert result.status_code==200,result.get_json()
    assert result.get_json()['updated_ids']==[f['order'].id]
    assert f['order'].status=='راجع' and f['order'].paid_amount==0
    assert f['order'].shipping_barcode is None and f['order'].shipping_barcodes_json is None
    assert BranchStock.query.filter_by(branch_id=f['branch'].id,product_id=f['product'].id).one().quantity==6
    assert current_lot_inventory_value()==1200
    from models.invoice_payment_ledger import InvoicePaymentLedger
    entries=[(row.amount_delta,row.treasury_account_id,row.payment_method,row.source_module) for row in InvoicePaymentLedger.query.filter_by(invoice_id=f['order'].id).all()]
    assert balance(f)==cash and balance(f,'bank')==bank, entries
    from models.shipping_payment import ShippingPayment
    from utils.treasury_calculations import get_treasury_movements
    settlements=ShippingPayment.query.filter_by(invoice_id=f['order'].id).all()
    assert sorted((row.action,row.amount) for row in settlements)==sorted([('تسديد',400),('تسديد',400),('عكس تسديد',-400),('عكس تسديد',-400)])
    assert any(row['type']=='cash_out' and row['amount']==-400 for row in get_treasury_movements(f['bank'].id))
    layers=[(row.remaining_quantity,row.unit_cost) for row in InventoryLot.query.all()]
    replay=returned(f); assert replay.status_code==200,replay.get_json()
    assert replay.get_json()['updated']==0 and replay.get_json()['skipped'][0]['id']==f['order'].id
    assert layers==[(row.remaining_quantity,row.unit_cost) for row in InventoryLot.query.all()]
    assert balance(f)==cash and balance(f,'bank')==bank
    assert ShippingPayment.query.filter_by(invoice_id=f['order'].id).count()==4
    history=f['order_request'](f"/orders/history/{f['order'].id}").get_json()['events']
    assert any(row['type']=='shipping_receipt' and 'SHIP-001' in row['details'] for row in history)
    assert receipt(f).status_code==409


def test_receipt_edits_keep_delivery_state_and_record_before_after(shipment):
    f=shipment
    assert receipt(f,['SHIP-A','SHIP-B']).status_code==200
    search=f['order_request']('/orders/data?page_type=all&search=SHIP-B').get_json()
    assert [row['id'] for row in search['rows']]==[f['order'].id]
    f['order'].status='تم التوصيل';f['db'].session.commit()
    assert receipt(f,['SHIP-C']).status_code==200
    assert f['order'].status=='تم التوصيل'
    history=f['order_request'](f"/orders/history/{f['order'].id}").get_json()['events']
    assert any('SHIP-A | SHIP-B' in row['details'] and 'SHIP-C' in row['details'] for row in history)
    details=f['order_request'](f"/orders/details/{f['order'].id}")
    assert details.status_code==200,details.get_json()
    assert details.get_json()['order']['can_return'] is True


@pytest.mark.parametrize('numbers', [['DUP','DUP'],['X'*201],[2]])
def test_invalid_receipt_cannot_dispatch_or_change_stock(shipment,numbers):
    f=shipment;response=receipt(f,numbers)
    assert response.status_code==400,response.get_json()
    f['db'].session.rollback()
    assert f['order'].status=='تم الطلب' and not f['order'].stock_is_deducted
    assert f['product'].quantity==6


def test_return_batch_reports_failure_and_does_not_claim_all_succeeded(shipment):
    from models.invoice import Invoice
    f=shipment; assert receipt(f).status_code==200
    second=Invoice(customer_id=f['order'].customer_id,customer_name=f['order'].customer_name,total=0,paid_amount=0,status='تم الطلب',payment_status='غير مسدد',branch_id=f['branch'].id,stock_is_deducted=False)
    f['db'].session.add(second);f['db'].session.commit()
    response=returned(f,[f['order'].id,second.id]);assert response.status_code==200,response.get_json()
    data=response.get_json()
    assert data['updated_ids']==[f['order'].id] and data['updated']==1
    assert data['failed'][0]['id']==second.id and 'يُلغى' in data['failed'][0]['error']
    assert second.status=='تم الطلب'


def test_missing_return_or_shipping_edit_permission_cannot_mutate(shipment):
    from models.employee import Employee
    from models.role import Role
    from uuid import uuid4
    f=shipment
    user=Employee(name='قارئ فقط',username=uuid4().hex,password='test',role='cashier',is_active=True,branch_id=f['branch'].id)
    user.roles.append(Role(name='readonly-'+uuid4().hex))
    f['db'].session.add(user);f['db'].session.commit()
    for path,body in [(f"/orders/update-shipping-barcode/{f['order'].id}",{'shipping_company_id':f['carrier'].id,'shipping_barcodes':['UNAUTHORIZED']}),('/orders/bulk-return',{'order_ids':[f['order'].id],'return_branch_id':f['branch'].id})]:
        response=f['order_request'](path,body,employee=user)
        assert response.status_code==403,response.get_json()
    assert f['order'].status=='تم الطلب' and f['order'].shipping_barcode is None
