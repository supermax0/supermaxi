from tests.test_hr_workspace import ctx, command, create_person, _client, _grant, TENANT, JSON
from flask import g
from extensions import db
from extensions_tenant import init_tenant_db


def test_hr_scopes_filter_manager_then_department_and_invalidate_offline_revision(ctx, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("modules.desktop_api.routes.find_core_tenant", lambda slug: SimpleNamespace(slug=TENANT, name="HR test", is_active=True))
    admin = _client(ctx)
    person_id = create_person(admin, ctx)
    hidden = create_person(admin, ctx)
    from modules.hr.models import HRPerson
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        manager = HRPerson.query.filter_by(employee_id=ctx["ids"]["clerk_id"]).one()
        db.session.get(HRPerson, person_id).manager_id = manager.id
        db.session.commit()
        manager_id = manager.id
    _grant(ctx, "hr.view", "hr.payroll.view")
    clerk = _client(ctx, "clerk_id", "cashier")
    initial_revision = clerk.get("/api/v1/desktop/auth/session", headers=JSON).get_json()["session"]["hr_scope_revision"]
    response = command(admin, "scope.update", {"employee_id": ctx["ids"]["clerk_id"], "mode": "manager"})
    assert response.status_code == 200, response.get_json()
    directory = clerk.get("/hr/api/page", headers=JSON).get_json()
    assert {p["id"] for p in directory["rows"]} == {person_id, manager_id}
    assert clerk.get(f"/hr/api/people/{hidden}", headers=JSON).status_code == 404
    assert command(clerk, "employee.update", {"person_id": hidden, "version": 1, "name": "forbidden"}).status_code == 403
    new_revision = clerk.get("/api/v1/desktop/auth/session", headers=JSON).get_json()["session"]["hr_scope_revision"]
    assert new_revision != initial_revision
    department = command(admin, "department.create", {"branch_id": ctx["ids"]["branch_id"], "name": "اختبار النطاق"}).get_json()["id"]
    assert command(admin, "employee.update", {"person_id": person_id, "version": 1, "department_id": department}).status_code == 200
    assert command(admin, "scope.update", {"employee_id": ctx["ids"]["clerk_id"], "mode": "department", "department_id": department, "version": 1}).status_code == 200
    assert {p["id"] for p in clerk.get("/hr/api/page", headers=JSON).get_json()["rows"]} == {person_id}


def test_hr_same_date_contract_revision_keeps_history_and_future_salary_starts_on_time(ctx):
    admin = _client(ctx)
    person_id = create_person(admin, ctx)
    edited = command(admin, "employee.update", {"person_id": person_id, "version": 1, "salary": 675000, "effective_from": "2026-01-01"})
    assert edited.status_code == 200, edited.get_json()
    future = command(admin, "employee.update", {"person_id": person_id, "version": 2, "salary": 900000, "effective_from": "2099-01-01"})
    assert future.status_code == 200, future.get_json()
    details = admin.get(f"/hr/api/people/{person_id}", headers=JSON).get_json()
    assert details["person"]["salary"] == 675000 and len(details["contracts"]) == 2
    from modules.hr.models import HRRecord
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        record = HRRecord.query.filter_by(person_id=person_id, kind="contract_revision").one()
        assert '650000' in record.payload
