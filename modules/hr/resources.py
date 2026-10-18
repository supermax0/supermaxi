"""Private personnel documents, existing fixed assets and employment exit."""
import base64
import binascii
import hashlib
import json
from datetime import datetime
from flask import abort
from extensions import db
from models.fixed_asset import FixedAsset
from models.employee import Employee
from .common import (BAGHDAD, actor, audit, can, day, integer, json_text, own,
                     person, require, text, version)
from .models import (HRPrivateDocument, HRAssetCustody, HROffboarding,
                     HRPayrollItem, HRPayrollRun, HRAdvance, HRPayAdjustment)


def document_access(employee):
    if not (can("hr.documents.view") or own(employee)):
        require("hr.documents.view")


def document_metadata(row):
    return {"id": row.id, "title": row.title, "kind": row.kind, "filename": row.filename,
            "mime": row.mime, "size": len(row.content), "sha256": row.sha256,
            "expires_on": row.expires_on.isoformat() if row.expires_on else "",
            "date": row.created_at.isoformat() + "Z"}


def save_document(payload):
    require("hr.resources.manage")
    employee = person(payload["person_id"])
    encoded = payload.get("content")
    if not isinstance(encoded, str) or len(encoded) > 5592408:
        raise ValueError("حجم المستند يجب ألا يتجاوز 4 ميغابايت")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("محتوى الملف غير صحيح") from None
    if not content or len(content) > 4 * 1024 * 1024:
        raise ValueError("الملف فارغ أو يتجاوز الحجم المسموح")
    mime = text(payload.get("mime"), limit=80, required=True)
    signatures = {"application/pdf": b"%PDF-", "image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff"}
    if mime not in signatures or not content.startswith(signatures[mime]):
        raise ValueError("ارفع PDF أو صورة PNG/JPEG صحيحة")
    filename = text(payload.get("filename"), limit=160, required=True)
    if "/" in filename or "\\" in filename:
        raise ValueError("اسم الملف غير صحيح")
    kind = payload.get("kind", "other")
    if kind not in ("contract", "identity", "certificate", "medical", "other", "photo"):
        raise ValueError("نوع المستند غير صحيح")
    if kind == "photo":
        from io import BytesIO
        import warnings
        from PIL import Image, UnidentifiedImageError
        if mime not in ("image/png", "image/jpeg"):
            raise ValueError("صورة الموظف يجب أن تكون PNG أو JPEG")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as source:
                    if source.width * source.height > 8000000:
                        raise ValueError("أبعاد الصورة كبيرة جداً")
                    source.load()
                    source.thumbnail((160,160))
                    thumb = BytesIO()
                    source.convert("RGB").save(thumb, format="JPEG", quality=80)
            content, mime = thumb.getvalue(), "image/jpeg"
            filename = "employee-photo.jpg"
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ValueError("الصورة غير صالحة أو تتجاوز الحجم المسموح") from None
    row = HRPrivateDocument(person_id=employee.id, title=text(payload.get("title"), limit=160, required=True),
        kind=kind, filename=filename, mime=mime, content=content, sha256=hashlib.sha256(content).hexdigest(),
        expires_on=day(payload["expires_on"]) if payload.get("expires_on") else None, created_by=actor().id)
    db.session.add(row)
    db.session.flush()
    audit("document.create", row.id, person_id=employee.id, detail={"sha256": row.sha256, "kind": kind})
    return {"id": row.id}


def document_content(document_id):
    row = db.session.get(HRPrivateDocument, integer(document_id, minimum=1))
    if not row:
        abort(404)
    document_access(person(row.person_id))
    audit("document.read", row.id, person_id=row.person_id)
    db.session.commit()
    return {**document_metadata(row), "content": base64.b64encode(row.content).decode("ascii")}


def assign_asset(payload):
    require("hr.resources.manage")
    employee = person(payload["person_id"], lock=True)
    if employee.status != "active":
        raise ValueError("العهدة تحتاج موظفاً نشطاً")
    asset = FixedAsset.query.filter_by(id=integer(payload["asset_id"], minimum=1)).with_for_update().first()
    if not asset or asset.branch_id != employee.branch_id or asset.status not in ("active", "fully_depreciated"):
        raise ValueError("اختر أصلاً فعالاً من فرع الموظف")
    if HRAssetCustody.query.filter_by(active_asset_id=asset.id).first():
        raise ValueError("الأصل بعهدة موظف آخر؛ سجّل إرجاعه أولاً")
    if asset.responsible_user_id and asset.responsible_user_id != employee.employee_id:
        raise ValueError("الأصل مرتبط بمسؤول آخر في صفحة الأصول")
    row = HRAssetCustody(person_id=employee.id, asset_id=asset.id, active_asset_id=asset.id,
                         note=text(payload.get("note", ""), limit=500), created_by=actor().id)
    asset.responsible_user_id = employee.employee_id
    db.session.add(row)
    db.session.flush()
    audit("asset.assign", row.id, person_id=employee.id, detail={"asset_id": asset.id})
    return {"id": row.id, "version": row.version}


def return_asset(payload):
    require("hr.resources.manage")
    row = db.session.get(HRAssetCustody, integer(payload["custody_id"], minimum=1))
    if not row:
        abort(404)
    employee = person(row.person_id, lock=True)
    version(row, payload)
    if row.returned_at:
        raise ValueError("العهدة مُرجعة مسبقاً")
    row.return_note = text(payload.get("reason"), limit=500, required=True)
    row.returned_at, row.active_asset_id = datetime.utcnow(), None
    asset = db.session.get(FixedAsset, row.asset_id)
    if asset.responsible_user_id == employee.employee_id:
        asset.responsible_user_id = None
    audit("asset.return", row.id, person_id=employee.id, detail={"reason": row.return_note})
    return {"id": row.id, "version": row.version}


def save_adjustment(payload):
    require("hr.payroll.prepare")
    employee = person(payload["person_id"], lock=True)
    from .finance import month_bounds, assert_attendance_editable
    first, _ = month_bounds(payload["month"])
    assert_attendance_editable(employee.id, first)
    if payload.get("kind") not in ("allowance", "deduction"):
        raise ValueError("نوع التسوية غير صحيح")
    row = HRPayAdjustment(person_id=employee.id, month=payload["month"], kind=payload["kind"],
        amount=integer(payload["amount"], minimum=1), title=text(payload.get("title"), limit=160, required=True), created_by=actor().id)
    db.session.add(row)
    db.session.flush()
    audit("payroll.adjustment", row.id, person_id=employee.id, detail={"kind": row.kind, "month": row.month, "amount": row.amount})
    return {"id": row.id}


def terminate_person(payload):
    require("hr.employees.state")
    require("hr.resources.manage")
    employee = person(payload["person_id"], lock=True)
    version(employee, payload)
    on = day(payload["ends_on"])
    if employee.status == "terminated" or on < employee.joined_on or on > datetime.now(BAGHDAD).date():
        raise ValueError("حدد آخر يوم عمل صحيح؛ إنهاء الخدمة المستقبلي يحتاج تنفيذه عند الاستحقاق")
    from .finance import assert_contract_editable
    assert_contract_editable(employee.id, on)
    if HRAssetCustody.query.filter_by(person_id=employee.id, returned_at=None).first():
        raise ValueError("أعد العُهد قبل إكمال إنهاء الخدمة")
    due = int(db.session.query(db.func.coalesce(db.func.sum(HRPayrollItem.net - HRPayrollItem.paid), 0))
              .join(HRPayrollRun).filter(HRPayrollItem.person_id == employee.id, HRPayrollRun.status == "approved").scalar())
    advance = int(db.session.query(db.func.coalesce(db.func.sum(HRAdvance.amount - HRAdvance.repaid), 0))
                  .filter(HRAdvance.person_id == employee.id, HRAdvance.status.in_(("paid", "repaying"))).scalar())
    if advance and payload.get("advance_agreement") is not True:
        raise ValueError("وثّق اتفاق تسوية السلفة المتبقية أولاً")
    if payload.get("disable_login") is True and employee.employee_id:
        require("manage_employees")
        if employee.employee_id == actor().id:
            raise ValueError("لا يمكن إيقاف حساب الدخول الحالي")
        account = db.session.get(Employee, employee.employee_id)
        if account.role == "admin" and Employee.query.filter_by(role="admin", is_active=True).count() <= 1:
            raise ValueError("لا يمكن إيقاف آخر مدير فعال")
        account.is_active = False
    row = HROffboarding(person_id=employee.id, ends_on=on,
        reason=text(payload.get("reason"), limit=500, required=True),
        settlement=json_text({"approved_salary_due": due, "advance_remaining": advance,
            "advance_agreement": payload.get("advance_agreement") is True, "note": text(payload.get("settlement_note", ""), limit=1000)}), created_by=actor().id)
    employee.status = "terminated"
    db.session.add(row)
    db.session.flush()
    from .finance import calculate_person
    from .models import HRCommission,HRLeaveType
    from .commissions import outstanding
    from .attendance import leave_cap,leave_used
    settlement=json.loads(row.settlement)
    settlement["month"]=on.strftime("%Y-%m")
    settlement["earned_payroll"]=calculate_person(employee,settlement["month"])
    settlement["commission_due"]=sum(outstanding(c) for c in HRCommission.query.filter(HRCommission.person_id==employee.id,HRCommission.status.in_(("approved","paid"))).all())
    settlement["commission_pending"]=sum(c.amount for c in HRCommission.query.filter_by(person_id=employee.id,status="pending").all())
    if employee.employee_id:
        from models.employee_commission_line import EmployeeCommissionLine
        imported=db.session.query(HRCommission.legacy_line_id).filter(HRCommission.legacy_line_id.is_not(None))
        settlement["commission_pending"]+=int(db.session.query(db.func.coalesce(db.func.sum(EmployeeCommissionLine.amount),0)).filter(
            EmployeeCommissionLine.employee_id==employee.employee_id,EmployeeCommissionLine.status=="pending",~EmployeeCommissionLine.id.in_(imported)).scalar())
    settlement["leave_balances"]=[{"type":kind.name,"days":max(0,(leave_cap(employee.id,kind)-leave_used(employee.id,kind.id,on.year))/2)}
        for kind in HRLeaveType.query.filter_by(active=True).all() if leave_cap(employee.id,kind) is not None]
    row.settlement=json_text(settlement)
    if employee.employee_id:
        from models.hr import HREmployeeProfile
        legacy=HREmployeeProfile.query.filter_by(employee_id=employee.employee_id).first()
        if legacy:legacy.employment_status="terminated"
    employee.updated_at=datetime.utcnow()
    audit("employee.terminate", row.id, person_id=employee.id, detail={"ends_on": on.isoformat(), "settlement": row.settlement})
    return {"id": row.id, "version": employee.version}


def change_person_state(payload):
    require("hr.employees.state")
    employee=person(payload["person_id"],lock=True)
    version(employee,payload)
    state=payload.get("status")
    if employee.status=="terminated" or state not in ("active","suspended","leave"):
        raise ValueError("الحالة غير متاحة؛ الموظف المنتهية خدمته يحتاج إجراء تعيين جديد")
    reason=text(payload.get("reason"),limit=500,required=True)
    if payload.get("change_login") is True and employee.employee_id:
        require("manage_employees")
        account=db.session.get(Employee,employee.employee_id)
        if state!="active" and (account.id==actor().id or account.role=="admin" and Employee.query.filter_by(role="admin",is_active=True).count()<=1):
            raise ValueError("لا يمكن إيقاف حسابك الحالي أو آخر مدير فعال")
        account.is_active=state=="active"
    before=employee.status
    employee.status=state
    employee.updated_at=datetime.utcnow()
    if employee.employee_id:
        from models.hr import HREmployeeProfile
        legacy=HREmployeeProfile.query.filter_by(employee_id=employee.employee_id).first()
        if legacy:legacy.employment_status=state
    audit("employee.state",employee.id,person_id=employee.id,detail={"before":before,"after":state,"reason":reason})
    return {"id":employee.id,"version":employee.version}
