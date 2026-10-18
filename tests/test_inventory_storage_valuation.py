"""Company/branch reports retain internal-transit value exactly once, without a web actor."""
from flask import g
from sqlalchemy import inspect,text
from tests.test_finance_operations import finance
from tests.test_desktop_stock_operations import stock
from tests.test_inventory_storage_locations import context


def test_company_and_branch_reports_keep_separate_transit_without_double_count(stock):
    from modules.inventory_locations import service
    from modules.inventory_locations.valuation import in_transit_value as internal_value
    from utils.inventory_lots import current_lot_inventory_value
    from utils.accounting_calculations import calculate_inventory_value
    from models.product import Product
    from models.branch import BranchStock
    from models.inventory_lot import InventoryLot
    f=stock
    with context(f):
        other=Product(name='صنف الفرع الثاني',sku='SECOND-STORAGE',quantity=4,buy_price=100,sale_price=200,
            branch_id=f['destination'].id)
        f['db'].session.add(other);f['db'].session.flush()
        f['db'].session.add_all([BranchStock(branch_id=f['destination'].id,product_id=other.id,quantity=4),
            InventoryLot(product_id=other.id,branch_id=f['destination'].id,quantity=4,remaining_quantity=4,unit_cost=100)])
        f['db'].session.commit()
        documents=[]
        for branch,product,quantity in ((f['branch'],f['product'],3),(f['destination'],other,2)):
            site=service.create_location(branch.id,'BACK','مخزن '+branch.name)
            doc=service.create_transfer(branch.id,product.id,quantity,None,site.id,reason='نقل موثق')
            f['db'].session.commit()
            service.send(doc.id,service.balance(branch.id,product.id)['revision'],service.document_revision(doc))
            f['db'].session.commit();documents.append(doc)
        assert current_lot_inventory_value()==1600 and calculate_inventory_value()==1600
    # Scheduler/app context has no user/session and does not call service._scope.
    assert internal_value()==650
    assert internal_value([f['branch'].id])==450 and internal_value([f['destination'].id])==200
    assert current_lot_inventory_value()==1600 and calculate_inventory_value()==1600
    with context(f,view_all=False):
        assert current_lot_inventory_value()==1200 and calculate_inventory_value()==1200
        g.branch=f['destination']
        assert current_lot_inventory_value()==400 and calculate_inventory_value()==400
    with context(f):
        service.cancel(documents[0].id,service.document_revision(documents[0]));f['db'].session.commit()
        assert internal_value()==200 and current_lot_inventory_value()==1600 and calculate_inventory_value()==1600
        service.receive(documents[1].id,service.document_revision(documents[1]));f['db'].session.commit()
        assert internal_value()==0 and current_lot_inventory_value()==1600 and calculate_inventory_value()==1600


def test_transit_reader_does_not_create_schema_for_legacy_or_query_only_database(stock):
    from modules.inventory_locations.models import InventoryStorageTransfer,InventoryStorageTransferLayer
    from modules.inventory_locations.valuation import in_transit_value
    f=stock
    for model in (InventoryStorageTransferLayer,InventoryStorageTransfer):
        model.__table__.drop(bind=f['db'].session.connection(),checkfirst=True)
    f['db'].session.commit();connection=f['db'].session.connection()
    connection.execute(text('PRAGMA query_only=ON'))
    try:
        assert in_transit_value()==0 and in_transit_value([])==0
        assert not inspect(connection).has_table('inventory_storage_transfer')
    finally:connection.execute(text('PRAGMA query_only=OFF'))


def test_full_financial_report_keeps_assets_profit_and_cash_during_internal_transport(stock):
    from modules.inventory_locations import service
    from utils.financial_report_data import get_financial_report_data
    f=stock
    with context(f):
        fields=('inventory_value','total_assets','current_assets','equity','net_profit_period',
            'cash_balance','total_liquidity','cash_inflow','cash_outflow')
        before=get_financial_report_data()
        assert before['inventory_value']==1200
        site=service.create_location(f['branch'].id,'REPORT','مخزن التقارير')
        doc=service.create_transfer(f['branch'].id,f['product'].id,3,None,site.id,reason='حفظ أصل المخزون')
        f['db'].session.commit()
        service.send(doc.id,service.balance(f['branch'].id,f['product'].id)['revision'],service.document_revision(doc))
        f['db'].session.commit()
        sent=get_financial_report_data()
        assert {key:sent[key] for key in fields}=={key:before[key] for key in fields}
        service.receive(doc.id,service.document_revision(doc));f['db'].session.commit()
        received=get_financial_report_data()
        assert {key:received[key] for key in fields}=={key:before[key] for key in fields}


def test_between_branch_transit_belongs_to_sender_until_actual_receipt(stock):
    from tests.test_desktop_stock_operations import draft,action
    from utils.accounting_calculations import calculate_inventory_value
    from utils.inventory_lots import current_lot_inventory_value
    f=stock;document,_=draft(f)
    response,_=action(f,document,'send');assert response.status_code==200,response.get_json()
    with context(f,view_all=False):
        assert current_lot_inventory_value()==1200 and calculate_inventory_value()==1200
        g.branch=f['destination']
        assert current_lot_inventory_value()==0 and calculate_inventory_value()==0
    response,_=action(f,document,'receive');assert response.status_code==200,response.get_json()
    with context(f,view_all=False):
        assert current_lot_inventory_value()==750 and calculate_inventory_value()==750
        g.branch=f['destination']
        assert current_lot_inventory_value()==450 and calculate_inventory_value()==450
