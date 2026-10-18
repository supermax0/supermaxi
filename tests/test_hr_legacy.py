from datetime import date, datetime, time, timedelta
from flask import g
from extensions import db
from extensions_tenant import init_tenant_db
from tests.test_hr_workspace import ctx, _client, JSON, TENANT, command


def test_hr_imports_existing_overnight_attendance_leaves_and_document_metadata(ctx):
    from models.hr import HRAttendance, HRLeaveRequest, HREmployeeDocument
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        employee_id = ctx["ids"]["clerk_id"]
        attendance = HRAttendance(employee_id=employee_id, attendance_date=date(2026,7,20),
            check_in=time(22), check_out=time(6), status="present", late_minutes=5, overtime_minutes=30)
        leave = HRLeaveRequest(employee_id=employee_id, leave_type="unpaid", start_date=date(2026,7,21),
            end_date=date(2026,7,22), days_count=2, status="approved")
        document = HREmployeeDocument(employee_id=employee_id, title="عقد سابق", file_url="https://private.invalid/contract.pdf")
        db.session.add_all([attendance,leave,document])
        db.session.commit()
    client = _client(ctx)
    response = client.get("/hr/api/page", headers=JSON)
    assert response.status_code == 200, response.get_json()
    from modules.hr.models import HRPerson, HRWorkRecord, HRLeave, HRRecord
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        person = HRPerson.query.filter_by(employee_id=employee_id).one()
        row = HRWorkRecord.query.filter_by(person_id=person.id, work_date=date(2026,7,20)).one()
        assert row.check_in == datetime(2026,7,20,19) and row.check_out == datetime(2026,7,21,3)
        assert row.worked_minutes == 480 and row.overtime_minutes == 30
        saved_id, profile_id = row.id, person.id
        assert HRLeave.query.filter_by(person_id=person.id, status="approved").one().half_days == 4
        assert "private.invalid" not in HRRecord.query.filter_by(person_id=person.id, kind="legacy_document").one().payload
    corrected = command(client,"attendance.correct",{"attendance_id":saved_id,"version":1,
        "check_in":"2026-07-20T19:15:00Z","check_out":"2026-07-21T03:00:00Z","reason":"تصحيح السجل السابق"})
    assert corrected.status_code == 200, corrected.get_json()
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        old = HRAttendance.query.filter_by(employee_id=employee_id, attendance_date=date(2026,7,20)).one()
        assert old.check_in == time(22,15) and old.check_out == time(6)
        assert HRWorkRecord.query.filter_by(person_id=profile_id, work_date=date(2026,7,20)).count() == 1


def test_hr_photo_is_validated_and_returned_as_small_scoped_thumbnail(ctx):
    import base64
    from io import BytesIO
    from PIL import Image
    from tests.test_hr_workspace import create_person
    client = _client(ctx)
    person_id = create_person(client,ctx)
    image = BytesIO()
    Image.new("RGB",(800,600),"red").save(image,format="PNG")
    payload={"person_id":person_id,"kind":"photo","title":"صورة الموظف","filename":"photo.png","mime":"image/png","content":base64.b64encode(image.getvalue()).decode()}
    response=command(client,"document.create",payload)
    assert response.status_code == 200,response.get_json()
    detail=client.get(f"/hr/api/people/{person_id}",headers=JSON).get_json()
    thumbnail=detail["person"]["photo_data"]
    assert thumbnail.startswith("data:image/jpeg;base64,")
    with Image.open(BytesIO(base64.b64decode(thumbnail.split(",")[1]))) as small:
        assert small.size == (160,120)
    assert command(client,"document.create",{**payload,"content":base64.b64encode(b"\x89PNG\r\n\x1a\ninvalid").decode()}).status_code == 400
