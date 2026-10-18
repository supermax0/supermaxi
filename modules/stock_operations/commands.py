import json
from uuid import UUID,uuid5,NAMESPACE_URL
from flask import jsonify,request,session
from sqlalchemy.exc import IntegrityError
from extensions import db
from models.activity_log import ActivityLog
from modules.desktop_api.sync import DesktopSyncReceipt,_receipt_response
from .common import actor,fingerprint,AuditError
from .schema import ensure_schema


def execute(body,branch_id,action):
    user=actor()
    if not isinstance(body,dict):raise AuditError("بيانات العملية غير صحيحة")
    try:key=str(UUID(str(body.get('operation_id',''))))
    except ValueError:raise AuditError("معرّف العملية غير صالح") from None
    namespace=str(uuid5(NAMESPACE_URL,f"finora-stock-operations:{session['tenant_slug']}"))
    stamp=fingerprint({'path':request.path,'body':body})
    ensure_schema()
    ActivityLog.__table__.create(bind=db.session.connection(),checkfirst=True)
    previous=DesktopSyncReceipt.query.filter_by(device_id=namespace,operation_id=key).first()
    if previous:return _receipt_response(previous,user.id,branch_id,stamp)
    receipt=DesktopSyncReceipt(device_id=namespace,operation_id=key,employee_id=user.id,
        branch_id=branch_id,fingerprint=stamp)
    db.session.add(receipt)
    try:db.session.flush()
    except IntegrityError:
        db.session.rollback()
        previous=DesktopSyncReceipt.query.filter_by(device_id=namespace,operation_id=key).first()
        if previous:return _receipt_response(previous,user.id,branch_id,stamp)
        raise
    try:
        result,evidence=action(user)
        label={'stock_transfer':'تحويل مخزون','inventory_writeoff':'سند تلف','stock_reorder_rule':'حد إعادة الطلب','warehouse':'مخزن'}.get(result['type'],'مستند مخزني')
        event=ActivityLog(employee_id=user.id,employee_name=user.name,branch_id=branch_id,action="stock_command",
            category="inventory",entity_type=result['type'],entity_id=str(result['id']),
            summary=f"عملية مخزون موثقة · {label} #{result['id']}",request_method=request.method,
            request_path=request.path,status_code=200)
        event.set_payload({'operation_id':key,**evidence});db.session.add(event)
        response={'success':True,'data':result,'operation_id':key}
        receipt.response_json=json.dumps(response,ensure_ascii=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return jsonify(response)

