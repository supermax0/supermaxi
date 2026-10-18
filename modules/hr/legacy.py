"""Preserve existing web HR records when opening the expanded desktop workspace."""
from datetime import datetime, timedelta, timezone
from extensions import db
from .common import BAGHDAD, actor, json_text
from .models import HRPerson, HRWorkRecord, HRLeave, HRLeaveType, HRLegacyLink, HRRecord, HRLeaveDay, HRLeaveEntitlement


def import_history(force=False):
    imported = HRRecord.query.filter_by(kind="legacy_history_import").first()
    if imported and not force:
        freeze_leave_history()
        return
    from models.hr import HRAttendance, HRLeaveRequest, HREmployeeDocument
    profiles = {p.employee_id: p for p in HRPerson.query.filter(HRPerson.employee_id.is_not(None)).all()}
    for old in HRAttendance.query.all():
        if db.session.get(HRLegacyLink, ("attendance", old.id)):
            continue
        profile = profiles.get(old.employee_id)
        if not profile:
            continue
        row = HRWorkRecord.query.filter_by(person_id=profile.id, work_date=old.attendance_date).first()
        if row is None:
            def utc(clock, next_day=False):
                return datetime.combine(old.attendance_date + timedelta(days=int(next_day)), clock, BAGHDAD).astimezone(timezone.utc).replace(tzinfo=None) if clock else None
            check_in = utc(old.check_in)
            check_out = utc(old.check_out, bool(old.check_in and old.check_out and old.check_out < old.check_in))
            row = HRWorkRecord(person_id=profile.id, work_date=old.attendance_date, check_in=check_in, check_out=check_out,
                worked_minutes=max(0, int((check_out-check_in).total_seconds()//60)) if check_in and check_out else 0,
                late_minutes=old.late_minutes, overtime_minutes=old.overtime_minutes,
                shift=json_text({"legacy_state":old.status,"legacy_id":old.id,"legacy_created_at":old.created_at.isoformat() if old.created_at else None}))
            db.session.add(row)
            db.session.flush()
        db.session.add(HRLegacyLink(kind="attendance", source_id=old.id, target_id=row.id))
    kinds = {}
    for old in HRLeaveRequest.query.all():
        if db.session.get(HRLegacyLink, ("leave", old.id)):
            continue
        profile = profiles.get(old.employee_id)
        if not profile:
            continue
        key = old.leave_type or "annual"
        if key not in kinds:
            name = {"annual":"سنوية (السجل السابق)","sick":"مرضية (السجل السابق)","unpaid":"بدون أجر (السجل السابق)"}.get(key, key + " (السجل السابق)")
            kind = HRLeaveType.query.filter_by(name=name).first()
            if not kind:
                kind = HRLeaveType(name=name, paid=key != "unpaid", yearly_half_days=None)
                db.session.add(kind)
                db.session.flush()
            kinds[key] = kind.id
        row = HRLeave(person_id=profile.id, type_id=kinds[key], starts=old.start_date, ends=old.end_date,
            half_day=False, half_days=old.days_count*2, reason=old.reason or "", status=old.status,
            created_by=old.employee_id, approved_by=old.decided_by, created_at=old.created_at)
        db.session.add(row)
        db.session.flush()
        db.session.add(HRLegacyLink(kind="leave", source_id=old.id, target_id=row.id))
    for old in HREmployeeDocument.query.all():
        if db.session.get(HRLegacyLink, ("document", old.id)):
            continue
        profile = profiles.get(old.employee_id)
        if profile:
            # Preserve metadata only; do not fetch or expose legacy external/private URLs.
            record = HRRecord(person_id=profile.id, kind="legacy_document", created_by=actor().id,
                payload=json_text({"title":old.title,"kind":old.document_type,"expiry":old.expiry_date.isoformat() if old.expiry_date else None,"legacy_id":old.id}))
            db.session.add(record)
            db.session.flush()
            db.session.add(HRLegacyLink(kind="document", source_id=old.id, target_id=record.id))
    if not imported:
        db.session.add(HRRecord(kind="legacy_history_import", created_by=actor().id, payload=json_text({"profiles":len(profiles)})))
    freeze_leave_history()


def freeze_leave_history():
    from models.hr import HREmployeeProfile
    from .attendance import is_work_day
    annual=HRLeaveType.query.filter_by(name="سنوية (السجل السابق)").first()
    if not annual and HREmployeeProfile.query.first():
        annual=HRLeaveType(name="سنوية (السجل السابق)",paid=True,yearly_half_days=None)
        db.session.add(annual);db.session.flush()
    if annual:
        profiles={p.employee_id:p for p in HRPerson.query.filter(HRPerson.employee_id.is_not(None)).all()}
        for old in HREmployeeProfile.query.all():
            profile=profiles.get(old.employee_id)
            if profile and not HRLeaveEntitlement.query.filter_by(person_id=profile.id,type_id=annual.id).first():
                db.session.add(HRLeaveEntitlement(person_id=profile.id,type_id=annual.id,
                    yearly_half_days=max(0,int(old.annual_leave_entitlement or 0))*2))
    frozen=db.session.query(HRLeaveDay.leave_id)
    for row in HRLeave.query.filter(HRLeave.status=="approved",~HRLeave.id.in_(frozen)).all():
        profile=db.session.get(HRPerson,row.person_id)
        kind=db.session.get(HRLeaveType,row.type_id)
        calendar=[row.starts+timedelta(days=i) for i in range((row.ends-row.starts).days+1)]
        # Imported day counts are historical facts; retain their total even where the old calendar differs.
        legacy=HRLegacyLink.query.filter_by(kind="leave",target_id=row.id).first()
        dates=calendar if legacy else [on for on in calendar if is_work_day(profile,on)]
        remaining=row.half_days
        for index,on in enumerate(dates):
            amount=remaining if index==len(dates)-1 else min(2,remaining)
            if amount:
                db.session.add(HRLeaveDay(leave_id=row.id,on_date=on,half_days=amount,paid=kind.paid))
                remaining-=amount


def guard_legacy_profile(old,account,form):
    from .common import person
    profile=HRPerson.query.filter_by(employee_id=account.id).first()
    if not profile:return
    person(profile.id)
    checks={"salary":str(int(account.salary or 0)),"pay_type":account.pay_type or "disabled",
        "hire_date":old.hire_date.isoformat() if old.hire_date else "","contract_start":old.contract_start.isoformat() if old.contract_start else "",
        "contract_end":old.contract_end.isoformat() if old.contract_end else "","employment_type":old.employment_type,
        "employment_status":old.employment_status,"is_active":"1" if account.is_active else "0",
        "annual_leave_entitlement":str(old.annual_leave_entitlement or 0)}
    if str(form.get("is_active","0"))!=checks["is_active"] or any(str(form[key]).strip()!=str(value) for key,value in checks.items() if key in form):
        raise ValueError("الأجر والعقد والحالة ورصيد الإجازة تُدار من مساحة FINORA للموظفين لحفظ تواريخ السريان والاعتماد")


def mirror_legacy_profile(old,account):
    from .common import audit,department_for
    from .models import HRPersonalInfo
    profile=HRPerson.query.filter_by(employee_id=account.id).first()
    if not profile:return
    profile.name,profile.phone=account.name,account.phone or ""
    profile.code=old.employee_code or profile.code
    profile.department_id=department_for(old.department_id,profile.branch_id)
    for field in ("job_title","email","address","notes"):
        setattr(profile,field,getattr(old,field) or "")
    profile.emergency_name,profile.emergency_phone=old.emergency_contact_name or "",old.emergency_contact_phone or ""
    info=db.session.get(HRPersonalInfo,profile.id)
    if info:
        for field in ("birth_date","national_id","gender","bank_name","bank_account"):
            setattr(info,field,getattr(old,field) or (None if field=="birth_date" else ""))
        info.version+=1
    profile.version+=1;profile.updated_at=datetime.utcnow()
    audit("employee.legacy_update",profile.id,person_id=profile.id,detail={"source":"web","version":profile.version})


def mirror_attendance(row):
    profile = db.session.get(HRPerson, row.person_id)
    if not profile.employee_id:
        return
    from models.hr import HRAttendance
    old = HRAttendance.query.filter_by(employee_id=profile.employee_id, attendance_date=row.work_date).first()
    if old is None:
        old = HRAttendance(employee_id=profile.employee_id, attendance_date=row.work_date)
        db.session.add(old)
    def clock(value):
        return value.replace(tzinfo=timezone.utc).astimezone(BAGHDAD).time().replace(tzinfo=None) if value else None
    old.check_in, old.check_out = clock(row.check_in), clock(row.check_out)
    old.late_minutes, old.overtime_minutes = row.late_minutes, row.overtime_minutes
    old.status = "late" if row.late_minutes else "present"
    old.notes = "دوام UTC مُدار من مساحة FINORA للموظفين"
