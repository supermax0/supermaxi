from datetime import date,datetime
from flask import g
from extensions import db
from extensions_tenant import init_tenant_db
from tests.test_hr_workspace import ctx,command,create_person,_client,TENANT,JSON


def test_cross_year_leave_freezes_workdays_and_calendar_cancel_restores_balance(ctx):
    client=_client(ctx)
    profile=create_person(client,ctx)
    branch=ctx["ids"]["branch_id"]
    kind=command(client,"leave_type.create",{"name":"سنوية اختبار","paid":True,"yearly_half_days":2}).get_json()["id"]
    holiday=command(client,"calendar.save",{"branch_id":branch,"on_date":"2027-01-01","title":"عطلة","working":False})
    assert holiday.status_code==200,holiday.get_json()
    request=command(client,"leave.request",{"person_id":profile,"type_id":kind,"starts":"2026-12-31","ends":"2027-01-02"})
    assert request.status_code==200,request.get_json()
    leave=request.get_json()["id"]
    assert command(client,"leave.decide",{"leave_id":leave,"version":1,"status":"approved"}).status_code==200
    revision=client.get("/hr/api/offline/revision",headers=JSON)
    assert revision.status_code==200,revision.get_json()
    from modules.hr.models import HRLeaveDay,HRLeave
    with ctx["app"].app_context():
        g.tenant=TENANT;init_tenant_db(TENANT)
        assert [(r.on_date,r.half_days) for r in HRLeaveDay.query.filter_by(leave_id=leave).order_by(HRLeaveDay.on_date).all()]==[(date(2026,12,31),2),(date(2027,1,2),2)]
        assert db.session.get(HRLeave,leave).half_days==4
    assert command(client,"calendar.save",{"branch_id":branch,"on_date":"2027-01-01","version":1,"title":"عمل","working":True}).status_code==400
    assert command(client,"leave.cancel",{"leave_id":leave,"version":2,"reason":"تعديل الموعد"}).status_code==200
    assert command(client,"calendar.save",{"branch_id":branch,"on_date":"2027-01-01","version":1,"title":"عمل","working":True}).status_code==200
    assert client.get("/hr/api/offline/revision",headers=JSON).get_json()["revision"]!=revision.get_json()["revision"]


def test_paid_daily_and_hourly_leave_credits_work_hours_without_duplicate_wages(ctx):
    client=_client(ctx)
    daily=create_person(client,ctx,salary=50000,salary_type="daily")
    hourly=create_person(client,ctx,salary=10000,salary_type="hourly")
    shift=command(client,"shift.create",{"branch_id":ctx["ids"]["branch_id"],"name":"عمل","starts":"08:00","ends":"16:00","weekdays":list(range(7)),"break_minutes":30,"grace_minutes":0,"overtime_enabled":False}).get_json()["id"]
    kind=command(client,"leave_type.create",{"name":"مدفوعة","paid":True,"yearly_half_days":40}).get_json()["id"]
    from modules.hr.models import HRShiftAssignment,HRLeave,HRWorkRecord,HRPerson
    from modules.hr.finance import calculate_person
    with ctx["app"].app_context():
        g.tenant=TENANT;init_tenant_db(TENANT)
        db.session.add(HRShiftAssignment(person_id=hourly,shift_id=shift,effective_from=date(2026,1,1)))
        db.session.commit()
    for profile in (daily,hourly):
        request=command(client,"leave.request",{"person_id":profile,"type_id":kind,"starts":"2026-09-07","ends":"2026-09-07","half_day":True})
        assert request.status_code==200,request.get_json()
        assert command(client,"leave.decide",{"leave_id":request.get_json()["id"],"version":1,"status":"approved"}).status_code==200
    with ctx["app"].app_context():
        g.tenant=TENANT;init_tenant_db(TENANT)
        for profile in (daily,hourly):
            db.session.add(HRWorkRecord(person_id=profile,work_date=date(2026,9,7),check_in=datetime(2026,9,7,5),check_out=datetime(2026,9,7,9),worked_minutes=225,shift="{}"))
        db.session.commit()
        assert calculate_person(db.session.get(HRPerson,daily),"2026-09")["gross"]==50000
        assert calculate_person(db.session.get(HRPerson,hourly),"2026-09")["gross"]==75000
