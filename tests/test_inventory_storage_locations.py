"""Core sites partition real FIFO instead of duplicating branch stock and value."""
from contextlib import contextmanager
import pytest
from tests.test_finance_operations import finance, balance as treasury_balance
from tests.test_desktop_stock_operations import stock


@contextmanager
def context(f, *, employee=None, view_all=True):
    from flask import g, session
    user=employee or f['admin']
    with f['app'].test_request_context('/storage-test'):
        session.update(user_id=user.id, employee_id=user.id, role=user.role, tenant_slug=f['tenant'])
        g.tenant=f['tenant'];g.branch=f['branch'];g.branches=[f['branch'],f['destination']]
        g.view_all_branches=view_all;g.independent_branches_enabled=True;g.branch_scope_ready=True
        yield


def test_internal_transfer_conserves_branch_fifo_value_and_cash(stock):
    from modules.inventory_locations import service
    from models.branch import BranchStock
    from utils.inventory_lots import current_lot_inventory_value
    f=stock;cash=treasury_balance(f)
    with context(f):
        site=service.create_location(f['branch'].id,'BACK','المخزن الخلفي');f['db'].session.commit()
        main=service.balance(f['branch'].id,f['product'].id)
        child=service.balance(f['branch'].id,f['product'].id,location_id=site.id)
        assert main['quantity']==6 and child['quantity']==0
        assert main['cost']==1200 and child['cost']==0
        document=service.create_transfer(f['branch'].id,f['product'].id,3,None,site.id,reason='نقل فعلي داخل الفرع')
        f['db'].session.commit()
        old_revision=service.document_revision(document)
        service.send(document.id,main['revision'],old_revision);f['db'].session.commit()
        assert service.balance(f['branch'].id,f['product'].id)['quantity']==3
        assert service.balance(f['branch'].id,f['product'].id,location_id=site.id)['quantity']==0
        from utils.accounting_calculations import calculate_inventory_value
        assert current_lot_inventory_value()==1200 and calculate_inventory_value()==1200
        assert service.in_transit_value(f['branch'].id)==450
        service.receive(document.id,service.document_revision(document));f['db'].session.commit()
        assert service.balance(f['branch'].id,f['product'].id)['quantity']==3
        assert service.balance(f['branch'].id,f['product'].id,location_id=site.id)['quantity']==3
        assert BranchStock.query.filter_by(branch_id=f['branch'].id,product_id=f['product'].id).one().quantity==6
        assert current_lot_inventory_value()==1200 and service.in_transit_value(f['branch'].id)==0
        assert [(row.quantity,row.unit_cost) for row in service.layers(document.id)]==[(2,100),(1,250)]
        assert treasury_balance(f)==cash
        with pytest.raises(ValueError):service.receive(document.id,old_revision)
        f['db'].session.rollback()
        assert current_lot_inventory_value()==1200


def test_cancel_returns_original_site_and_cost_even_if_product_price_changed(stock):
    from modules.inventory_locations import service
    from utils.inventory_lots import current_lot_inventory_value
    f=stock
    with context(f):
        site=service.create_location(f['branch'].id,'RACK','رف التخزين');f['db'].session.commit()
        document=service.create_transfer(f['branch'].id,f['product'].id,2,None,site.id,reason='نقل ثم إلغاء')
        f['db'].session.commit()
        state=service.balance(f['branch'].id,f['product'].id)
        service.send(document.id,state['revision'],service.document_revision(document));f['db'].session.commit()
        f['product'].buy_price=999;f['db'].session.commit()
        service.cancel(document.id,service.document_revision(document));f['db'].session.commit()
        assert service.balance(f['branch'].id,f['product'].id)['quantity']==6
        assert service.balance(f['branch'].id,f['product'].id,location_id=site.id)['quantity']==0
        assert current_lot_inventory_value()==1200
        assert [(row.quantity,row.unit_cost) for row in service.layers(document.id,'cancel')]==[(2,100)]


def test_stale_source_or_document_cannot_move_stock(stock):
    from modules.inventory_locations import service
    from modules.inventory_audit.common import AuditError
    f=stock
    with context(f):
        site=service.create_location(f['branch'].id,'SITE','المخزن');f['db'].session.commit()
        document=service.create_transfer(f['branch'].id,f['product'].id,2,None,site.id,reason='مراجعة النسخة')
        f['db'].session.commit()
        state=service.balance(f['branch'].id,f['product'].id);stamp=service.document_revision(document)
        document.quantity=3;f['db'].session.commit()
        with pytest.raises(AuditError):service.send(document.id,state['revision'],stamp)
        assert document.status=='draft' and f['product'].quantity==6
        f['lots'][0].remaining_quantity=1;f['db'].session.commit()
        with pytest.raises(AuditError):service.send(document.id,state['revision'],service.document_revision(document))
        assert document.status=='draft' and f['product'].quantity==6


def test_location_edit_cannot_overwrite_change_after_revision_check(stock, monkeypatch):
    from sqlalchemy import update, select
    from modules.inventory_locations import service
    from modules.inventory_locations.models import InventoryStorageLocation
    from modules.inventory_audit.common import AuditError
    f=stock
    with context(f):
        site=service.create_location(f['branch'].id,'SITE','المخزن');f['db'].session.commit()
        revision=service.location_revision(site)
        original=service.location_revision
        def changed_after_read(row):
            stamp=original(row)
            f['db'].session.execute(update(InventoryStorageLocation).where(
                InventoryStorageLocation.id==row.id).values(name='تعديل موظف آخر')
                .execution_options(synchronize_session=False))
            return stamp
        monkeypatch.setattr(service,'location_revision',changed_after_read)
        with pytest.raises(AuditError) as failure:
            service.update_location(f['branch'].id,site.id,code='SITE',name='تعديل قديم',
                kind='storage',is_active=True,revision=revision)
        assert failure.value.code=='source_changed'
        assert f['db'].session.execute(select(InventoryStorageLocation.name).where(
            InventoryStorageLocation.id==site.id)).scalar_one()=='تعديل موظف آخر'


def test_cost_proof_and_sent_payload_are_immutable(stock):
    from modules.inventory_locations import service
    from modules.inventory_audit.common import AuditError
    f=stock
    with context(f):
        site=service.create_location(f['branch'].id,'SITE','المخزن');f['db'].session.commit()
        document=service.create_transfer(f['branch'].id,f['product'].id,1,None,site.id,reason='دليل كلفة محفوظ')
        f['db'].session.commit()
        state=service.balance(f['branch'].id,f['product'].id)
        service.send(document.id,state['revision'],service.document_revision(document));f['db'].session.commit()
        proof=service.layers(document.id)[0];proof.unit_cost=999
        with pytest.raises(AuditError):f['db'].session.flush()
        f['db'].session.rollback()
        document.quantity=2
        with pytest.raises(AuditError):f['db'].session.flush()
        f['db'].session.rollback()
        assert service.layers(document.id)[0].unit_cost==100 and document.quantity==1


def test_location_of_another_branch_is_rejected_without_mutation(stock):
    from modules.inventory_locations import service
    from modules.inventory_audit.common import AuditError
    f=stock
    with context(f):
        foreign=service.create_location(f['destination'].id,'OTHER','مخزن الفرع الثاني');f['db'].session.commit()
        with pytest.raises(AuditError):service.create_transfer(f['branch'].id,f['product'].id,1,None,foreign.id,reason='نطاق خاطئ')
        assert f['product'].quantity==6


def test_variant_location_uses_its_original_cost_and_updates_parent_only_once(stock):
    from modules.inventory_locations import service
    from models.product_color_variant import ProductColorVariant
    from models.branch import BranchStock
    f=stock
    variant=ProductColorVariant(product_id=f['product'].id,color_name='أسود | L',quantity=6)
    f['db'].session.add(variant)
    for lot in f['lots']:lot.variant_color=variant.color_name
    f['db'].session.commit()
    with context(f):
        site=service.create_location(f['branch'].id,'VAR','مخزن الخيارات');f['db'].session.commit()
        doc=service.create_transfer(f['branch'].id,f['product'].id,2,None,site.id,variant_name=variant.color_name,reason='نقل الخيار')
        f['db'].session.commit();state=service.balance(f['branch'].id,f['product'].id,variant.color_name)
        service.send(doc.id,state['revision'],service.document_revision(doc));f['db'].session.commit()
        assert variant.quantity==4 and f['product'].quantity==4
        service.receive(doc.id,service.document_revision(doc));f['db'].session.commit()
        assert variant.quantity==6 and f['product'].quantity==6
        assert BranchStock.query.filter_by(branch_id=f['branch'].id,product_id=f['product'].id).one().quantity==6
        assert service.balance(f['branch'].id,f['product'].id,variant.color_name,site.id)['quantity']==2
        assert service.balance(f['branch'].id,f['product'].id,variant.color_name,site.id)['cost']==200


def test_original_fifo_age_is_fixed_at_send(stock):
    from datetime import timedelta
    from modules.inventory_locations import service
    from models.inventory_lot import InventoryLot
    f=stock
    with context(f):
        site=service.create_location(f['branch'].id,'AGE','مخزن الكلفة');f['db'].session.commit()
        doc=service.create_transfer(f['branch'].id,f['product'].id,2,None,site.id,reason='حفظ عمر الدفعة')
        f['db'].session.commit();state=service.balance(f['branch'].id,f['product'].id);original=f['lots'][0].created_at
        service.send(doc.id,state['revision'],service.document_revision(doc));f['db'].session.commit()
        f['lots'][0].created_at+=timedelta(days=100);f['db'].session.commit()
        service.receive(doc.id,service.document_revision(doc));f['db'].session.commit()
        received=service.layers(doc.id,'receive')[0]
        assert f['db'].session.get(InventoryLot,received.inventory_lot_id).created_at==original


def test_uncovered_physical_balance_requires_review_not_guessed_cost(stock):
    from modules.inventory_locations import service
    from modules.inventory_audit.common import AuditError
    f=stock
    with context(f):
        site=service.create_location(f['branch'].id,'BASIS','مخزن التقييم');f['db'].session.commit()
        doc=service.create_transfer(f['branch'].id,f['product'].id,2,None,site.id,reason='تقييم مفقود')
        f['lots'][0].remaining_quantity=1;f['db'].session.commit()
        current=service.balance(f['branch'].id,f['product'].id)
        assert current['basis_valid'] is False and current['cost'] is None
        with pytest.raises(AuditError,match='كلفة'):service.send(doc.id,current['revision'],service.document_revision(doc))
        assert doc.status=='draft' and f['product'].quantity==6 and service.layers(doc.id)==[]


def test_failed_receive_rolls_back_new_lots_placements_and_document(stock,monkeypatch):
    from modules.inventory_locations import service
    from modules.inventory_locations.models import InventoryLotPlacement
    from models.inventory_lot import InventoryLot
    f=stock
    with context(f):
        site=service.create_location(f['branch'].id,'ATOMIC','مخزن التسليم');f['db'].session.commit()
        doc=service.create_transfer(f['branch'].id,f['product'].id,3,None,site.id,reason='فشل الاستلام')
        f['db'].session.commit();state=service.balance(f['branch'].id,f['product'].id)
        service.send(doc.id,state['revision'],service.document_revision(doc));f['db'].session.commit()
        before=[(row.id,row.remaining_quantity) for row in InventoryLot.query.all()]
        def fail(*args,**kwargs):raise ValueError('تعذر تحديث رصيد الفرع')
        monkeypatch.setattr(service,'receive_stock',fail)
        with pytest.raises(ValueError,match='تعذر'):service.receive(doc.id,service.document_revision(doc))
        assert doc.status=='sent' and service.layers(doc.id,'receive')==[]
        assert InventoryLotPlacement.query.count()==0
        assert before==[(row.id,row.remaining_quantity) for row in InventoryLot.query.all()]
        assert f['product'].quantity==3


def test_mixed_fifo_transfer_records_exact_value_without_rounding(stock):
    from modules.inventory_locations import service
    from models.stock_movement import StockMovement
    from utils.inventory_lots import current_lot_inventory_value
    f=stock;f['lots'][1].unit_cost=251;f['db'].session.commit()
    with context(f):
        site=service.create_location(f['branch'].id,'EXACT','مخزن القيم');f['db'].session.commit()
        doc=service.create_transfer(f['branch'].id,f['product'].id,3,None,site.id,reason='قيمة غير قابلة للقسمة')
        f['db'].session.commit();state=service.balance(f['branch'].id,f['product'].id)
        service.send(doc.id,state['revision'],service.document_revision(doc));f['db'].session.commit()
        assert StockMovement.query.filter_by(source_type='inventory_storage_transfer',source_id=doc.id).one().total_cost==451
        assert current_lot_inventory_value()==1204 and service.in_transit_value(f['branch'].id)==451
        service.receive(doc.id,service.document_revision(doc));f['db'].session.commit()
        assert current_lot_inventory_value()==1204


def test_legacy_read_does_not_create_location_tables(stock):
    from modules.inventory_locations import service
    from modules.inventory_locations.models import InventoryStorageLocation,InventoryLotPlacement,InventoryStorageTransfer,InventoryStorageTransferLayer
    from sqlalchemy import inspect,text
    f=stock
    for model in (InventoryStorageTransferLayer,InventoryStorageTransfer,InventoryLotPlacement,InventoryStorageLocation):
        model.__table__.drop(bind=f['db'].session.connection(),checkfirst=True)
    f['db'].session.commit()
    with context(f):
        connection=f['db'].session.connection();connection.execute(text('PRAGMA query_only=ON'))
        try:
            state=service.balance(f['branch'].id,f['product'].id)
            assert state['quantity']==6 and state['cost']==1200
            assert not inspect(connection).has_table('inventory_storage_location')
        finally:connection.execute(text('PRAGMA query_only=OFF'))
