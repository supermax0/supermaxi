from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from tests.test_hr_workspace import ctx, command, _client, TENANT, JSON


def _form(client, ctx):
    result = command(client, "recruitment.form", {"branch_id": ctx["ids"]["branch_id"], "title": "موظف مبيعات",
        "fields": [{"key": "name", "type": "short_text", "label": "الاسم الكامل", "required": True},
                   {"key": "email", "type": "email", "label": "البريد الإلكتروني", "required": True}]})
    assert result.status_code == 200, result.get_json()
    return result.get_json()["id"]


def _link(client, form_id, **extra):
    result = command(client, "recruitment.link", {"form_id": form_id, "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "max_submissions": 10, **extra})
    assert result.status_code == 200, result.get_json()
    return result.get_json()


def _company(monkeypatch):
    from flask import g
    def lookup(tenant):
        assert g.tenant is None
        return SimpleNamespace(name="شركة اختبار", is_subscription_valid=lambda: True) if tenant == TENANT else None
    monkeypatch.setattr("modules.hr.recruitment.lookup_company", lookup)


def test_hr_public_application_is_private_versioned_and_idempotent_with_quota(ctx, monkeypatch):
    _company(monkeypatch)
    admin = _client(ctx)
    form_id = _form(admin, ctx)
    link = _link(admin, form_id, pin="4321", private=True, max_submissions=1)
    public = ctx["app"].test_client()
    page = public.get(link["url"])
    assert page.status_code == 200 and 'id="unlock"' in page.get_data(as_text=True)
    assert "الاسم الكامل" not in page.get_data(as_text=True)
    payload = {"id": str(uuid4()), "pin": "wrong", "answers": {"name": "متقدم اختبار", "email": "candidate@example.com"}}
    assert public.post(link["url"], json=payload).status_code == 403
    assert public.post(link["url"], json={"action": "unlock", "pin": "4321"}).status_code == 200
    assert command(admin, "recruitment.form", {"form_id": form_id, "version": 1, "title": "نسخة جديدة", "fields": [
        {"key": "new_required", "type": "short_text", "label": "حقل جديد", "required": True}]}).status_code == 200
    payload["pin"] = "4321"
    accepted = public.post(link["url"], json=payload)
    assert accepted.status_code == 200, accepted.get_json()
    assert public.post(link["url"], json=payload).get_json() == accepted.get_json()
    assert public.post(link["url"], json={**payload, "id": str(uuid4())}).status_code == 410
    assert public.get("/hr/api/recruitment", headers=JSON, environ_overrides={"REMOTE_ADDR": "203.0.113.10"}).status_code in (401, 302)
    staff = admin.get("/hr/api/recruitment", headers=JSON).get_json()
    assert staff["rows"][0]["answers"]["name"] == "متقدم اختبار" and staff["rows"][0]["person_id"] is None
    application_id = staff["rows"][0]["id"]
    employee = {"name": "متقدم اختبار", "branch_id": ctx["ids"]["branch_id"], "joined_on": "2026-10-10", "salary": 500000}
    assert command(admin, "recruitment.convert", {"application_id": application_id, "version": 1, "employee": employee}).status_code == 400
    assert command(admin, "recruitment.decide", {"application_id": application_id, "version": 1, "status": "accepted", "note": "مقابلة ناجحة"}).status_code == 200
    converted = command(admin, "recruitment.convert", {"application_id": application_id, "version": 2, "employee": employee})
    assert converted.status_code == 200, converted.get_json()
    profile = admin.get(f"/hr/api/people/{converted.get_json()['id']}", headers=JSON).get_json()
    assert profile["person"]["employee_id"] is None and profile["person"]["name"] == employee["name"]
    assert command(admin, "recruitment.convert", {"application_id": application_id, "version": 3, "employee": employee}).status_code == 400


def test_hr_recruitment_unknown_tenant_invalid_fields_and_rate_limit(ctx, monkeypatch):
    _company(monkeypatch)
    admin = _client(ctx)
    invalid = command(admin, "recruitment.form", {"branch_id": ctx["ids"]["branch_id"], "title": "Invalid", "fields": [
        {"key": "duplicate", "type": "short_text", "label": "One"}, {"key": "duplicate", "type": "short_text", "label": "Two"}]})
    assert invalid.status_code == 400
    link = _link(admin, _form(admin, ctx), pin="9999")
    public = ctx["app"].test_client()
    assert public.get(link["url"].replace(TENANT, "unknown-tenant")).status_code == 404
    for _ in range(10):
        assert public.post(link["url"], json={"action": "unlock", "pin": "bad"}).status_code == 403
    assert public.post(link["url"], json={"action": "unlock", "pin": "9999"}).status_code == 429
    assert command(admin, "recruitment.link_state", {"link_id": link["id"], "version": 1, "active": False}).status_code == 200
    assert public.get(link["url"]).status_code == 404
