"""Employment profiles and dated contracts, independent of login accounts."""
import json
from datetime import datetime
from uuid import uuid4
from sqlalchemy import or_
from extensions import db
from models.employee import Employee
from models.branch import Branch
from .common import (BAGHDAD, actor, audit, branch, can, day, department_for, finance_visible, own,
                     integer, json_text, people_query, person, require, text, version)
from .models import HRContract, HRDepartment, HRPerson, HRAudit, HRRecord

PERSON_FIELDS = {"name", "code", "phone", "phone2", "email", "address", "emergency_name", "emergency_phone",
                 "branch_id", "department_id", "job_title", "manager_id", "joined_on", "contract_type", "contract_end", "notes"}
PAY_RULE_FIELDS = {"overtime_hourly_bonus", "late_minute_penalty", "absence_daily_penalty"}
FINANCIAL_FIELDS = {"salary", "salary_type", "effective_from"} | PAY_RULE_FIELDS
PRIVATE_FIELDS={"birth_date","national_id","gender","bank_name","bank_account"}
SALARY_TYPES = {"monthly", "weekly", "daily", "hourly", "commission", "monthly_commission"}


def serialize(row, departments=None, branches=None):
    departments = departments or {}
    branches = branches or {}
    result = {field: getattr(row, field) or "" for field in
              ("id", "code", "name", "phone", "phone2", "email", "address", "emergency_name", "emergency_phone", "job_title", "status", "contract_type", "notes")}
    result.update(branch_id=row.branch_id, branch=branches.get(row.branch_id, ""),
                  department_id=row.department_id, department=departments.get(row.department_id, ""),
                  employee_id=row.employee_id, manager_id=row.manager_id, version=row.version,
                  joined_on=row.joined_on.isoformat(), contract_end=row.contract_end.isoformat() if row.contract_end else "",
                  updated_at=row.updated_at.isoformat() + "Z")
    from .models import HRPrivateDocument
    import base64
    photo = getattr(row, "_hr_photo", None)
    if not hasattr(row, "_hr_photo"):
        photo = HRPrivateDocument.query.filter_by(person_id=row.id, kind="photo").order_by(HRPrivateDocument.id.desc()).first()
    result["photo_data"] = "data:image/jpeg;base64," + base64.b64encode(photo.content).decode("ascii") if photo else None
    current = getattr(row, "_hr_current_contract", None)
    if not hasattr(row, "_hr_current_contract"):
        current = HRContract.query.filter(HRContract.person_id == row.id, HRContract.effective_from <= datetime.now(BAGHDAD).date()).order_by(HRContract.effective_from.desc()).first()
    terms=json.loads(current.terms) if current else {}
    result["contract_type"]=terms.get("contract_type",result["contract_type"])
    result["contract_end"]=terms.get("contract_end",result["contract_end"])
    if finance_visible(row):
        result.update(salary=row.salary, salary_type=row.salary_type)
        result.update(terms)
    return result


def list_people(args):
    query = people_query()
    search = text(args.get("search", ""), limit=150)
    if search:
        like = f"%{search}%"
        query = query.outerjoin(HRDepartment, HRDepartment.id == HRPerson.department_id).filter(or_(
            HRPerson.name.ilike(like), HRPerson.phone.ilike(like), HRPerson.code.ilike(like),
            HRPerson.email.ilike(like), HRPerson.job_title.ilike(like), HRDepartment.name.ilike(like)))
    for key, column in (("status", HRPerson.status), ("contract_type", HRPerson.contract_type)):
        if args.get(key):
            query = query.filter(column == text(args[key], limit=30))
    for key, column in (("department_id", HRPerson.department_id), ("branch_id", HRPerson.branch_id)):
        if args.get(key):
            query = query.filter(column == integer(args[key], minimum=1))
    if args.get("joined_from"):
        query = query.filter(HRPerson.joined_on >= day(args["joined_from"]))
    if args.get("joined_to"):
        query = query.filter(HRPerson.joined_on <= day(args["joined_to"]))
    total = query.count()
    page = integer(args.get("page", 1), minimum=1, maximum=100000)
    size = integer(args.get("page_size", 25), minimum=1, maximum=100)
    sort = {"name": HRPerson.name, "code": HRPerson.code, "recent": HRPerson.updated_at.desc()}.get(args.get("sort"), HRPerson.name)
    rows = query.order_by(sort, HRPerson.id).offset((page - 1) * size).limit(size).all()
    contracts = HRContract.query.filter(HRContract.person_id.in_([r.id for r in rows]),
        HRContract.effective_from <= datetime.now(BAGHDAD).date()).order_by(HRContract.effective_from.desc()).all()
    current_contracts = {}
    for contract in contracts:
        current_contracts.setdefault(contract.person_id, contract)
    for row in rows:
        row._hr_current_contract = current_contracts.get(row.id)
    from .models import HRPrivateDocument
    photos = {}
    for photo in HRPrivateDocument.query.filter(HRPrivateDocument.person_id.in_([r.id for r in rows]), HRPrivateDocument.kind == "photo").order_by(HRPrivateDocument.id.desc()).all():
        photos.setdefault(photo.person_id, photo)
    for row in rows:
        row._hr_photo = photos.get(row.id)
    departments = {d.id: d.name for d in HRDepartment.query.all()}
    branches = {b.id: b.name for b in Branch.query.all()}
    from .attendance import attendance_rows
    today = attendance_rows(rows if can("hr.attendance.view") else [r for r in rows if own(r)])
    return {"rows": [{**serialize(row, departments, branches), "attendance": today.get(row.id) if can("hr.attendance.view") or own(row) else None} for row in rows],
            "total": total, "page": page, "page_size": size, "total_pages": max(1, (total + size - 1) // size)}


def save_person(payload, target=None):
    require("hr.employees.edit" if target else "hr.employees.create")
    allowed = PERSON_FIELDS | FINANCIAL_FIELDS | PRIVATE_FIELDS | {"version", "employee_id"}
    if set(payload) - allowed:
        raise ValueError("حقول الموظف غير معروفة")
    if (FINANCIAL_FIELDS | {"contract_type", "contract_end"} | ({"joined_on"} if target else set())).intersection(payload) and not can("hr.payroll.prepare"):
        raise PermissionError("يلزم صلاحية إعداد الرواتب لتعديل البيانات المالية")
    row = person(target, lock=True) if target else HRPerson(code=f"PENDING-{uuid4().hex[:20]}", name="", joined_on=day(payload["joined_on"]), branch_id=branch(payload))
    if target:
        version(row, payload)
    old_salary = {"salary": row.salary or 0, "salary_type": row.salary_type or "monthly", "contract_type": row.contract_type or "full_time", "contract_end":row.contract_end.isoformat() if row.contract_end else ""}
    financial_input=bool((FINANCIAL_FIELDS | {"contract_type","contract_end"}).intersection(payload))
    if target and row.status=="terminated" and financial_input:
        raise ValueError("العقد منتهي الخدمة؛ سجّل تصحيح المستحقات كتسوية مستقلة موثّقة")
    effective_context=day(payload["effective_from"]) if payload.get("effective_from") else datetime.now(BAGHDAD).date()
    contract_query=HRContract.query.filter_by(person_id=row.id)
    if financial_input:
        contract_query=contract_query.filter(HRContract.effective_from <= effective_context)
    previous_contract = contract_query.order_by(HRContract.effective_from.desc()).first() if target else None
    previous_rules = json.loads(previous_contract.terms) if previous_contract else {}
    if target and financial_input and previous_contract:
        old_salary.update({key:previous_rules.get(key,old_salary[key]) for key in old_salary})
        row.salary,row.salary_type,row.contract_type=old_salary["salary"],old_salary["salary_type"],old_salary["contract_type"]
        row.contract_end=day(old_salary["contract_end"]) if old_salary["contract_end"] else None
    old_salary.update({key:previous_rules.get(key,0) for key in PAY_RULE_FIELDS})
    if "branch_id" in payload:
        new_branch = branch(payload)
        if target and new_branch != row.branch_id:
            require("hr.resources.manage")
            from .models import HRAssetCustody,HRAdvance,HRPayrollItem,HRPayrollRun,HRCommission
            if row.employee_id and db.session.get(Employee,row.employee_id).branch_id not in (None,new_branch):
                raise ValueError("انقل حساب الدخول إلى الفرع الجديد أولاً")
            if HRAssetCustody.query.filter_by(person_id=row.id,returned_at=None).first():
                raise ValueError("أعد العهد قبل نقل الموظف إلى فرع آخر")
            if HRAdvance.query.filter(HRAdvance.person_id==row.id,HRAdvance.status.in_(("pending","approved","paid","repaying"))).first():
                raise ValueError("سوِّ طلبات السلف والرصيد المتبقي قبل نقل الموظف")
            if HRPayrollItem.query.join(HRPayrollRun,HRPayrollRun.id==HRPayrollItem.run_id).filter(HRPayrollItem.person_id==row.id,
                db.or_(HRPayrollRun.status!="approved",HRPayrollItem.paid<HRPayrollItem.net)).first():
                raise ValueError("أكمل مسير الموظف وصرف مستحقاته قبل النقل")
            if HRCommission.query.filter(HRCommission.person_id==row.id,HRCommission.status.in_(("pending","approved")),HRCommission.amount>HRCommission.paid).first():
                raise ValueError("سوِّ العمولات المتبقية قبل نقل الموظف")
        row.branch_id = new_branch
    for field in PERSON_FIELDS - {"branch_id", "department_id", "manager_id", "joined_on", "contract_end"}:
        if field in payload:
            setattr(row, field, text(payload[field], limit=1000 if field == "notes" else 255 if field == "address" else 40 if field == "code" else 30 if field in ("phone", "phone2", "emergency_phone", "contract_type") else 100 if field in ("job_title", "emergency_name") else 150, required=field in ("name", "code")))
    if not row.name:
        raise ValueError("أدخل اسم الموظف")
    if row.email:
        from utils.signup_email_verify import normalize_email, is_valid_email
        if not is_valid_email(row.email):
            raise ValueError("البريد الإلكتروني غير صحيح")
        row.email=normalize_email(row.email)
    if "joined_on" in payload:
        if target and day(payload["joined_on"])!=row.joined_on:
            from .finance import assert_contract_editable
            assert_contract_editable(row.id,min(row.joined_on,day(payload["joined_on"])))
        row.joined_on = day(payload["joined_on"])
    if "contract_end" in payload:
        row.contract_end = day(payload["contract_end"]) if payload["contract_end"] else None
    if row.contract_end and row.contract_end < row.joined_on:
        raise ValueError("انتهاء العقد قبل التعيين")
    if "department_id" in payload:
        row.department_id = department_for(payload["department_id"], row.branch_id)
    elif row.department_id:
        department_for(row.department_id, row.branch_id)
    if "manager_id" in payload:
        manager = person(payload["manager_id"]) if payload["manager_id"] else None
        if manager and (manager.id == row.id or manager.branch_id != row.branch_id):
            raise ValueError("المدير المباشر غير صحيح")
        visited={row.id}
        ancestor=manager
        while ancestor:
            if ancestor.id in visited:
                raise ValueError("اختيار المدير يؤدي إلى حلقة في التسلسل الإداري")
            visited.add(ancestor.id)
            ancestor=db.session.get(HRPerson,ancestor.manager_id) if ancestor.manager_id else None
        row.manager_id = manager.id if manager else None
    if "employee_id" in payload:
        require("hr.resources.manage")
        require("manage_employees")
        account = db.session.get(Employee, integer(payload["employee_id"], minimum=1)) if payload["employee_id"] else None
        if account and account.branch_id not in (None, row.branch_id):
            raise ValueError("حساب الدخول لا يتبع فرع الموظف")
        row.employee_id = account.id if account else None
    if "salary" in payload:
        row.salary = integer(payload["salary"])
    if "salary_type" in payload:
        if payload["salary_type"] not in SALARY_TYPES:
            raise ValueError("نوع الأجر غير صحيح")
        row.salary_type = payload["salary_type"]
    row.updated_at = datetime.utcnow()
    db.session.add(row)
    db.session.flush()
    if not target and row.code.startswith("PENDING-"):
        row.code = f"EMP-{row.id:03}"
    if PRIVATE_FIELDS.intersection(payload):
        from .models import HRPersonalInfo
        require("hr.resources.manage")
        if {"birth_date","national_id","gender"}.intersection(payload):require("hr.documents.view")
        if {"bank_name","bank_account"}.intersection(payload):require("hr.payroll.prepare")
        info=db.session.get(HRPersonalInfo,row.id)
        if not info:
            info=HRPersonalInfo(id=row.id)
            db.session.add(info)
        else:info.version+=1
        for field in PRIVATE_FIELDS.intersection(payload)-{"birth_date","gender"}:
            setattr(info,field,text(payload[field],limit=80 if field=="national_id" else 100))
        if "gender" in payload:
            if payload["gender"] not in ("","male","female","other"):raise ValueError("الجنس غير صحيح")
            info.gender=payload["gender"]
        if "birth_date" in payload:
            info.birth_date=day(payload["birth_date"]) if payload["birth_date"] else None
            if info.birth_date and (info.birth_date.year<1900 or info.birth_date>datetime.now(BAGHDAD).date()):raise ValueError("تاريخ الميلاد غير صحيح")
    if row.employee_id:
        from models.hr import HREmployeeProfile
        account = db.session.get(Employee, row.employee_id)
        account.name, account.phone = row.name, row.phone or None
        legacy = HREmployeeProfile.query.filter_by(employee_id=row.employee_id).first()
        if legacy is None:
            legacy = HREmployeeProfile(employee_id=row.employee_id)
            db.session.add(legacy)
        legacy.employee_code, legacy.department_id, legacy.job_title = row.code, row.department_id, row.job_title
        legacy.email, legacy.address, legacy.notes = row.email, row.address, row.notes
        legacy.hire_date, legacy.contract_end, legacy.employment_type = row.joined_on, row.contract_end, row.contract_type
        legacy.emergency_contact_name,legacy.emergency_contact_phone=row.emergency_name,row.emergency_phone
        if PRIVATE_FIELDS.intersection(payload):
            for field in PRIVATE_FIELDS:setattr(legacy,field,getattr(info,field))
    new_salary = {"salary": row.salary, "salary_type": row.salary_type, "contract_type": row.contract_type, "contract_end":row.contract_end.isoformat() if row.contract_end else ""}
    new_salary.update({key:integer(payload.get(key,old_salary[key])) for key in PAY_RULE_FIELDS})
    if not target or new_salary != old_salary:
        effective = day(payload["effective_from"]) if payload.get("effective_from") else row.joined_on if not target else None
        if effective is None:
            raise ValueError("حدد تاريخ سريان التعديل المالي أو العقد")
        from .finance import assert_contract_editable
        assert_contract_editable(row.id, effective)
        existing = HRContract.query.filter_by(person_id=row.id, effective_from=effective).first()
        if existing:
            db.session.add(HRRecord(person_id=row.id, kind="contract_revision", created_by=actor().id,
                payload=json_text({"contract_id": existing.id, "effective_from": effective.isoformat(), **json.loads(existing.terms)})))
            existing.terms, existing.created_by = json_text(new_salary), actor().id
        else:
            db.session.add(HRContract(person_id=row.id, effective_from=effective, terms=json_text(new_salary), created_by=actor().id))
    audit("employee.update" if target else "employee.create", row.id, person_id=row.id,
          detail={"fields": sorted(set(payload) - {"version"}), "version": row.version})
    person(row.id)  # Scope restrictions apply to new profiles and transfers, too.
    return {"id": row.id, "version": row.version}


def details(person_id):
    row = person(person_id)
    departments = {d.id: d.name for d in HRDepartment.query.all()}
    branches = {b.id: b.name for b in Branch.query.all()}
    from .attendance import attendance_rows
    result = {"person": serialize(row, departments, branches), "attendance": attendance_rows([row]).get(row.id) if can("hr.attendance.view") or own(row) else None,
              "history": [], "contracts": [], "documents": [], "assets": [], "leave_balances": [], "adjustments": [], "commission_policies": [],"private_info":{},"offboarding":None}
    from .models import HROffboarding
    exit_row=HROffboarding.query.filter_by(person_id=row.id).first()
    if exit_row:
        result["offboarding"]={"ends_on":exit_row.ends_on.isoformat(),"reason":exit_row.reason,
            "settlement":json.loads(exit_row.settlement) if finance_visible(row) else {}}
        if not own(row):
            frozen=result["offboarding"]["settlement"]
            if not can("hr.commission.view"):
                for key in ("commission_due","commission_pending"):frozen.pop(key,None)
            if not can("hr.advance.view"):
                for key in ("advance_remaining","advance_agreement"):frozen.pop(key,None)
    from .models import HRPersonalInfo
    info=db.session.get(HRPersonalInfo,row.id)
    if info and (can("hr.documents.view") or own(row)):
        result["private_info"].update(birth_date=info.birth_date.isoformat() if info.birth_date else "",national_id=info.national_id,gender=info.gender)
    if info and finance_visible(row):
        result["private_info"].update(bank_name=info.bank_name,bank_account=info.bank_account)
    from .models import HRPrivateDocument, HRAssetCustody, HRLeaveType, HRLeave, HRPayAdjustment
    from .resources import document_metadata
    if can("hr.documents.view") or own(row):
        result["documents"] = [document_metadata(d) for d in HRPrivateDocument.query.filter_by(person_id=row.id).order_by(HRPrivateDocument.id.desc()).all()]
    if can("hr.resources.manage") or own(row):
        from models.fixed_asset import FixedAsset
        custodies = HRAssetCustody.query.filter_by(person_id=row.id).order_by(HRAssetCustody.id.desc()).all()
        assets = {a.id: a for a in FixedAsset.query.filter(FixedAsset.id.in_([c.asset_id for c in custodies])).all()}
        result["assets"] = [{"id": c.id, "asset_id": c.asset_id, "name": assets[c.asset_id].name,
            "code": assets[c.asset_id].asset_code, "version": c.version, "note": c.note,
            "returned_at": c.returned_at.isoformat() + "Z" if c.returned_at else None} for c in custodies if c.asset_id in assets]
    if can("hr.leave.manage") or own(row):
        year = datetime.now(BAGHDAD).year
        from .attendance import leave_cap,leave_used
        for kind in HRLeaveType.query.filter_by(active=True).all():
            used,cap=leave_used(row.id,kind.id,year),leave_cap(row.id,kind)
            result["leave_balances"].append({"id":kind.id,"name":kind.name,"used":used/2,
                "remaining":(cap-used)/2 if cap is not None else None})
    if finance_visible(row):
        result["adjustments"] = [{"id": a.id, "month": a.month, "kind": a.kind, "title": a.title, "amount": a.amount}
            for a in HRPayAdjustment.query.filter_by(person_id=row.id).order_by(HRPayAdjustment.id.desc()).limit(50).all()]
    if can("hr.resources.manage") or row.employee_id == actor().id:
        result["history"] = [{"id": item.id, "action": item.action, "date": item.happened_at.isoformat() + "Z",
                               "reference": item.reference} for item in HRAudit.query.filter_by(person_id=row.id).order_by(HRAudit.id.desc()).limit(25).all()]
    if finance_visible(row):
        result["contracts"] = [{"id": c.id, "effective_from": c.effective_from.isoformat(), **json.loads(c.terms)}
                               for c in HRContract.query.filter_by(person_id=row.id).order_by(HRContract.effective_from.desc()).all()]
    if can("hr.commission.view") or own(row):
        from .models import HRCommissionPolicy
        result["commission_policies"] = [{"id": p.id, "effective_from": p.effective_from.isoformat(),
            "kind": p.kind, "rules": json.loads(p.rules)} for p in HRCommissionPolicy.query.filter_by(person_id=row.id)
            .order_by(HRCommissionPolicy.effective_from.desc()).all()]
    return result
