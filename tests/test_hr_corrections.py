from datetime import datetime, timezone
from flask import g
from extensions_tenant import init_tenant_db
from tests.test_hr_workspace import ctx, command, create_person, _client, _grant, TENANT, JSON


def test_correction_request_requires_review_and_frozen_base_version(ctx):
    client=_client(ctx)
    profile=create_person(client,ctx)
    now=datetime.now(timezone.utc).isoformat()
    attendance=command(client,"attendance.record",{"person_id":profile,"event":"check_in","occurred_at":now})
    assert attendance.status_code==200,attendance.get_json()
    payload={"person_id":profile,"attendance_id":attendance.get_json()["id"],"attendance_version":1,"check_in":now,"check_out":"","reason":"نسيان تسجيل الوقت الصحيح"}
    requested=command(client,"attendance.correction_request",payload)
    assert requested.status_code==200,requested.get_json()
    correction=requested.get_json()["id"]
    assert command(client,"attendance.correction_request",payload).status_code==400
    from modules.hr.models import HRAttendance
    from extensions import db
    with ctx["app"].app_context():
        g.tenant=TENANT;init_tenant_db(TENANT)
        assert db.session.get(HRAttendance,payload["attendance_id"]).version==1
    assert any(r["key"]==f"correction:{correction}" for r in client.get("/hr/api/notifications",headers=JSON).get_json()["items"])
    _grant(ctx,"hr.view","hr.attendance.record")
    clerk=_client(ctx,"clerk_id","cashier")
    decision={"correction_id":correction,"version":1,"status":"approved","reason":"تم التحقق"}
    assert command(clerk,"attendance.correction_decide",decision).status_code==403
    approved=command(client,"attendance.correction_decide",decision)
    assert approved.status_code==200,approved.get_json()
    assert command(client,"attendance.correction_decide",decision).status_code==409
    with ctx["app"].app_context():
        g.tenant=TENANT;init_tenant_db(TENANT)
        assert db.session.get(HRAttendance,payload["attendance_id"]).version==2
    payload["attendance_version"]=2
    second=command(client,"attendance.correction_request",payload).get_json()["id"]
    corrected=command(client,"attendance.correct",{"attendance_id":payload["attendance_id"],"version":2,"check_in":now,"check_out":"","reason":"تصحيح مباشر موثق"})
    assert corrected.status_code==200,corrected.get_json()
    assert command(client,"attendance.correction_decide",{**decision,"correction_id":second}).status_code==409


def test_employee_entitlement_is_versioned_and_updates_coherent_revision(ctx):
    client=_client(ctx)
    profile=create_person(client,ctx)
    kind=command(client,"leave_type.create",{"name":"استحقاق شخصي اختبار","paid":True,"yearly_half_days":40}).get_json()["id"]
    before=client.get("/hr/api/offline/revision",headers=JSON).get_json()["revision"]
    payload={"person_id":profile,"version":1,"type_id":kind,"yearly_half_days":50}
    saved=command(client,"leave.entitlement",payload)
    assert saved.status_code==200,saved.get_json()
    assert command(client,"leave.entitlement",payload).status_code==409
    after=client.get("/hr/api/offline/revision",headers=JSON).get_json()["revision"]
    assert before!=after
    details=client.get(f"/hr/api/people/{profile}",headers=JSON).get_json()
    assert next(r for r in details["leave_balances"] if r["id"]==kind)["remaining"]==25


def test_month_calendar_uses_dated_shift_holidays_and_frozen_leave(ctx):
    client=_client(ctx)
    profile=create_person(client,ctx)
    branch=ctx["ids"]["branch_id"]
    shift=command(client,"shift.create",{"branch_id":branch,"name":"نهاري تقويم","starts":"08:00","ends":"16:00","weekdays":[0,1,2,3,4],"break_minutes":0,"grace_minutes":0}).get_json()["id"]
    assert command(client,"shift.assign",{"person_id":profile,"version":1,"shift_id":shift,"effective_from":"2026-11-01"}).status_code==200
    assert command(client,"calendar.save",{"branch_id":branch,"on_date":"2026-11-09","working":False,"title":"عطلة تقويم اختبار"}).status_code==200
    kind=command(client,"leave_type.create",{"name":"تقويم مدفوعة","paid":True,"yearly_half_days":10}).get_json()["id"]
    leave=command(client,"leave.request",{"person_id":profile,"type_id":kind,"starts":"2026-11-10","ends":"2026-11-10","reason":"اختبار"}).get_json()["id"]
    assert command(client,"leave.decide",{"leave_id":leave,"version":1,"status":"approved","reason":"موافق"}).status_code==200
    response=client.get(f"/hr/api/calendar?person_id={profile}&month=2026-11",headers=JSON)
    assert response.status_code==200,response.get_json()
    days={d["date"]:d for d in response.get_json()["rows"]}
    assert len(days)==30
    assert days["2026-11-09"]["state"]=="holiday"
    assert days["2026-11-10"]["state"]=="leave" and days["2026-11-10"]["leave_days"]==1
    assert days["2026-11-11"]["shift"]["name"]=="نهاري تقويم"
    current=client.get(f"/hr/api/people/{profile}",headers=JSON).get_json()["person"]
    assert command(client,"employee.update",{"person_id":profile,"version":current["version"],"contract_end":"2026-11-15","effective_from":"2026-11-01"}).status_code==200
    ended=client.get(f"/hr/api/calendar?person_id={profile}&month=2026-11",headers=JSON).get_json()["rows"]
    assert next(d for d in ended if d["date"]=="2026-11-16")["state"]=="unscheduled"
    _grant(ctx,"hr.view")
    assert _client(ctx,"clerk_id","cashier").get(f"/hr/api/calendar?person_id={profile}&month=2026-11",headers=JSON).status_code==403


def test_bulk_employee_state_is_atomic_on_version_conflict(ctx):
    client=_client(ctx)
    first,second=create_person(client,ctx),create_person(client,ctx)
    assert command(client,"employee.update",{"person_id":second,"version":1,"phone":"0770"}).status_code==200
    payload={"mode":"state","people":[{"person_id":first,"version":1},{"person_id":second,"version":1}],"status":"suspended","reason":"مراجعة جماعية"}
    assert command(client,"employee.bulk",payload).status_code==409
    before=client.get(f"/hr/api/people/{first}",headers=JSON).get_json()["person"]
    assert before["status"]=="active" and before["version"]==1
    payload["people"][1]["version"]=2
    saved=command(client,"employee.bulk",payload)
    assert saved.status_code==200,saved.get_json()
    assert saved.get_json()["count"]==2
    assert client.get(f"/hr/api/people/{first}",headers=JSON).get_json()["person"]["status"]=="suspended"
