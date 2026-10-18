"""JSON adapters for the native FINORA HR workspace."""
import json
from datetime import datetime
from flask import Blueprint, abort, jsonify, request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.exceptions import HTTPException
from extensions import db
from models.branch import Branch
from models.employee import Employee
from models.employee_commission_line import EmployeeCommissionLine
from utils.branch_scope import allowed_branch_ids
from utils.branch_mode import independent_branches_enabled
from utils.treasury_schema_guard import ensure_treasury_schema
from utils.payroll_schema import ensure_payroll_schema
from utils.treasury_calculations import InsufficientTreasuryBalance
from .common import (BAGHDAD, HR_PERMISSIONS, actor, audit, branch, can, day, ensure_schema, finance_visible,
                     fingerprint, integer, json_text, own, people_query, person, require, text, uuid)
from .models import (HRPerson, HRDepartment, HRShift, HRLeaveType, HRLeave, HRAttendance, HRCommand,
                     HRPayrollRun, HRPayrollItem, HRAdvance, HRRecord)
from .employees import details, list_people, save_person
from .attendance import (attendance_dict, attendance_rows, save_shift, shift_dict, assign_shift,
                         record_attendance, correct_attendance, request_leave, decide_leave)
from .attendance import save_calendar, cancel_leave, save_leave_entitlement, request_correction, decide_correction
from .finance import (month_bounds, prepare_payroll, recalculate_payroll, decide_payroll, pay_payroll, request_advance,
                      decide_advance, pay_advance)
from .resources import save_document, document_content, assign_asset, return_asset, save_adjustment, terminate_person,change_person_state
from .recruitment import (staff_page, save_form, create_link, toggle_link, decide_application,
                          convert_application, application_for, form_for)
from .commissions import (save_policy, assign_invoice, approve_commission, pay_commission,
                          accept_change, import_legacy, workspace_rows, outstanding)
from .models import HRCommission, HRCommissionChange, HRAssetCustody, HRCorrectionRequest

hr_bp = Blueprint("hr_desktop", __name__, url_prefix="/hr")


@hr_bp.after_request
def private_response(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


@hr_bp.get("/api/reports/<kind>/<format_>")
def report_export(kind, format_):
    from .reports import export_report
    return export_report(kind, format_, request.args)


@hr_bp.get("/api/statement")
def financial_statement():
    from .statements import statement
    try:
        return jsonify(statement(request.args))
    except (ValueError,KeyError) as exc:
        return jsonify(success=False,error=str(exc)),400


@hr_bp.before_request
def prepare():
    require("hr.view")
    ensure_treasury_schema()
    ensure_payroll_schema()
    from utils.hr_schema import ensure_hr_schema
    ensure_hr_schema()
    ensure_schema()


@hr_bp.errorhandler(ValueError)
@hr_bp.errorhandler(TypeError)
@hr_bp.errorhandler(KeyError)
def validation_error(error):
    db.session.rollback()
    return jsonify(success=False, error=str(error) if isinstance(error, ValueError) else "بيانات الطلب غير مكتملة أو غير صحيحة"), 400


@hr_bp.errorhandler(PermissionError)
def denied(error):
    db.session.rollback()
    return jsonify(success=False, error=str(error)), 403


@hr_bp.errorhandler(HTTPException)
def http_error(error):
    db.session.rollback()
    return jsonify(success=False, error=error.description), error.code


@hr_bp.errorhandler(InsufficientTreasuryBalance)
def insufficient(error):
    db.session.rollback()
    return jsonify(success=False, error=str(error)), 400


@hr_bp.errorhandler(IntegrityError)
@hr_bp.errorhandler(StaleDataError)
def duplicate(error):
    db.session.rollback()
    return jsonify(success=False, error="السجل موجود مسبقاً أو تغيّر أثناء الحفظ؛ حدّث البيانات وراجع الطلب"), 409


@hr_bp.get("/api/page")
def page():
    return jsonify(list_people(request.args))


@hr_bp.get("/api/notifications")
def notifications():
    from .notifications import alerts
    return jsonify(alerts())


@hr_bp.get("/api/people/<int:person_id>")
def person_details(person_id):
    return jsonify(details(person_id))


@hr_bp.get("/api/corrections")
def corrections():
    from .models import HRCorrectionRequest
    query=people_query()
    if not can("hr.attendance.approve"):
        require("hr.self")
        query=query.filter(HRPerson.employee_id==actor().id)
    names={p.id:{"person_name":p.name,"code":p.code} for p in query.all()}
    rows=HRCorrectionRequest.query.filter(HRCorrectionRequest.person_id.in_(list(names)))
    if request.args.get("person_id"):
        rows=rows.filter_by(person_id=person(request.args["person_id"]).id)
    page=integer(request.args.get("page",1),minimum=1)
    size=25;total=rows.count()
    result=[{"id":r.id,"person_id":r.person_id,**names[r.person_id],"status":r.status,"version":r.version,
             "detail":json.loads(r.payload),"decision":r.decision,"date":r.created_at.isoformat()+"Z"}
            for r in rows.order_by(HRCorrectionRequest.id.desc()).offset((page-1)*size).limit(size).all()]
    return jsonify(rows=result,total=total,page=page,total_pages=max(1,(total+size-1)//size))


@hr_bp.get("/api/calendar")
def calendar_view():
    employee=person(request.args.get("person_id"))
    if not (can("hr.attendance.view") or can("hr.self") and own(employee)):
        require("hr.attendance.view")
    from .attendance import month_calendar
    month=request.args.get("month",datetime.now(BAGHDAD).strftime("%Y-%m"))
    return jsonify(rows=month_calendar(employee,month),month=month,person_id=employee.id)


@hr_bp.get("/api/documents/<int:document_id>")
def private_document(document_id):
    response = jsonify(document_content(document_id))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@hr_bp.get("/api/recruitment")
def recruitment_page():
    return jsonify(staff_page(request.args))


@hr_bp.get("/api/applicant-files/<int:file_id>")
def applicant_file(file_id):
    import base64
    from .models import HRApplicantFile
    row = db.session.get(HRApplicantFile, file_id)
    if not row:
        abort(404)
    application_for(row.application_id)
    audit("recruitment.file_view", row.id)
    db.session.commit()
    response = jsonify(filename=row.filename, mime=row.mime, content=base64.b64encode(row.content).decode("ascii"))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@hr_bp.get("/api/lookups")
def lookups():
    branches = Branch.query.filter(Branch.is_active.is_(True))
    if independent_branches_enabled():
        branches = branches.filter(Branch.id.in_(allowed_branch_ids()))
    permitted = [b.id for b in branches.all()]
    result = {"permissions": [p for p in HR_PERMISSIONS if can(p)],
              "branches": [{"id": b.id, "name": b.name} for b in branches.order_by(Branch.name).all()],
              "departments": [{"id": d.id, "name": d.name, "branch_id": d.branch_id, "version": d.version}
                              for d in HRDepartment.query.filter((HRDepartment.branch_id.in_(permitted) | HRDepartment.branch_id.is_(None)), HRDepartment.is_active.is_(True)).all()],
              "shifts": [shift_dict(s) for s in HRShift.query.filter(HRShift.branch_id.in_(permitted), HRShift.active.is_(True)).all()],
              "leave_types": [{"id": t.id, "name": t.name, "paid": t.paid, "yearly_half_days": t.yearly_half_days}
                              for t in HRLeaveType.query.filter_by(active=True).all()], "treasury_accounts": [], "accounts": [], "assets": [], "access_scopes": []}
    if can("hr.settings.manage") and can("manage_employees"):
        from .models import HRAccessScope
        result["access_scopes"] = [{"employee_id": s.employee_id, "mode": s.mode, "department_id": s.department_id,
            "version": s.version} for s in HRAccessScope.query.join(Employee, Employee.id == HRAccessScope.employee_id)
            .filter(Employee.branch_id.in_(permitted)).all()]
    from .models import HRCalendarDay
    from datetime import timedelta
    today=datetime.now(BAGHDAD).date()
    result["calendar"]=[{"id":c.id,"branch_id":c.branch_id,"on_date":c.on_date.isoformat(),"title":c.title,"working":c.working,"version":c.version}
        for c in HRCalendarDay.query.filter(HRCalendarDay.branch_id.in_(permitted),HRCalendarDay.on_date >= today-timedelta(days=365),
        HRCalendarDay.on_date <= today+timedelta(days=400)).order_by(HRCalendarDay.on_date).all()]
    if can("hr.payroll.pay") or can("hr.advance.pay") or can("hr.commission.pay"):
        from models.treasury_account import TreasuryAccount
        result["treasury_accounts"] = [{"id": a.id, "name": a.name, "branch_id": a.branch_id}
                                      for a in TreasuryAccount.query.filter_by(is_active=True).all() if a.branch_id in permitted or not independent_branches_enabled()]
    if can("hr.resources.manage"):
        result["accounts"] = [{"id": e.id, "name": e.name, "branch_id": e.branch_id} for e in Employee.query.all()
                              if e.branch_id in permitted or not independent_branches_enabled()]
        from models.fixed_asset import FixedAsset
        from .models import HRAssetCustody
        occupied = db.session.query(HRAssetCustody.active_asset_id).filter(HRAssetCustody.active_asset_id.is_not(None))
        result["assets"] = [{"id": a.id, "name": f"{a.asset_code} · {a.name}", "branch_id": a.branch_id}
                            for a in FixedAsset.query.filter(FixedAsset.branch_id.in_(permitted), FixedAsset.status.in_(("active", "fully_depreciated")),
                                                             FixedAsset.id.notin_(occupied)).all()]
    return jsonify(result)


@hr_bp.get("/api/overview")
def overview():
    rows = people_query().filter(HRPerson.status == "active").all()
    today = attendance_rows(rows if can("hr.attendance.view") else [r for r in rows if own(r)])
    counts = {key: sum(1 for r in today.values() if r["state"] == key) for key in ("present", "late", "absent", "leave", "scheduled", "unscheduled")}
    result = {"employees": len(rows), "attendance": counts, "salaries": None, "salary_paid": None,
              "advances": None, "commissions": None}
    ids = [p.id for p in people_query().all()]
    if can("hr.payroll.view"):
        month = datetime.now(BAGHDAD).strftime("%Y-%m")
        totals = (db.session.query(db.func.coalesce(db.func.sum(HRPayrollItem.net), 0), db.func.coalesce(db.func.sum(HRPayrollItem.paid), 0))
                  .join(HRPayrollRun).filter(HRPayrollItem.person_id.in_(ids), HRPayrollRun.month == month, HRPayrollRun.status == "approved").one())
        result["salaries"], result["salary_paid"] = int(totals[0]), int(totals[1])
    if can("hr.advance.view"):
        result["advances"] = int(db.session.query(db.func.coalesce(db.func.sum(HRAdvance.amount - HRAdvance.repaid), 0))
                                 .filter(HRAdvance.person_id.in_(ids), HRAdvance.status.in_(("paid", "repaying"))).scalar())
    if can("hr.commission.view"):
        account_ids = [p.employee_id for p in rows if p.employee_id]
        result["commissions"] = int(db.session.query(db.func.coalesce(db.func.sum(EmployeeCommissionLine.amount), 0))
                                    .filter(EmployeeCommissionLine.employee_id.in_(account_ids), EmployeeCommissionLine.status == "pending").scalar())
        result["commissions"] += sum(outstanding(r) for r in HRCommission.query.filter(
            HRCommission.person_id.in_(ids), HRCommission.status.in_(("pending", "approved", "paid"))).all())
    return jsonify(result)


@hr_bp.get("/api/workspace")
def workspace():
    return jsonify(workspace_data(request.args))


def workspace_data(args):
    tab = args.get("tab", "attendance")
    query = people_query()
    if args.get("search"):
        from sqlalchemy import or_
        like = f"%{text(args['search'], limit=150)}%"
        query = query.filter(or_(HRPerson.name.ilike(like), HRPerson.code.ilike(like), HRPerson.phone.ilike(like), HRPerson.job_title.ilike(like)))
    if args.get("status"):
        query = query.filter(HRPerson.status == text(args["status"], limit=20))
    if args.get("person_id"):
        query = query.filter(HRPerson.id == person(args["person_id"]).id)
    if args.get("branch_id"):
        query = query.filter(HRPerson.branch_id == integer(args["branch_id"], minimum=1))
    if args.get("department_id"):
        query = query.filter(HRPerson.department_id == integer(args["department_id"], minimum=1))
    if tab in ("attendance", "leave", "payroll", "advances","commissions"):
        permission = {"attendance": "hr.attendance.view", "leave": "hr.leave.manage", "payroll": "hr.payroll.view", "advances": "hr.advance.view","commissions":"hr.commission.view"}[tab]
        if not can(permission):
            if not can("hr.self"):
                require(permission)
            query = query.filter(HRPerson.employee_id == actor().id)
    elif tab == "resources":
        require("hr.resources.manage")
    else:
        raise ValueError("التبويب غير معروف")
    employees = query.all()
    ids = [p.id for p in employees]
    names = {p.id: {"person_id": p.id, "person_name": p.name, "code": p.code} for p in employees}
    number = integer(args.get("page", 1), minimum=1, maximum=100000)
    size = integer(args.get("page_size", 25), minimum=1, maximum=100)
    offset = (number - 1) * size
    result = []
    total = 0
    if tab == "attendance":
        on = day(args["date"]) if args.get("date") else datetime.now(BAGHDAD).date()
        selected = employees[offset:offset + size]
        attendance = attendance_rows(selected, on)
        result = [{**names[p.id], **attendance[p.id]} for p in selected]
        total = len(employees)
    elif tab == "leave":
        rows = HRLeave.query.filter(HRLeave.person_id.in_(ids)).order_by(HRLeave.id.desc())
        total = rows.count()
        types = {t.id: t.name for t in HRLeaveType.query.all()}
        result = [{**names[r.person_id], "id": r.id, "type": types.get(r.type_id, ""), "starts": r.starts.isoformat(),
                   "ends": r.ends.isoformat(), "days": r.half_days / 2, "reason": r.reason, "status": r.status, "version": r.version}
                  for r in rows.offset(offset).limit(size).all()]
    elif tab == "advances":
        rows = HRAdvance.query.filter(HRAdvance.person_id.in_(ids)).order_by(HRAdvance.id.desc())
        total = rows.count()
        result = [{**names[r.person_id], "id": r.id, "amount": r.amount, "repaid": r.repaid, "remaining": r.amount - r.repaid,
                   "instalments": r.instalments, "first_month": r.first_month, "status": r.status, "version": r.version}
                  for r in rows.offset(offset).limit(size).all()]
    elif tab == "payroll":
        month = args.get("month", datetime.now(BAGHDAD).strftime("%Y-%m"))
        month_bounds(month)
        rows = HRPayrollItem.query.join(HRPayrollRun).filter(HRPayrollItem.person_id.in_(ids), HRPayrollRun.month == month).order_by(HRPayrollItem.id)
        total = rows.count()
        runs = {r.id: r for r in HRPayrollRun.query.filter_by(month=month).all()}
        result = [{**names[r.person_id], "id": r.id, "run_id": r.run_id, "run_version": runs[r.run_id].version,
                   "status": runs[r.run_id].status, "gross": r.gross, "deductions": r.deductions, "net": r.net,
                   "paid": r.paid, "remaining": r.net - r.paid, "calculation": json.loads(r.calculation)}
                  for r in rows.offset(offset).limit(size).all()]
    elif tab == "commissions":
        result, total = workspace_rows(employees, names, offset, size)
    elif tab == "resources":
        rows = HRRecord.query.filter(HRRecord.person_id.in_(ids)).order_by(HRRecord.id.desc())
        own_ids=[p.id for p in employees if own(p)]
        if not can("hr.payroll.view"):
            rows=rows.filter(db.or_(HRRecord.kind != "contract_revision",HRRecord.person_id.in_(own_ids)))
        if not can("hr.documents.view"):
            rows=rows.filter(db.or_(HRRecord.kind != "legacy_document",HRRecord.person_id.in_(own_ids)))
        total = rows.count()
        result = [{**names[r.person_id], "id": r.id, "kind": r.kind, "date": r.created_at.isoformat() + "Z",
                   "detail": json.loads(r.payload)} for r in rows.offset(offset).limit(size).all()]
    return dict(rows=result, total=total, page=number, page_size=size, total_pages=max(1, (total + size - 1) // size))


@hr_bp.get("/api/offline")
def offline_profiles():
    from .common import data_revision, access_revision
    directory = list_people(request.args)
    result = {"directory": directory, "details": [details(r["id"]) for r in directory["rows"]],
        "revision":data_revision(),"scope_revision":access_revision(actor())}
    if directory["page"] == 1:
        result["lookups"] = lookups().get_json()
        result["overview"] = overview().get_json()
    return jsonify(result)


@hr_bp.get("/api/offline/revision")
def offline_revision():
    from .common import data_revision,access_revision
    return jsonify(revision=data_revision(),scope_revision=access_revision(actor()))


def save_department(payload):
    require("hr.resources.manage")
    row = HRDepartment(branch_id=branch(payload), name=text(payload.get("name"), limit=100, required=True))
    db.session.add(row)
    db.session.flush()
    audit("department.create", row.id)
    return {"id": row.id}


def save_leave_type(payload):
    require("hr.settings.manage")
    row = HRLeaveType(name=text(payload.get("name"), limit=80, required=True), paid=payload.get("paid") is True,
                      yearly_half_days=integer(payload["yearly_half_days"], maximum=732) if payload.get("yearly_half_days") is not None else None)
    db.session.add(row)
    db.session.flush()
    audit("leave_type.create", row.id)
    return {"id": row.id}


def save_record(payload):
    require("hr.resources.manage")
    employee = person(payload["person_id"], lock=True)
    kind = payload.get("kind")
    if kind not in ("review", "goal", "warning", "note"):
        raise ValueError("نوع السجل غير صحيح")
    content = {"title": text(payload.get("title"), limit=150, required=True), "note": text(payload.get("note", ""), limit=2000),
               "period": text(payload.get("period", ""), limit=30)}
    if kind == "review":
        content["score"] = integer(payload.get("score"), maximum=100)
    row = HRRecord(person_id=employee.id, kind=kind, payload=json_text(content), created_by=actor().id)
    db.session.add(row)
    db.session.flush()
    audit(f"resource.{kind}", row.id, person_id=employee.id)
    return {"id": row.id}


def save_access_scope(payload):
    require("hr.settings.manage")
    require("manage_employees")
    from .models import HRAccessScope
    from .common import department_for
    employee = db.session.get(Employee, integer(payload["employee_id"], minimum=1))
    if not employee or employee.id == actor().id or (independent_branches_enabled() and employee.branch_id not in allowed_branch_ids()):
        raise ValueError("اختر حساب دخول ضمن نطاق إدارتك غير حسابك الحالي")
    mode = payload.get("mode")
    if mode not in ("all", "department", "manager", "self"):
        raise ValueError("نطاق الموارد البشرية غير صحيح")
    department = department_for(payload.get("department_id"), employee.branch_id) if mode == "department" else None
    if mode == "department" and not department:
        raise ValueError("حدد القسم المسموح")
    row = db.session.get(HRAccessScope, employee.id)
    if row:
        version = integer(payload.get("version"), minimum=1)
        if row.version != version:
            abort(409, description="تغيّر نطاق الحساب؛ حدّث البيانات")
        row.version += 1
    else:
        row = HRAccessScope(employee_id=employee.id)
        db.session.add(row)
    row.mode, row.department_id = mode, department
    db.session.flush()
    audit("scope.update", employee.id, detail={"mode": mode, "department_id": department})
    return {"id": employee.id, "version": row.version}


def bulk_people(payload):
    selected=payload.get("people")
    if not isinstance(selected,list) or not 1<=len(selected)<=100:
        raise ValueError("حدد من موظف واحد إلى 100 موظف")
    ids=[integer(p.get("person_id"),minimum=1) for p in selected if isinstance(p,dict)]
    if len(ids)!=len(selected) or len(set(ids))!=len(ids):
        raise ValueError("قائمة الموظفين غير صحيحة")
    reason=text(payload.get("reason"),limit=500,required=True)
    mode=payload.get("mode")
    permissions={"department":"hr.employees.edit","branch":"hr.employees.edit","state":"hr.employees.state","shift":"hr.shifts.manage"}
    if mode not in permissions:raise ValueError("الإجراء الجماعي غير متاح")
    require(permissions[mode])
    result=[]
    for item in selected:
        employee=person(item["person_id"],lock=True)
        data={"person_id":employee.id,"version":item.get("version")}
        if mode=="state":
            result.append(change_person_state({**data,"status":payload.get("status"),"reason":reason}))
        elif mode=="shift":
            result.append(assign_shift({**data,"shift_id":payload.get("shift_id"),"effective_from":payload.get("effective_from")}))
        else:
            field="department_id" if mode=="department" else "branch_id"
            result.append(save_person({"version":item.get("version"),field:payload.get(field)},employee.id))
        audit("employee.bulk",employee.id,person_id=employee.id,detail={"mode":mode,"reason":reason,"count":len(selected)})
    return {"id":ids[0],"count":len(result)}


ACTIONS = {
    "employee.bulk": ("hr.view",lambda p,c:bulk_people(p)),
    "attendance.correction_request": ("hr.attendance.record",lambda p,c:request_correction(p)),
    "attendance.correction_decide": ("hr.attendance.approve",lambda p,c:decide_correction(p)),
    "leave.entitlement": ("hr.settings.manage",lambda p,c:save_leave_entitlement(p)),
    "calendar.save": ("hr.settings.manage",lambda p,c:save_calendar(p)),
    "leave.cancel": ("hr.leave.approve",lambda p,c:cancel_leave(p)),
    "scope.update": ("hr.settings.manage", lambda p, c: save_access_scope(p)),
    "commission.policy": ("hr.commission.manage", lambda p, c: save_policy(p)),
    "commission.assign": ("hr.commission.manage", lambda p, c: assign_invoice(p)),
    "commission.import": ("hr.commission.manage", lambda p, c: import_legacy(p)),
    "commission.approve": ("hr.commission.manage", lambda p, c: approve_commission(p)),
    "commission.pay": ("hr.commission.pay", lambda p, c: pay_commission(p, c)),
    "commission.change": ("hr.commission.manage", lambda p, c: accept_change(p)),
    "employee.create": ("hr.employees.create", lambda p, c: save_person(p)),
    "employee.update": ("hr.employees.edit", lambda p, c: save_person({k: v for k, v in p.items() if k != "person_id"}, p["person_id"])),
    "department.create": ("hr.resources.manage", lambda p, c: save_department(p)),
    "shift.create": ("hr.shifts.manage", lambda p, c: save_shift(p)),
    "shift.assign": ("hr.shifts.manage", lambda p, c: assign_shift(p)),
    "attendance.record": ("hr.attendance.record", lambda p, c: record_attendance(p)),
    "attendance.correct": ("hr.attendance.approve", lambda p, c: correct_attendance(p)),
    "leave.request": ("hr.leave.manage", lambda p, c: request_leave(p)),
    "leave.decide": ("hr.leave.approve", lambda p, c: decide_leave(p)),
    "leave_type.create": ("hr.settings.manage", lambda p, c: save_leave_type(p)),
    "payroll.prepare": ("hr.payroll.prepare", lambda p, c: prepare_payroll(p)),
    "payroll.recalculate": ("hr.payroll.prepare", lambda p, c: recalculate_payroll(p)),
    "payroll.decide": ("hr.payroll.approve", lambda p, c: decide_payroll(p)),
    "payroll.pay": ("hr.payroll.pay", lambda p, c: pay_payroll(p, c)),
    "advance.request": ("hr.advance.create", lambda p, c: request_advance(p)),
    "advance.decide": ("hr.advance.approve", lambda p, c: decide_advance(p)),
    "advance.pay": ("hr.advance.pay", lambda p, c: pay_advance(p)),
    "resource.record": ("hr.resources.manage", lambda p, c: save_record(p)),
    "document.create": ("hr.resources.manage", lambda p, c: save_document(p)),
    "asset.assign": ("hr.resources.manage", lambda p, c: assign_asset(p)),
    "asset.return": ("hr.resources.manage", lambda p, c: return_asset(p)),
    "payroll.adjustment": ("hr.payroll.prepare", lambda p, c: save_adjustment(p)),
    "employee.terminate": ("hr.employees.state", lambda p, c: terminate_person(p)),
    "employee.state": ("hr.employees.state", lambda p,c:change_person_state(p)),
    "recruitment.form": ("hr.recruitment.manage", lambda p, c: save_form(p)),
    "recruitment.link": ("hr.recruitment.manage", lambda p, c: create_link(p)),
    "recruitment.link_state": ("hr.recruitment.manage", lambda p, c: toggle_link(p)),
    "recruitment.decide": ("hr.recruitment.manage", lambda p, c: decide_application(p)),
    "recruitment.convert": ("hr.recruitment.manage", lambda p, c: convert_application(p)),
}


@hr_bp.post("/api/commands")
def command():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"id", "action", "payload"} or not isinstance(body["payload"], dict):
        raise ValueError("بنية الأمر غير صحيحة")
    command_id = uuid(body["id"])
    action = body["action"]
    if action not in ACTIONS:
        raise ValueError("الإجراء غير معروف")
    permission, handler = ACTIONS[action]
    if action == "payroll.decide" and body["payload"].get("status") == "reviewed":
        permission = "hr.payroll.review"
    if action in ("attendance.record", "attendance.correction_request", "leave.request") and can("hr.self") and own(person(body["payload"].get("person_id"))):
        pass
    else:
        require(permission)
    if action.startswith("recruitment."):
        if body["payload"].get("form_id"):
            form_for(body["payload"]["form_id"])
        if body["payload"].get("application_id"):
            application_for(body["payload"]["application_id"])
        if body["payload"].get("link_id"):
            from .models import HRRecruitLink
            link = db.session.get(HRRecruitLink, integer(body["payload"]["link_id"], minimum=1))
            if not link:
                abort(404)
            form_for(link.form_id)
    digest = fingerprint({"action": action, "payload": body["payload"]})
    old = db.session.get(HRCommand, command_id)
    if old:
        if old.actor_id != actor().id or old.fingerprint != digest:
            abort(409, description="معرّف العملية مستخدم لطلب مختلف")
        if body["payload"].get("person_id"):
            person(body["payload"]["person_id"])
        if action=="employee.bulk":
            permissions={"department":"hr.employees.edit","branch":"hr.employees.edit","state":"hr.employees.state","shift":"hr.shifts.manage"}
            require(permissions.get(body["payload"].get("mode"),"hr.employees.edit"))
            for selected in body["payload"].get("people",[]):person(selected["person_id"])
        if body["payload"].get("run_id"):
            from .finance import payroll_run
            payroll_run(body["payload"]["run_id"])
        for key, model in (("item_id", HRPayrollItem), ("advance_id", HRAdvance),
                           ("leave_id", HRLeave), ("attendance_id", HRAttendance),
                           ("commission_id", HRCommission), ("custody_id", HRAssetCustody),
                           ("correction_id", HRCorrectionRequest)):
            if body["payload"].get(key):
                row = db.session.get(model, integer(body["payload"][key], minimum=1))
                if not row:
                    abort(404)
                person(row.person_id)
        if body["payload"].get("change_id"):
            change = db.session.get(HRCommissionChange, integer(body["payload"]["change_id"], minimum=1))
            if not change:
                abort(404)
            person(db.session.get(HRCommission, change.commission_id).person_id)
        if body["payload"].get("legacy_id"):
            line = db.session.get(EmployeeCommissionLine, integer(body["payload"]["legacy_id"], minimum=1))
            if not line or not people_query().filter_by(employee_id=line.employee_id).first():
                abort(404)
        return jsonify(json.loads(old.response))
    receipt = HRCommand(id=command_id, actor_id=actor().id, fingerprint=digest)
    db.session.add(receipt)
    # Acquire the SQLite write lock before any check-then-write financial logic.
    db.session.flush()
    result = {"success": True, **handler(body["payload"], command_id)}
    receipt.response = json_text(result)
    db.session.commit()
    return jsonify(result)
