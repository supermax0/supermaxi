from uuid import uuid4
import pytest
from flask import Flask, g, session
from tests.test_finance_operations import finance
from tests.test_desktop_stock_operations import stock
from modules.inventory_locations import routes


@pytest.fixture
def storage_api(stock):
    f=stock;probe=Flask('storage-api-routing');probe.register_blueprint(routes.storage_locations_bp)
    def call(path,body=None,*,employee=None):
        user=employee or f['admin'];url='/api/v1/desktop/stock-operations/storage'+path
        method='POST' if body is not None else 'GET'
        with f['app'].test_request_context(url,method=method,json=body):
            session.update(user_id=user.id,employee_id=user.id,role=user.role,tenant_slug=f['tenant'])
            g.tenant=f['tenant'];g.branch=f['branch'];g.branches=[f['branch'],f['destination']]
            g.view_all_branches=True;g.independent_branches_enabled=True;g.branch_scope_ready=True
            endpoint,args=probe.url_map.bind('localhost').match(url.split('?')[0],method=method)
            return f['app'].make_response(probe.view_functions[endpoint](**args))
    f['storage_api']=call
    return f


def site(f):
    payload={'operation_id':str(uuid4()),'branch_id':f['branch'].id,'code':'BACK','name':'المخزن الخلفي','kind':'storage'}
    response=f['storage_api']('/locations',payload)
    assert response.status_code==200,response.get_json()
    return response.get_json()['data']['location'],payload


def test_location_creation_replays_same_receipt_and_rejects_replacement(storage_api):
    from modules.inventory_locations.models import InventoryStorageLocation
    from models.activity_log import ActivityLog
    f=storage_api;location,payload=site(f)
    replay=f['storage_api']('/locations',payload)
    assert replay.get_json()['data']['location']==location
    assert InventoryStorageLocation.query.count()==1
    assert ActivityLog.query.filter_by(entity_type='storage_location',action='stock_command').count()==1
    changed=f['storage_api']('/locations',{**payload,'name':'اسم آخر'})
    assert changed.status_code==409 and InventoryStorageLocation.query.count()==1


def test_each_transfer_phase_is_replayed_once_with_original_request(storage_api):
    from modules.inventory_locations.models import InventoryStorageTransfer
    from models.stock_movement import StockMovement
    f=storage_api;location,_=site(f)
    create={'operation_id':str(uuid4()),'branch_id':f['branch'].id,'product_id':f['product'].id,
        'quantity':3,'from_location_id':None,'to_location_id':location['id'],'reason':'نقل حقيقي'}
    response=f['storage_api']('/transfers',create);assert response.status_code==200,response.get_json()
    document=response.get_json()['data']['document'];id=document['id']
    assert f['storage_api']('/transfers',create).get_json()['data']['id']==id
    details=f['storage_api'](f'/transfers/{id}').get_json()['data']
    send={'operation_id':str(uuid4()),'branch_id':f['branch'].id,'revision':details['revision'],
        'source_revision':details['source']['revision']}
    first=f['storage_api'](f'/transfers/{id}/send',send);assert first.status_code==200,first.get_json()
    assert f['product'].quantity==3
    assert f['storage_api'](f'/transfers/{id}/send',send).get_json()==first.get_json()
    latest=f['storage_api'](f'/transfers/{id}').get_json()['data']
    receive={'operation_id':str(uuid4()),'branch_id':f['branch'].id,'revision':latest['revision']}
    first=f['storage_api'](f'/transfers/{id}/receive',receive);assert first.status_code==200,first.get_json()
    assert f['storage_api'](f'/transfers/{id}/receive',receive).get_json()==first.get_json()
    assert f['product'].quantity==6 and InventoryStorageTransfer.query.count()==1
    assert StockMovement.query.filter_by(source_type='inventory_storage_transfer',source_id=id).count()==2


def test_occupied_or_pending_site_cannot_change_kind_or_be_disabled(storage_api):
    f=storage_api;location,_=site(f)
    create={'operation_id':str(uuid4()),'branch_id':f['branch'].id,'product_id':f['product'].id,
        'quantity':1,'from_location_id':None,'to_location_id':location['id'],'reason':'تحويل معلق'}
    document=f['storage_api']('/transfers',create).get_json()['data']['document']
    edit={'operation_id':str(uuid4()),'branch_id':f['branch'].id,'code':location['code'],'name':location['name'],
        'kind':'damaged','is_active':False,'revision':location['revision']}
    response=f['storage_api'](f"/locations/{location['id']}",edit)
    assert response.status_code==409 and response.get_json()['code']=='location_in_use'
    details=f['storage_api'](f"/transfers/{document['id']}").get_json()['data']
    cancelled=f['storage_api'](f"/transfers/{document['id']}/cancel",{'operation_id':str(uuid4()),
        'branch_id':f['branch'].id,'revision':details['revision']})
    assert cancelled.status_code==200,cancelled.get_json()
    response=f['storage_api'](f"/locations/{location['id']}",{**edit,'operation_id':str(uuid4())})
    assert response.status_code==200,response.get_json()
    assert response.get_json()['data']['location']['is_active'] is False


def test_transfer_retains_product_identity_when_catalog_is_renamed(storage_api):
    from modules.inventory_locations import service
    from modules.inventory_audit.common import AuditError
    f=storage_api;location,_=site(f)
    payload={'operation_id':str(uuid4()),'branch_id':f['branch'].id,'product_id':f['product'].id,
        'quantity':1,'from_location_id':None,'to_location_id':location['id'],'reason':'توثيق الصنف'}
    document=f['storage_api']('/transfers',payload).get_json()['data']['document']
    assert document['product_name']==f['product'].name and document['sku']=='STOCK-OPS'
    f['product'].name='اسم جديد';f['product'].sku='NEW-SKU';f['db'].session.commit()
    details=f['storage_api'](f"/transfers/{document['id']}").get_json()['data']
    assert details['product_name']==document['product_name'] and details['sku']=='STOCK-OPS'
    sent=f['storage_api'](f"/transfers/{document['id']}/send",{'operation_id':str(uuid4()),
        'branch_id':f['branch'].id,'revision':details['revision'],'source_revision':details['source']['revision']})
    assert sent.status_code==200,sent.get_json()
    row=service.InventoryStorageTransfer.query.get(document['id'])
    row.product_snapshot_json='{}'
    with pytest.raises(AuditError):f['db'].session.flush()
    f['db'].session.rollback()


def test_color_and_size_rows_have_distinct_list_identity(storage_api):
    from models.product_color_variant import ProductColorVariant
    f=storage_api
    f['db'].session.add_all([ProductColorVariant(product_id=f['product'].id,color_name='أسود | L',quantity=3),
        ProductColorVariant(product_id=f['product'].id,color_name='أبيض | L',quantity=3)])
    f['db'].session.commit()
    response=f['storage_api'](f"/stocks?branch_id={f['branch'].id}&q=STOCK-OPS")
    assert response.status_code==200,response.get_json()
    items=response.get_json()['data']['items']
    assert len(items)==2 and len({row['id'] for row in items})==2
    assert {row['product_id'] for row in items}=={f['product'].id}
    assert {row['variant_name'] for row in items}=={'أسود | L','أبيض | L'}


def reader(f):
    from models.employee import Employee
    from models.role import Role,Permission
    permission=Permission.query.filter_by(name='manage_inventory').first()
    if not permission:permission=Permission(name='manage_inventory');f['db'].session.add(permission)
    role=Role(name='storage-reader-'+uuid4().hex);role.permissions.append(permission)
    user=Employee(username=uuid4().hex,name='قارئ المخزون',password='test',role='cashier',branch_id=f['branch'].id,is_active=True)
    user.roles.append(role);f['db'].session.add(user);f['db'].session.commit()
    return user


def test_reader_gets_own_branch_without_cost_and_cannot_mutate_or_replay(storage_api):
    f=storage_api;location,payload=site(f);user=reader(f)
    item=f['storage_api'](f"/item?branch_id={f['branch'].id}&product_id={f['product'].id}",employee=user)
    assert item.status_code==200 and item.get_json()['data']['cost'] is None
    meta=f['storage_api']('/meta',employee=user).get_json()['data']
    assert meta['can_edit'] is False and {row['branch_id'] for row in meta['places']}=={f['branch'].id}
    assert f['storage_api'](f"/item?branch_id={f['destination'].id}&product_id={f['product'].id}",employee=user).status_code==403
    assert f['storage_api']('/locations',payload,employee=user).status_code==403


def test_current_permission_is_checked_before_replay_after_revocation(storage_api):
    from models.role import Role
    f=storage_api;location,payload=site(f)
    f['admin'].role='cashier';f['admin'].roles.append(Role(name='revoked-'+uuid4().hex));f['db'].session.commit()
    response=f['storage_api']('/locations',payload)
    assert response.status_code==403


def test_legacy_read_endpoints_do_not_migrate_under_query_only(storage_api):
    from modules.inventory_locations.models import InventoryStorageLocation,InventoryLotPlacement,InventoryStorageTransfer,InventoryStorageTransferLayer
    from sqlalchemy import inspect,text
    f=storage_api
    for model in (InventoryStorageTransferLayer,InventoryStorageTransfer,InventoryLotPlacement,InventoryStorageLocation):
        model.__table__.drop(bind=f['db'].session.connection(),checkfirst=True)
    f['db'].session.commit();connection=f['db'].session.connection()
    connection.execute(text('PRAGMA query_only=ON'))
    try:
        assert f['storage_api']('/meta').status_code==200
        assert f['storage_api'](f"/item?branch_id={f['branch'].id}&product_id={f['product'].id}").status_code==200
        assert f['storage_api'](f"/transfers?branch_id={f['branch'].id}").get_json()['data']['items']==[]
        stocks=f['storage_api'](f"/stocks?branch_id={f['branch'].id}&q=STOCK-OPS")
        assert stocks.status_code==200,stocks.get_json()
        assert stocks.get_json()['data']['items'][0]['quantity']==6
        assert not inspect(connection).has_table('inventory_storage_location')
    finally:connection.execute(text('PRAGMA query_only=OFF'))


def test_stock_list_partitions_locations_without_adding_a_second_quantity(storage_api):
    f=storage_api;location,_=site(f)
    main=f['storage_api'](f"/stocks?branch_id={f['branch'].id}&q=STOCK-OPS").get_json()['data']
    child=f['storage_api'](f"/stocks?branch_id={f['branch'].id}&location_id={location['id']}&q=STOCK-OPS").get_json()['data']
    assert main['total']==1 and child['total']==1
    assert main['items'][0]['quantity']==6 and child['items'][0]['quantity']==0
    assert main['items'][0]['name']==f['product'].name and main['items'][0]['sku']=='STOCK-OPS'
