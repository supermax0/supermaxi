"""Baghdad attendance dates, frozen shifts, overnight work and leave approval."""
import json
from datetime import date, datetime, time, timedelta, timezone
from sqlalchemy import or_
from extensions import db
from .common import (BAGHDAD, actor, audit, branch, can, day, integer, json_text,
                     own, people_query, person, require, text, timestamp, version)
from .models import HRAttendance, HRShift, HRShiftAssignment, HRLeave, HRLeaveType, HRCalendarDay, HRLeaveDay, HRLeaveEntitlement


def shift_dict(shift):
    return {"id": shift.id, "name": shift.name, "branch_id": shift.branch_id, "starts": shift.starts,
            "ends": shift.ends, "weekdays": json.loads(shift.weekdays), "break_minutes": shift.break_minutes,
            "grace_minutes": shift.grace_minutes, "overtime_enabled": shift.overtime_enabled, "version": shift.version}


def assigned_shifts(people, on):
    ids = [p.id for p in people]
    rows = (HRShiftAssignment.query.filter(HRShiftAssignment.person_id.in_(ids), HRShiftAssignment.effective_from <= on)
            .order_by(HRShiftAssignment.effective_from.desc(), HRShiftAssignment.id.desc()).all()) if ids else []
    latest = {}
    for row in rows:
        latest.setdefault(row.person_id, row.shift_id)
    shifts = {s.id: shift_dict(s) for s in HRShift.query.filter(HRShift.id.in_(set(latest.values()))).all()} if latest else {}
    return {key: shifts[value] for key, value in latest.items() if value in shifts}


def bounds(shift, work_date):
    start = datetime.combine(work_date, time.fromisoformat(shift["starts"]), BAGHDAD)
    end = datetime.combine(work_date, time.fromisoformat(shift["ends"]), BAGHDAD)
    if end <= start:
        end += timedelta(days=1)
    return start.astimezone(timezone.utc).replace(tzinfo=None), end.astimezone(timezone.utc).replace(tzinfo=None)


def calculate(row):
    shift = json.loads(row.shift)
    shift.pop("legacy_state", None)
    row.shift = json_text(shift)
    row.worked_minutes = row.late_minutes = row.early_minutes = row.overtime_minutes = 0
    if not row.check_in:
        raise ValueError("حدد وقت الحضور قبل احتساب الدوام")
    if row.check_out:
        elapsed = int((row.check_out - row.check_in).total_seconds() // 60)
        if not 0 <= elapsed <= 24 * 60:
            raise ValueError("وقت الانصراف يجب أن يلي الحضور خلال 24 ساعة")
        row.worked_minutes = max(0, elapsed - int(shift.get("break_minutes", 0)))
    if shift.get("starts") and shift.get("ends"):
        start, end = bounds(shift, row.work_date)
        row.late_minutes = max(0, int((row.check_in - start).total_seconds() // 60) - shift["grace_minutes"])
        if row.check_out:
            row.early_minutes = max(0, int((end - row.check_out).total_seconds() // 60))
            row.overtime_minutes = max(0, int((row.check_out - end).total_seconds() // 60)) if shift.get("overtime_enabled") else 0


def attendance_dict(row, state=None):
    def local(value):
        return value.replace(tzinfo=timezone.utc).astimezone(BAGHDAD).strftime("%H:%M") if value else ""
    return {"id": row.id, "date": row.work_date.isoformat(), "check_in": local(row.check_in),
            "check_out": local(row.check_out), "check_in_at": row.check_in.isoformat() + "Z" if row.check_in else None,
            "check_out_at": row.check_out.isoformat() + "Z" if row.check_out else None,
            "worked_minutes": row.worked_minutes, "late_minutes": row.late_minutes,
            "overtime_minutes": row.overtime_minutes, "early_minutes": row.early_minutes,
            "state": state or json.loads(row.shift).get("legacy_state") or ("late" if row.late_minutes else "present"), "version": row.version,
            "shift": json.loads(row.shift) if json.loads(row.shift).get("id") else None}


def attendance_rows(people, on=None):
    on = on or datetime.now(BAGHDAD).date()
    ids = [p.id for p in people]
    if not ids:
        return {}
    shifts = assigned_shifts(people, on)
    calendar = {c.branch_id:c.working for c in HRCalendarDay.query.filter(HRCalendarDay.branch_id.in_([p.branch_id for p in people]), HRCalendarDay.on_date == on).all()}
    records = HRAttendance.query.filter(HRAttendance.person_id.in_(ids), or_(
        HRAttendance.work_date == on,
        (HRAttendance.work_date == on - timedelta(days=1)) & HRAttendance.check_out.is_(None) & HRAttendance.check_in.is_not(None))).order_by(HRAttendance.work_date.desc()).all()
    present = {}
    for row in records:
        present.setdefault(row.person_id, row)
    leaves = {row.person_id for row in HRLeave.query.filter(HRLeave.person_id.in_(ids), HRLeave.status == "approved",
                                                          HRLeave.starts <= on, HRLeave.ends >= on).all()}
    result = {}
    for employee in people:
        row = present.get(employee.id)
        if row and not (not row.check_in and json.loads(row.shift).get("legacy_state") == "leave"):
            result[employee.id] = attendance_dict(row)
            continue
        shift = shifts.get(employee.id)
        state = "leave" if employee.id in leaves else "unscheduled"
        if employee.id not in leaves and calendar.get(employee.branch_id) is False:
            state = "holiday"
        elif employee.id not in leaves and shift and calendar.get(employee.branch_id, on.weekday() in shift["weekdays"]) and employee.status == "active":
            start, _ = bounds(shift, on)
            state = "absent" if datetime.utcnow() > start + timedelta(minutes=shift["grace_minutes"]) else "scheduled"
        result[employee.id] = {"id": None, "date": on.isoformat(), "state": state, "check_in": "", "check_out": "",
                               "worked_minutes": 0, "late_minutes": 0, "overtime_minutes": 0, "early_minutes": 0,
                               "version": 0, "shift": shift}
    return result


def month_calendar(employee, month):
    from .finance import month_bounds
    from .models import HROffboarding, HRContract
    first,last=month_bounds(month)
    exit_row=HROffboarding.query.filter_by(person_id=employee.id).first()
    contracts=HRContract.query.filter(HRContract.person_id==employee.id,HRContract.effective_from<=last).order_by(HRContract.effective_from.desc(),HRContract.id.desc()).all()
    records={r.work_date:r for r in HRAttendance.query.filter(HRAttendance.person_id==employee.id,HRAttendance.work_date>=first,HRAttendance.work_date<=last).all()}
    assignments=HRShiftAssignment.query.filter(HRShiftAssignment.person_id==employee.id,HRShiftAssignment.effective_from<=last).order_by(HRShiftAssignment.effective_from.desc()).all()
    shifts={s.id:shift_dict(s) for s in HRShift.query.filter(HRShift.id.in_([a.shift_id for a in assignments])).all()}
    calendar={c.on_date:c for c in HRCalendarDay.query.filter_by(branch_id=employee.branch_id).filter(HRCalendarDay.on_date>=first,HRCalendarDay.on_date<=last).all()}
    leave_days={d.on_date:d.half_days for d in HRLeaveDay.query.join(HRLeave,HRLeave.id==HRLeaveDay.leave_id).filter(HRLeave.person_id==employee.id,HRLeave.status=="approved",HRLeaveDay.on_date>=first,HRLeaveDay.on_date<=last).all()}
    result=[];now=datetime.utcnow()
    for index in range((last-first).days+1):
        on=first+timedelta(days=index)
        assignment=next((a for a in assignments if a.effective_from<=on),None)
        shift=shifts.get(assignment.shift_id) if assignment else None
        holiday=calendar.get(on)
        contract=next((c for c in contracts if c.effective_from<=on),None)
        contract_end=json.loads(contract.terms).get("contract_end") if contract else employee.contract_end.isoformat() if employee.contract_end else None
        ends_on=exit_row.ends_on if exit_row else day(contract_end) if contract_end else None
        state="unscheduled"
        working=holiday.working if holiday else bool(shift and on.weekday() in shift["weekdays"])
        if on<employee.joined_on or ends_on and on>ends_on:state="unscheduled"
        elif holiday and not working or shift and not working:state="holiday"
        elif leave_days.get(on)==2:state="leave"
        elif shift:
            start,_=bounds(shift,on)
            state="absent" if now>start+timedelta(minutes=shift["grace_minutes"]) else "scheduled"
        record=records.get(on)
        row=attendance_dict(record) if record else {"id":None,"date":on.isoformat(),"state":state,"check_in":"","check_out":"","worked_minutes":0,"version":0,"shift":shift}
        row.update(holiday=holiday.title if holiday else "",leave_days=leave_days.get(on,0)/2)
        result.append(row)
    return result


def save_shift(payload):
    require("hr.shifts.manage")
    starts, ends = text(payload.get("starts"), limit=5), text(payload.get("ends"), limit=5)
    time.fromisoformat(starts)
    time.fromisoformat(ends)
    if len(starts) != 5 or len(ends) != 5 or starts == ends:
        raise ValueError("حدد بداية ونهاية مختلفتين للوردية")
    weekdays = payload.get("weekdays")
    if not isinstance(weekdays, list) or not weekdays or len(weekdays) > 7:
        raise ValueError("حدد أيام العمل")
    weekdays = sorted(set(integer(d, maximum=6) for d in weekdays))
    row = HRShift(branch_id=branch(payload), name=text(payload.get("name"), limit=100, required=True),
                  starts=starts, ends=ends, weekdays=json_text(weekdays),
                  break_minutes=integer(payload.get("break_minutes", 0), maximum=240),
                  grace_minutes=integer(payload.get("grace_minutes", 0), maximum=120),
                  overtime_enabled=payload.get("overtime_enabled") is True)
    db.session.add(row)
    db.session.flush()
    start, end = bounds(shift_dict(row), date.today())
    if row.break_minutes >= int((end - start).total_seconds() // 60):
        raise ValueError("الاستراحة يجب أن تكون أقل من مدة الوردية")
    audit("shift.create", row.id)
    return {"id": row.id}


def assign_shift(payload):
    require("hr.shifts.manage")
    employee = person(payload["person_id"], lock=True)
    version(employee, payload)
    shift = db.session.get(HRShift, integer(payload["shift_id"], minimum=1))
    if not shift or not shift.active or shift.branch_id != employee.branch_id:
        raise ValueError("الوردية لا تتبع فرع الموظف")
    effective = day(payload["effective_from"])
    if effective < datetime.now(BAGHDAD).date():
        raise ValueError("تغيير الوردية يسري اليوم أو بتاريخ مستقبلي")
    from .finance import assert_contract_editable
    assert_contract_editable(employee.id, effective)
    if HRLeave.query.filter(HRLeave.person_id == employee.id, HRLeave.status == "approved", HRLeave.ends >= effective).first():
        raise ValueError("الوردية تؤثر بإجازة معتمدة؛ ألغِ الإجازة وأعد احتسابها بعد التعديل")
    assignment = HRShiftAssignment.query.filter_by(person_id=employee.id, effective_from=effective).first()
    if assignment:
        assignment.shift_id = shift.id
    else:
        db.session.add(HRShiftAssignment(person_id=employee.id, shift_id=shift.id, effective_from=effective))
    audit("shift.assign", employee.id, person_id=employee.id, detail={"shift_id": shift.id, "effective_from": effective.isoformat()})
    return {"id": employee.id, "version": employee.version}


def record_attendance(payload):
    employee = person(payload["person_id"], lock=True)
    if not (can("hr.attendance.record") or can("hr.self") and own(employee)):
        require("hr.attendance.record")
    if employee.status != "active":
        raise ValueError("الموظف غير نشط")
    occurred = timestamp(payload["occurred_at"])
    now = datetime.utcnow()
    if occurred > now + timedelta(minutes=5) or occurred < now - timedelta(days=7):
        raise ValueError("الوقت خارج فترة تسجيل الدوام؛ استخدم تصحيحاً معتمداً")
    local = occurred.replace(tzinfo=timezone.utc).astimezone(BAGHDAD)
    event = payload.get("event")
    work_date = local.date()
    if event == "check_in":
        shift = assigned_shifts([employee], work_date).get(employee.id)
        previous_shift = assigned_shifts([employee], work_date - timedelta(days=1)).get(employee.id)
        if previous_shift:
            _, previous_end = bounds(previous_shift, work_date - timedelta(days=1))
            if previous_shift["ends"] <= previous_shift["starts"] and occurred <= previous_end:
                work_date -= timedelta(days=1)
                shift = previous_shift
        if "shift_version" in payload and integer(payload["shift_version"]) != (shift or {}).get("version", 0):
            from flask import abort
            abort(409, description="تغيّرت الوردية أثناء العمل دون اتصال؛ راجع الحدث")
        if "shift_id" in payload and payload["shift_id"] != (shift or {}).get("id"):
            from flask import abort
            abort(409, description="تغيّرت الوردية المسندة أثناء العمل دون اتصال؛ راجع الحدث")
        existing = HRAttendance.query.filter_by(person_id=employee.id, work_date=work_date).first()
        if existing and existing.check_in:
            raise ValueError("الحضور مسجل لهذا اليوم مسبقاً")
        if HRAttendance.query.filter_by(person_id=employee.id, check_out=None).filter(HRAttendance.check_in.is_not(None)).first():
            raise ValueError("يوجد حضور سابق بدون انصراف؛ يحتاج تصحيحاً")
        if existing:
            row = existing
            row.check_in, row.shift = occurred, json_text(shift or {})
            row.version += 1
        else:
            row = HRAttendance(person_id=employee.id, work_date=work_date, check_in=occurred, shift=json_text(shift or {}))
            db.session.add(row)
    elif event == "check_out":
        query = HRAttendance.query.filter_by(person_id=employee.id, check_out=None).filter(HRAttendance.check_in.is_not(None))
        expected = payload.get("attendance_id")
        if payload.get("check_in_command_id"):
            from .models import HRCommand
            from .common import uuid
            command = db.session.get(HRCommand,uuid(payload["check_in_command_id"]))
            if not command or command.actor_id != actor().id or not command.response:
                from flask import abort
                abort(409,description="حدث الحضور المرتبط لم يُؤكد؛ راجع الطلب الأول")
            receipt = json.loads(command.response)
            if not isinstance(receipt.get("attendance"),dict) or receipt["attendance"].get("check_out"):
                raise ValueError("الأمر المرتبط ليس حدث حضور")
            expected = receipt.get("id")
        if expected:
            query=query.filter(HRAttendance.id == integer(expected,minimum=1))
        row = (query
               .order_by(HRAttendance.work_date.desc()).with_for_update().first())
        if not row:
            raise ValueError("سجل الحضور أولاً أو راجع الانصراف المسجل")
        row.check_out = occurred
        row.version += 1
    else:
        raise ValueError("حدث الدوام غير معروف")
    from .finance import assert_attendance_editable
    assert_attendance_editable(employee.id, row.work_date)
    calculate(row)
    from .legacy import mirror_attendance
    mirror_attendance(row)
    db.session.flush()
    audit(f"attendance.{event}", row.id, person_id=employee.id, happened_at=occurred,
          source="offline" if payload.get("source") == "offline" else "desktop")
    return {"id": row.id, "attendance": attendance_dict(row)}


def correct_attendance(payload):
    require("hr.attendance.approve")
    row = db.session.get(HRAttendance, integer(payload["attendance_id"], minimum=1))
    if not row:
        raise ValueError("سجل الدوام غير موجود")
    person(row.person_id, lock=True)
    version(row, payload)
    reason = text(payload.get("reason"), limit=500, required=True)
    before = attendance_dict(row)
    row.check_in = timestamp(payload["check_in"])
    check_in_day = row.check_in.replace(tzinfo=timezone.utc).astimezone(BAGHDAD).date()
    shift = json.loads(row.shift)
    allowed = {row.work_date}
    if shift.get("starts") and shift.get("ends") and shift["ends"] <= shift["starts"]:
        allowed.add(row.work_date+timedelta(days=1))
    if check_in_day not in allowed:
        raise ValueError("وقت الحضور لا يتبع يوم العمل المسجل")
    row.check_out = timestamp(payload["check_out"]) if payload.get("check_out") else None
    from .finance import assert_attendance_editable
    assert_attendance_editable(row.person_id, row.work_date)
    calculate(row)
    from .legacy import mirror_attendance
    mirror_attendance(row)
    audit("attendance.correct", row.id, person_id=row.person_id, detail={"before": before, "after": attendance_dict(row), "reason": reason})
    return {"id": row.id, "version": row.version}


def request_correction(payload):
    employee=person(payload["person_id"],lock=True)
    if not (can("hr.attendance.record") or can("hr.self") and own(employee)):
        require("hr.attendance.record")
    row=db.session.get(HRAttendance,integer(payload["attendance_id"],minimum=1))
    if not row or row.person_id!=employee.id:
        raise ValueError("اختر سجل دوام الموظف")
    if integer(payload["attendance_version"],minimum=1)!=row.version:
        from flask import abort
        abort(409,description="تغيّر سجل الدوام؛ حدّثه قبل طلب التصحيح")
    from .finance import assert_attendance_editable
    assert_attendance_editable(employee.id,row.work_date)
    from .models import HRCorrectionRequest
    if HRCorrectionRequest.query.filter_by(attendance_id=row.id,status="pending").first():
        raise ValueError("يوجد طلب تصحيح قيد المراجعة لهذا السجل")
    start=timestamp(payload["check_in"])
    end=timestamp(payload["check_out"]) if payload.get("check_out") else None
    if end and (end<start or end-start>timedelta(hours=24)):
        raise ValueError("فترة الدوام غير صحيحة")
    local_day=start.replace(tzinfo=timezone.utc).astimezone(BAGHDAD).date()
    if local_day not in (row.work_date,row.work_date+timedelta(days=1)):
        raise ValueError("وقت الحضور خارج يوم السجل")
    content={"attendance_id":row.id,"version":row.version,"check_in":start.isoformat()+"Z",
             "check_out":end.isoformat()+"Z" if end else "","reason":text(payload.get("reason"),limit=500,required=True)}
    request_=HRCorrectionRequest(person_id=employee.id,attendance_id=row.id,payload=json_text(content),created_by=actor().id)
    db.session.add(request_);db.session.flush()
    audit("attendance.correction_request",request_.id,person_id=employee.id,detail={"attendance_id":row.id})
    return {"id":request_.id}


def decide_correction(payload):
    require("hr.attendance.approve")
    from .models import HRCorrectionRequest
    row=db.session.get(HRCorrectionRequest,integer(payload["correction_id"],minimum=1))
    if not row:
        raise ValueError("طلب التصحيح غير موجود")
    person(row.person_id,lock=True)
    version(row,payload)
    target=payload.get("status")
    if row.status!="pending" or target not in ("approved","rejected"):
        raise ValueError("قرار التصحيح غير متاح")
    reason=text(payload.get("reason"),limit=500,required=True)
    if target=="approved":
        content=json.loads(row.payload)
        content["reason"]=reason+" · طلب #"+str(row.id)
        correct_attendance(content)
    row.status,row.decision,row.decided_by=target,reason,actor().id
    audit("attendance.correction_decide",row.id,person_id=row.person_id,detail={"status":target,"reason":reason})
    return {"id":row.id,"version":row.version}


def request_leave(payload):
    employee = person(payload["person_id"], lock=True)
    if not (can("hr.leave.manage") or can("hr.self") and own(employee)):
        require("hr.leave.manage")
    kind = db.session.get(HRLeaveType, integer(payload["type_id"], minimum=1))
    if not kind or not kind.active:
        raise ValueError("نوع الإجازة غير متاح")
    starts, ends = day(payload["starts"]), day(payload["ends"])
    if ends < starts or (ends - starts).days > 365:
        raise ValueError("حدد فترة إجازة لا تتجاوز سنة")
    half = payload.get("half_day") is True
    if half and starts != ends:
        raise ValueError("نصف يوم يخص تاريخاً واحداً")
    days = [starts + timedelta(days=i) for i in range((ends - starts).days + 1)]
    eligible = sum(1 for d in days if is_work_day(employee, d))
    if not eligible:
        raise ValueError("الفترة لا تحتوي أيام عمل")
    row = HRLeave(person_id=employee.id, type_id=kind.id, starts=starts, ends=ends, half_day=half,
                  half_days=1 if half else eligible * 2, reason=text(payload.get("reason", ""), limit=500), created_by=actor().id)
    db.session.add(row)
    db.session.flush()
    audit("leave.request", row.id, person_id=employee.id)
    return {"id": row.id}


def decide_leave(payload):
    require("hr.leave.approve")
    row = db.session.get(HRLeave, integer(payload["leave_id"], minimum=1))
    if not row:
        raise ValueError("طلب الإجازة غير موجود")
    person(row.person_id, lock=True)
    version(row, payload)
    target = payload.get("status")
    if row.status != "pending" or target not in ("approved", "rejected"):
        raise ValueError("الطلب لا يقبل هذا الإجراء")
    if target == "approved":
        if HRLeave.query.filter(HRLeave.person_id == row.person_id, HRLeave.status == "approved", HRLeave.starts <= row.ends, HRLeave.ends >= row.starts).first():
            raise ValueError("توجد إجازة معتمدة متداخلة")
        kind = db.session.get(HRLeaveType, row.type_id)
        employee = person(row.person_id)
        days = [row.starts+timedelta(days=i) for i in range((row.ends-row.starts).days+1)
                if is_work_day(employee,row.starts+timedelta(days=i))]
        if not days:
            raise ValueError("الفترة لا تحتوي أيام عمل")
        row.half_days = 1 if row.half_day else len(days)*2
        cap=leave_cap(employee.id,kind)
        for year in {d.year for d in days}:
            requested=sum(1 if row.half_day else 2 for d in days if d.year==year)
            if cap is not None and leave_used(employee.id,kind.id,year)+requested > cap:
                raise ValueError("رصيد الإجازة لا يكفي لسنة "+str(year))
        from .finance import assert_attendance_editable
        for i in range((row.ends - row.starts).days + 1):
            assert_attendance_editable(row.person_id, row.starts + timedelta(days=i))
        for on in days:
            db.session.add(HRLeaveDay(leave_id=row.id,on_date=on,half_days=1 if row.half_day else 2,paid=kind.paid))
    row.status = target
    row.approved_by = actor().id
    audit(f"leave.{target}", row.id, person_id=row.person_id)
    return {"id": row.id, "version": row.version}


def leave_cap(person_id,kind):
    entitlement=HRLeaveEntitlement.query.filter_by(person_id=person_id,type_id=kind.id).first()
    return entitlement.yearly_half_days if entitlement else kind.yearly_half_days


def leave_used(person_id,type_id,year):
    return int(db.session.query(db.func.coalesce(db.func.sum(HRLeaveDay.half_days),0)).join(HRLeave,HRLeave.id==HRLeaveDay.leave_id).filter(
        HRLeave.person_id==person_id,HRLeave.type_id==type_id,HRLeave.status=="approved",
        HRLeaveDay.on_date>=date(year,1,1),HRLeaveDay.on_date<=date(year,12,31)).scalar())


def save_leave_entitlement(payload):
    require("hr.settings.manage")
    employee=person(payload["person_id"],lock=True)
    version(employee,payload)
    kind=db.session.get(HRLeaveType,integer(payload["type_id"],minimum=1))
    if not kind or not kind.active:
        raise ValueError("اختر نوع إجازة فعالاً")
    cap=integer(payload["yearly_half_days"],maximum=732)
    year=datetime.now(BAGHDAD).year
    if cap < leave_used(employee.id,kind.id,year):
        raise ValueError("الرصيد الجديد أقل من الإجازات المعتمدة لهذا العام")
    row=HRLeaveEntitlement.query.filter_by(person_id=employee.id,type_id=kind.id).first()
    if row is None:
        row=HRLeaveEntitlement(person_id=employee.id,type_id=kind.id)
        db.session.add(row)
    row.yearly_half_days=cap
    employee.updated_at=datetime.utcnow()
    audit("leave.entitlement",employee.id,person_id=employee.id,detail={"type_id":kind.id,"yearly_half_days":cap})
    return {"id":employee.id,"version":employee.version}


def is_work_day(employee, on):
    calendar = HRCalendarDay.query.filter_by(branch_id=employee.branch_id, on_date=on).first()
    if calendar:
        return calendar.working
    shift = assigned_shifts([employee], on).get(employee.id)
    return not shift or on.weekday() in shift["weekdays"]


def save_calendar(payload):
    require("hr.settings.manage")
    branch_id, on = branch(payload), day(payload["on_date"])
    from .models import HRPayrollRun, HRPerson
    if HRPayrollRun.query.filter_by(branch_id=branch_id, month=on.strftime("%Y-%m"), status="approved").first():
        raise ValueError("اليوم دخل بمسير معتمد؛ لا يمكن تغيير حساب الفترة")
    if HRLeave.query.join(HRPerson, HRPerson.id == HRLeave.person_id).filter(HRPerson.branch_id == branch_id,
        HRLeave.status == "approved", HRLeave.starts <= on, HRLeave.ends >= on).first():
        raise ValueError("اليوم يدخل بإجازة معتمدة؛ ألغِ الإجازة وأعد احتسابها بعد تعديل التقويم")
    row = HRCalendarDay.query.filter_by(branch_id=branch_id, on_date=on).first()
    if row:
        version(row,payload)
    else:
        row = HRCalendarDay(branch_id=branch_id,on_date=on)
        db.session.add(row)
    row.title,row.working=text(payload.get("title"),limit=150,required=True),payload.get("working") is True
    db.session.flush()
    audit("calendar.save",row.id,detail={"date":on.isoformat(),"working":row.working})
    return {"id":row.id,"version":row.version}


def cancel_leave(payload):
    require("hr.leave.approve")
    row = db.session.get(HRLeave,integer(payload["leave_id"],minimum=1))
    if not row:
        raise ValueError("الإجازة غير موجودة")
    person(row.person_id,lock=True)
    version(row,payload)
    if row.status != "approved":
        raise ValueError("يمكن إلغاء إجازة معتمدة فقط")
    from .finance import assert_attendance_editable
    for i in range((row.ends-row.starts).days+1):
        assert_attendance_editable(row.person_id,row.starts+timedelta(days=i))
    reason=text(payload.get("reason"),limit=500,required=True)
    row.status="cancelled"
    audit("leave.cancelled",row.id,person_id=row.person_id,detail={"reason":reason})
    return {"id":row.id,"version":row.version}
