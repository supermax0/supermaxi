"""Regression coverage for multi-specialty clinics and versioned visit forms."""
from datetime import date

import pytest
from flask import Flask

from extensions import db


@pytest.fixture()
def specialty_db():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        SECRET_KEY="specialty-test",
    )
    db.init_app(app)
    import models  # noqa: F401
    from models.delivery_agent import DeliveryAgent  # noqa: F401
    from modules.clinics.models import CLINIC_MODELS  # noqa: F401

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_seed_doctor_multi_specialty_and_visit_template_snapshot(specialty_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicAppointment, ClinicVisit
    from modules.clinics.service_specialties import seed_default_specialties

    with specialty_db.app_context():
        specialties = seed_default_specialties(1)
        internal = next(row for row in specialties if row["code"] == "internal_medicine")
        endocrine = next(row for row in specialties if row["code"] == "endocrinology")
        doctor = service.create_doctor(1, {
            "full_name": "د. أحمد",
            "primary_specialty_id": internal["id"],
            "specialty_ids": [internal["id"], endocrine["id"]],
        })
        patient = service.create_patient(1, {"full_name": "مريض مركزي"})
        appointment = service.create_appointment(1, {
            "patient_id": patient["id"], "doctor_id": doctor["id"],
            "specialty_id": internal["id"], "appointment_date": date.today().isoformat(),
            "start_time": "10:00",
        })
        visit = service.start_visit_from_appointment(1, appointment["id"])

        assert doctor["primary_specialty_id"] == internal["id"]
        assert set(doctor["specialty_ids"]) == {internal["id"], endocrine["id"]}
        assert ClinicAppointment.query.get(appointment["id"]).specialty_id == internal["id"]
        stored_visit = ClinicVisit.query.get(visit["id"])
        assert stored_visit.specialty_id == internal["id"]
        assert stored_visit.visit_template_id == internal["default_visit_template_id"]


def test_template_values_are_tenant_scoped_and_completed_visit_is_immutable(specialty_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicVisitTemplateField
    from modules.clinics.service_specialties import save_visit_values, seed_default_specialties

    with specialty_db.app_context():
        specialty = next(row for row in seed_default_specialties(1) if row["code"] == "internal_medicine")
        doctor = service.create_doctor(1, {"full_name": "د. باطنية", "primary_specialty_id": specialty["id"], "specialty_ids": [specialty["id"]]})
        patient = service.create_patient(1, {"full_name": "أحمد علي"})
        visit = service.create_walkin_visit(1, {"patient_id": patient["id"], "doctor_id": doctor["id"], "specialty_id": specialty["id"]})
        field = ClinicVisitTemplateField.query.filter_by(tenant_id=1, template_id=visit["visit_template_id"]).first()
        saved = save_visit_values(1, visit["id"], {"values": {str(field.id): "قيمة سريرية"}})
        assert saved["values"][str(field.id)] == "قيمة سريرية"
        with pytest.raises(ValueError, match="الزيارة غير موجودة"):
            save_visit_values(2, visit["id"], {"values": {str(field.id): "تسريب"}})
        service.complete_visit(1, visit["id"], auto_invoice=False)
        with pytest.raises(ValueError, match="بعد إكمال"):
            save_visit_values(1, visit["id"], {"values": {str(field.id): "تعديل"}})
        with pytest.raises(ValueError, match="لا يمكن تغيير"):
            service.update_visit(1, visit["id"], {"specialty_id": specialty["id"]})


def test_new_template_version_does_not_change_existing_visit(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_specialties import create_template, publish_template, seed_default_specialties

    with specialty_db.app_context():
        specialty = next(row for row in seed_default_specialties(1) if row["code"] == "internal_medicine")
        doctor = service.create_doctor(1, {"full_name": "د. نسخة", "primary_specialty_id": specialty["id"], "specialty_ids": [specialty["id"]]})
        patient = service.create_patient(1, {"full_name": "مريض نسخة"})
        old_visit = service.create_walkin_visit(1, {"patient_id": patient["id"], "doctor_id": doctor["id"]})
        old_template_id = old_visit["visit_template_id"]
        new_template = create_template(1, specialty["id"], {"name": "باطنية مطور", "sections": [{"title_ar": "قسم", "fields": [{"key": "new_field", "label_ar": "حقل جديد", "field_type": "text"}]}]})
        publish_template(1, new_template["id"])
        new_visit = service.create_walkin_visit(1, {"patient_id": patient["id"], "doctor_id": doctor["id"]})
        assert old_template_id != new_visit["visit_template_id"]
        assert service.get_visit_detail(1, old_visit["id"])["template"]["id"] == old_template_id


def test_visit_identity_updates_validate_before_mutating(specialty_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicVisit, ClinicVisitTemplateField
    from modules.clinics.service_specialties import seed_default_specialties, save_visit_values

    specs = seed_default_specialties(1)
    internal = next(s for s in specs if s["code"] == "internal_medicine")
    dental = next(s for s in specs if s["code"] == "dentistry")
    doctor = service.create_doctor(1, {"full_name": "أول", "primary_specialty_id": internal["id"], "specialty_ids": [internal["id"], dental["id"]]})
    other = service.create_doctor(1, {"full_name": "ثان", "primary_specialty_id": dental["id"], "specialty_ids": [dental["id"]]})
    foreign = service.create_doctor(2, {"full_name": "خارج المنشأة"})
    patient = service.create_patient(1, {"full_name": "مريض"})
    visit = service.create_walkin_visit(1, {"patient_id": patient["id"], "doctor_id": doctor["id"]})
    row = db.session.get(ClinicVisit, visit["id"])
    original = (row.doctor_id, row.specialty_id, row.visit_template_id, row.clinical_notes)
    for payload in ({"doctor_id": other["id"]}, {"doctor_id": foreign["id"]}, {"visit_template_id": 999}):
        with pytest.raises(ValueError):
            service.update_visit(1, row.id, {**payload, "clinical_notes": "لا تحفظ"})
        assert (row.doctor_id, row.specialty_id, row.visit_template_id, row.clinical_notes) == original
    field = ClinicVisitTemplateField.query.filter_by(template_id=row.visit_template_id).first()
    save_visit_values(1, row.id, {"values": {str(field.id): "قيمة محفوظة"}})
    with pytest.raises(ValueError, match="بعد تسجيل"):
        service.update_visit(1, row.id, {"specialty_id": dental["id"]})
    assert (row.doctor_id, row.specialty_id, row.visit_template_id, row.clinical_notes) == original
    service.update_visit(1, row.id, {"doctor_id": doctor["id"]})
    assert row.visit_template_id == original[2]


def test_started_appointment_keeps_original_identity(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_specialties import seed_default_specialties

    spec = seed_default_specialties(1)[0]
    doctors = [service.create_doctor(1, {"full_name": name, "primary_specialty_id": spec["id"], "specialty_ids": [spec["id"]]}) for name in ("أول", "ثان")]
    patient = service.create_patient(1, {"full_name": "مريض"})
    appt = service.create_appointment(1, {"patient_id": patient["id"], "doctor_id": doctors[0]["id"], "appointment_date": date.today().isoformat(), "start_time": "10:00"})
    service.patch_appointment(1, appt["id"], {"doctor_id": doctors[1]["id"]})
    visit = service.start_visit_from_appointment(1, appt["id"])
    with pytest.raises(ValueError, match="بعد بدء"):
        service.patch_appointment(1, appt["id"], {"doctor_id": doctors[0]["id"], "notes": "لا تحفظ"})
    assert service.get_appointment(1, appt["id"])["doctor_id"] == visit["doctor_id"]


def test_service_links_filter_and_reject_cross_tenant(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_specialties import seed_default_specialties
    specs = seed_default_specialties(1)
    a, b = specs[:2]
    doctor = service.create_doctor(1, {"full_name": "طبيب", "primary_specialty_id": a["id"], "specialty_ids": [a["id"], b["id"]]})
    common = service.create_service(1, {"name": "عامة"})
    private = service.create_service(1, {"name": "خاصة", "specialty_ids": [a["id"]], "doctor_ids": [doctor["id"]]})
    assert {s["id"] for s in service.list_services(1, specialty_id=b["id"], doctor_id=doctor["id"])} == {common["id"]}
    with pytest.raises(ValueError):
        service.assert_service_selection(1, private["id"], doctor["id"], b["id"])
    with pytest.raises(ValueError):
        service.update_service(1, private["id"], {"name": "لا تحفظ", "specialty_ids": [999999]})
    assert next(s for s in service.list_services(1) if s["id"] == private["id"])["name"] == "خاصة"
    with pytest.raises(ValueError):
        service.create_service(2, {"name": "تسريب", "doctor_ids": [doctor["id"]]})


def test_doctor_guard_scopes_lists_and_blocks_foreign_writes(specialty_db, monkeypatch):
    from types import SimpleNamespace
    from modules.clinics import service, guards
    from modules.clinics.models import ClinicDoctor, ClinicVisit
    doctors = [service.create_doctor(1, {"full_name": name}) for name in ("أول", "ثان")]
    patient = service.create_patient(1, {"full_name": "مشترك"})
    visits = [service.create_walkin_visit(1, {"patient_id": patient["id"], "doctor_id": d["id"]}) for d in doctors]
    db.session.commit()
    employee = SimpleNamespace(id=10, role="doctor", is_active=True, has_permission=lambda key: key == "clinics_clinical")
    monkeypatch.setattr(guards, "current_employee", lambda: employee)
    monkeypatch.setattr(guards, "current_tenant_id", lambda: 1)
    monkeypatch.setattr(guards, "is_clinics_tenant", lambda: True)
    monkeypatch.setattr(guards, "get_current_clinic_doctor", lambda: db.session.get(ClinicDoctor, doctors[0]["id"]))

    @guards.require_clinics("clinics_clinical", json_mode=True)
    def listing():
        return [v.id for v in ClinicVisit.query.filter_by(tenant_id=1).all()]

    @guards.require_clinics("clinics_clinical", json_mode=True)
    def mutation(visit_id):
        return service.update_visit(1, visit_id, {"clinical_notes": "ممنوع"})

    with specialty_db.test_request_context('/clinics/api/visits'):
        assert listing() == [visits[0]["id"]]
    with specialty_db.test_request_context('/clinics/api/visits/2', method='PATCH', json={}):
        assert mutation(visit_id=visits[1]["id"])[1] == 403


def test_table_visibility_and_attachment_validation(specialty_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicVisitTemplateField, ClinicAttachment
    from modules.clinics.service_specialties import seed_default_specialties, create_template, publish_template, save_visit_values
    spec = seed_default_specialties(1)[0]
    template = create_template(1, spec["id"], {"name": "شرطي", "sections": [{"title_ar": "تفاصيل", "fields": [
        {"key": "flag", "label_ar": "إظهار", "field_type": "boolean"},
        {"key": "details", "label_ar": "الجدول", "field_type": "table", "options": ["الفحص", "النتيجة"], "required": True,
         "visibility_rules": {"field_key": "flag", "operator": "eq", "value": True}},
        {"key": "image", "label_ar": "صورة", "field_type": "image"}]}]})
    publish_template(1, template["id"])
    doctor = service.create_doctor(1, {"full_name": "طبيب", "primary_specialty_id": spec["id"], "specialty_ids": [spec["id"]]})
    patient = service.create_patient(1, {"full_name": "مريض"})
    visit = service.create_walkin_visit(1, {"patient_id": patient["id"], "doctor_id": doctor["id"]})
    fields = {f.key: str(f.id) for f in ClinicVisitTemplateField.query.filter_by(template_id=template["id"]).all()}
    save_visit_values(1, visit["id"], {"values": {fields["flag"]: True}})
    with pytest.raises(ValueError, match="الحقل مطلوب"):
        service.complete_visit(1, visit["id"], auto_invoice=False)
    with pytest.raises(ValueError, match="الجدول"):
        save_visit_values(1, visit["id"], {"values": {fields["details"]: [{"غير مسموح": "قيمة"}]}})
    foreign = ClinicAttachment(tenant_id=2, patient_id=patient["id"], file_name="image.png", stored_name="image.png", mime_type="image/png", size_bytes=1)
    db.session.add(foreign); db.session.flush()
    with pytest.raises(ValueError, match="المرفق"):
        save_visit_values(1, visit["id"], {"values": {fields["image"]: foreign.id}})
    save_visit_values(1, visit["id"], {"values": {fields["flag"]: False}})
    service.complete_visit(1, visit["id"], auto_invoice=False)


def test_report_specialty_totals_match_series(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_specialties import seed_default_specialties
    from modules.clinics.service_reports import reports_hub
    specs = seed_default_specialties(1)[:2]
    patient = service.create_patient(1, {"full_name": "مريض مشترك"})
    for index, spec in enumerate(specs):
        doctor = service.create_doctor(1, {"full_name": str(index), "primary_specialty_id": spec["id"], "specialty_ids": [spec["id"]]})
        svc = service.create_service(1, {"name": str(index), "price": (index+1)*10000})
        visit = service.create_walkin_visit(1, {"patient_id": patient["id"], "doctor_id": doctor["id"], "service_id": svc["id"]})
        service.complete_visit(1, visit["id"])
    report = reports_hub(1, {"specialty_id": specs[0]["id"], "date_from": date.today().isoformat(), "date_to": date.today().isoformat()})
    assert report["kpis"]["completed_visits"] == 1
    assert sum(r["visits"] for r in report["series"]["by_day"]) == 1
    assert sum(r["revenue"] for r in report["series"]["by_doctor"]) == report["kpis"]["invoiced"]
    assert sum(r["invoiced"] for r in report["series"]["by_day"]) == report["kpis"]["invoiced"]
    assert sum(r["total"] for r in report["tables"]["top_services"]) == report["kpis"]["invoiced"]


def test_vital_history_and_no_followup_choice(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_clinical import clinical_record
    from modules.clinics.service_ops import complete_visit_extended
    from modules.clinics.models import ClinicFollowUp
    patient = service.create_patient(1, {"full_name": "مريض"})
    visit = service.create_walkin_visit(1, {"patient_id": patient["id"]})
    service.save_vitals(1, visit["id"], {"weight_kg": 70, "bmi": 23, "blood_glucose": 100})
    history = clinical_record(1, patient["id"], section="vitals")
    assert history["items"][0]["blood_glucose"] == 100
    complete_visit_extended(1, visit["id"], auto_invoice=False, create_followup=False)
    assert ClinicFollowUp.query.filter_by(visit_id=visit["id"]).count() == 0


def test_public_booking_template_javascript_parses(specialty_db):
    import re
    import shutil
    import subprocess
    from pathlib import Path
    from flask import render_template
    from modules.clinics.service_booking import public_clinic_info
    specialty_db.template_folder = str(Path(__file__).resolve().parents[1] / "templates")
    node = shutil.which("node")
    if not node:
        pytest.skip("Node runtime unavailable")
    with specialty_db.test_request_context():
        html = render_template("clinics/public_booking.html", clinic=public_clinic_info(1), tenant_slug="test", error=None)
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert scripts
    for script in scripts:
        result = subprocess.run([node, "--check"], input=script, text=True, encoding="utf-8", capture_output=True)
        assert result.returncode == 0, result.stderr


def test_dashboard_role_financial_redaction(specialty_db):
    from types import SimpleNamespace
    from modules.clinics.service_dashboard import dashboard_snapshot
    employee = SimpleNamespace(id=9, role="doctor", name="طبيب", username="doctor", profile_pic="", roles=[])
    result = dashboard_snapshot(1, employee=employee)
    assert result["finance"] is None
    assert "revenue_today" not in result["kpis"]
    assert "avg_visit_value" not in result["performance"]
    assert not result["activities"]


def test_activity_log_page_is_owner_only(specialty_db):
    from types import SimpleNamespace
    from modules.clinics import service
    from modules.clinics.service_dashboard import activity_log

    service.create_patient(1, {"full_name": "مريض النشاط", "phone": "0770000111"})
    owner = SimpleNamespace(id=1, role="admin", name="مدير", username="admin", profile_pic="", roles=[])
    staff = SimpleNamespace(id=9, role="doctor", name="طبيب", username="doctor", profile_pic="", roles=[])
    payload = activity_log(1, employee=owner)
    assert payload["total"] >= 1
    assert payload["items"][0]["summary"]
    denied = activity_log(1, employee=staff)
    assert denied["total"] == 0
    assert denied["items"] == []


def test_legacy_specialty_migration_is_idempotent(specialty_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicDoctorSpecialty, ClinicSettings
    from modules.clinics.service_specialties import migrate_legacy_specialties

    with specialty_db.app_context():
        settings = ClinicSettings(tenant_id=1, clinic_type="dental")
        db.session.add(settings)
        doctor = service.create_doctor(1, {"full_name": "د. قديم", "specialty": "الأسنان"})
        migrate_legacy_specialties(1)
        migrate_legacy_specialties(1)
        links = ClinicDoctorSpecialty.query.filter_by(tenant_id=1, doctor_id=doctor["id"]).all()
        assert len(links) == 1
        assert links[0].is_primary is True
        assert settings.organization_mode == "solo_clinic"


def test_update_settings_prefers_organization_mode_over_clinic_type(specialty_db):
    from modules.clinics.models import ClinicSettings
    from modules.clinics.service import update_settings, settings_payload

    with specialty_db.app_context():
        db.session.add(ClinicSettings(tenant_id=1, clinic_type="dental", organization_mode="solo_clinic"))
        db.session.flush()
        # Saving org mode alone must not rewrite clinic_type or mix specialties into org mode.
        payload = update_settings(1, {"organization_mode": "multi_doctor_clinic", "clinic_name": "عيادة اختبار"})
        row = ClinicSettings.query.filter_by(tenant_id=1).one()
        assert row.organization_mode == "multi_doctor_clinic"
        assert row.clinic_type == "dental"
        assert payload["organization_mode"] == "multi_doctor_clinic"
        # Legacy org-shaped clinic_type maps into organization_mode and is not stored as clinic_type.
        update_settings(1, {"clinic_type": "medical_center"})
        row = ClinicSettings.query.filter_by(tenant_id=1).one()
        assert row.organization_mode == "medical_center"
        assert row.clinic_type == "dental"  # specialty hint preserved; org shape not written back
        assert settings_payload(1)["organization_mode_label"] == "مجمع طبي"


def test_migration_preserves_later_mode_choice_and_core_only_visits(specialty_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicSettings, ClinicVisit
    from modules.clinics.service_specialties import migrate_legacy_specialties, seed_default_specialties
    with specialty_db.app_context():
        db.session.add(ClinicSettings(tenant_id=1, clinic_type="multi_doctor"))
        doctor = service.create_doctor(1, {"full_name":"Legacy", "specialty":"الباطنية"})
        patient = service.create_patient(1, {"full_name":"Historical"})
        visit = service.create_walkin_visit(1, {"patient_id":patient["id"], "doctor_id":doctor["id"]})
        migrate_legacy_specialties(1)
        settings = ClinicSettings.query.filter_by(tenant_id=1).one()
        settings.organization_mode = "medical_center"
        seed_default_specialties(1)
        migrate_legacy_specialties(1)
        assert settings.organization_mode == "medical_center"
        assert db.session.get(ClinicVisit, visit["id"]).visit_template_id is None


def test_template_draft_edit_archive_and_tenant_boundary(specialty_db):
    from modules.clinics.service_specialties import (
        seed_default_specialties, create_template, update_template, publish_template,
        archive_template, template_dict,
    )
    with specialty_db.app_context():
        specialty = seed_default_specialties(1)[0]
        template = create_template(1, specialty["id"], {"name":"Draft"})
        sections = [{"title_ar":"Section", "fields":[{"key":"notes", "label_ar":"Notes", "field_type":"text"}]}]
        updated = update_template(1, template["id"], {"sections":sections})
        assert len(updated["sections"]) == 1
        updated = update_template(1, template["id"], {"sections":sections})
        assert len(updated["sections"]) == 1
        with pytest.raises(ValueError):
            update_template(2, template["id"], {"name":"Cross tenant"})
        publish_template(1, template["id"])
        with pytest.raises(ValueError):
            update_template(1, template["id"], {"name":"Changed"})
        archive_template(1, template["id"])
        assert template_dict(1, template["id"])["sections"]
        with pytest.raises(ValueError):
            publish_template(1, template["id"])


def test_invalid_values_do_not_partially_overwrite(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_specialties import seed_default_specialties, save_visit_values, visit_template_context
    with specialty_db.app_context():
        specialty = next(s for s in seed_default_specialties(1) if s["code"] == "internal_medicine")
        doctor = service.create_doctor(1, {"full_name":"D", "primary_specialty_id":specialty["id"]})
        patient = service.create_patient(1, {"full_name":"P"})
        visit = service.create_walkin_visit(1, {"doctor_id":doctor["id"], "patient_id":patient["id"]})
        context = visit_template_context(1, visit["id"])
        fields = {f["key"]:f for s in context["template"]["sections"] for f in s["fields"]}
        text_id = str(fields["history_present_illness"]["id"])
        select_id = str(fields["smoking"]["id"])
        save_visit_values(1, visit["id"], {"values":{text_id:"Original"}})
        with pytest.raises(ValueError):
            save_visit_values(1, visit["id"], {"values":{text_id:"Overwritten", select_id:"Invalid"}})
        assert visit_template_context(1, visit["id"])["values"][text_id] == "Original"


def test_schema_migrates_without_staff_context(specialty_db, monkeypatch):
    from modules.clinics import schema
    from modules.clinics.models import ClinicDoctor, ClinicDoctorSpecialty, ClinicSettings
    with specialty_db.app_context():
        db.session.add(ClinicSettings(tenant_id=1, clinic_type="dental"))
        db.session.add(ClinicDoctor(tenant_id=1, full_name="Legacy"))
        db.session.commit()
        monkeypatch.setattr(schema, "_engine", lambda: db.engine)
        schema.clear_clinics_schema_cache()
        schema.ensure_clinics_schema()
        db.session.expire_all()
        assert ClinicDoctorSpecialty.query.filter_by(tenant_id=1).count() == 1
        schema.clear_clinics_schema_cache()
        schema.ensure_clinics_schema()
        assert ClinicDoctorSpecialty.query.filter_by(tenant_id=1).count() == 1


@pytest.mark.parametrize("extended", [False, True])
def test_required_fields_block_completion_before_billing(specialty_db, extended):
    from modules.clinics import service
    from modules.clinics.models import ClinicVisit, ClinicInvoice
    from modules.clinics.service_ops import complete_visit_extended
    from modules.clinics.service_specialties import create_specialty, create_template, publish_template, save_visit_values
    with specialty_db.app_context():
        spec = create_specialty(1, {"name_ar":"اختبار", "code":"required_test"})
        template = create_template(1, spec["id"], {"sections":[{"title_ar":"قسم", "fields":[
            {"key":"assessment", "label_ar":"التقييم", "field_type":"textarea", "required":True},
            {"key":"reviewed", "label_ar":"تمت المراجعة", "field_type":"boolean", "required":True},
        ]}]})
        publish_template(1, template["id"])
        doctor = service.create_doctor(1, {"full_name":"D", "primary_specialty_id":spec["id"]})
        patient = service.create_patient(1, {"full_name":"P"})
        visit = service.create_walkin_visit(1, {"patient_id":patient["id"], "doctor_id":doctor["id"]})
        complete = complete_visit_extended if extended else service.complete_visit
        fields = template["sections"][0]["fields"]
        values = {str(fields[0]["id"]):"   ", str(fields[1]["id"]):False}
        save_visit_values(1, visit["id"], {"values":values})
        with pytest.raises(ValueError, match="الحقل مطلوب"):
            complete(1, visit["id"])
        assert db.session.get(ClinicVisit, visit["id"]).status == "open"
        assert ClinicInvoice.query.filter_by(tenant_id=1, visit_id=visit["id"]).count() == 0
        values[str(fields[0]["id"])] = "تم توثيق التقييم"
        save_visit_values(1, visit["id"], {"values":values})
        complete(1, visit["id"], auto_invoice=False)
        assert db.session.get(ClinicVisit, visit["id"]).status == "completed"


def test_seed_specialty_templates_reuses_patient_and_is_idempotent(specialty_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicPatient, ClinicVisitTemplate
    from modules.clinics.service_specialties import seed_default_specialties
    with specialty_db.app_context():
        specialties = seed_default_specialties(1)
        template_count = ClinicVisitTemplate.query.filter_by(tenant_id=1).count()
        seed_default_specialties(1)
        assert template_count >= 5
        assert ClinicVisitTemplate.query.filter_by(tenant_id=1).count() == template_count
        patient = service.create_patient(1, {"full_name":"ملف مشترك"})
        for code in ("internal_medicine", "dentistry", "pediatrics", "obstetrics_gynecology", "cardiology"):
            spec = next(s for s in specialties if s["code"] == code)
            doctor = service.create_doctor(1, {"full_name":code, "primary_specialty_id":spec["id"]})
            visit = service.create_walkin_visit(1, {"doctor_id":doctor["id"], "patient_id":patient["id"]})
            detail = service.get_visit_detail(1, visit["id"])
            assert detail["template"]["specialty_id"] == spec["id"]
            assert detail["template"]["sections"]
        assert ClinicPatient.query.filter_by(tenant_id=1).count() == 1


@pytest.mark.parametrize("rules", [
    {"a": "b", "b": "a"},
    {"a": "b", "b": "c", "c": "a"},
])
def test_template_publish_rejects_visibility_cycles(specialty_db, rules):
    from modules.clinics.service_specialties import create_specialty, create_template, publish_template
    spec = create_specialty(1, {"name_ar": "دورات", "code": "visibility_cycles"})
    fields = []
    for key in ("a", "b", "c"):
        field = {"key": key, "label_ar": key, "field_type": "text"}
        if key in rules:
            field["visibility_rules"] = {"field_key": rules[key], "operator": "eq", "value": "yes"}
        fields.append(field)
    template = create_template(1, spec["id"], {"name": "Cycle", "sections": [{"title_ar": "S", "fields": fields}]})
    with pytest.raises(ValueError, match="دائري"):
        publish_template(1, template["id"])


def test_template_publish_allows_acyclic_visibility_chain(specialty_db):
    from modules.clinics.service_specialties import create_specialty, create_template, publish_template
    spec = create_specialty(1, {"name_ar": "سلسلة", "code": "visibility_chain"})
    template = create_template(1, spec["id"], {"name": "Chain", "sections": [{"title_ar": "S", "fields": [
        {"key": "a", "label_ar": "A", "field_type": "text"},
        {"key": "b", "label_ar": "B", "field_type": "text", "visibility_rules": {"field_key": "a", "operator": "not_empty"}},
        {"key": "c", "label_ar": "C", "field_type": "text", "visibility_rules": {"field_key": "b", "operator": "contains", "value": "x"}},
    ]}]})
    assert publish_template(1, template["id"])["status"] == "published"


def test_procedures_are_linked_and_prioritized_for_visit_specialty(specialty_db):
    from modules.clinics.service_clinical_ops import save_procedure
    from modules.clinics.service_ops import list_procedures
    from modules.clinics.service_specialties import create_specialty

    dental = create_specialty(1, {"name_ar": "أسنان", "code": "procedure_dental"})
    internal = create_specialty(1, {"name_ar": "باطنية", "code": "procedure_internal"})
    matching = save_procedure(1, {"name": "إجراء الأسنان", "specialty_ids": [dental["id"]]})
    unrestricted = save_procedure(1, {"name": "إجراء عام"})
    mismatched = save_procedure(1, {"name": "إجراء الباطنية", "specialty_ids": [internal["id"]]})

    ordered = list_procedures(1, specialty_id=dental["id"])
    assert [row["id"] for row in ordered] == [matching["id"], unrestricted["id"], mismatched["id"]]
    assert ordered[0]["specialty_ids"] == [dental["id"]]
    assert ordered[0]["specialty_match"] is True


def test_procedure_specialty_update_rejects_other_tenant_without_losing_links(specialty_db):
    from modules.clinics.models import ClinicProcedureSpecialty
    from modules.clinics.service_clinical_ops import save_procedure
    from modules.clinics.service_specialties import create_specialty

    own = create_specialty(1, {"name_ar": "محلي", "code": "procedure_own"})
    foreign = create_specialty(2, {"name_ar": "خارجي", "code": "procedure_foreign"})
    procedure = save_procedure(1, {"name": "إجراء", "specialty_ids": [own["id"]]})
    db.session.commit()
    with pytest.raises(ValueError, match="غير تابع"):
        save_procedure(1, {"name": "إجراء معدل", "specialty_ids": [foreign["id"]]}, procedure_id=procedure["id"])
    db.session.rollback()

    links = ClinicProcedureSpecialty.query.filter_by(tenant_id=1, procedure_id=procedure["id"]).all()
    assert [row.specialty_id for row in links] == [own["id"]]


def test_procedures_center_hides_revenue_without_billing_permission(specialty_db):
    from modules.clinics.service_clinical_ops import procedures_center

    hidden = procedures_center(1, {"tab": "catalog"}, include_financial=False)
    visible = procedures_center(1, {"tab": "catalog"}, include_financial=True)
    assert "revenue_today" not in hidden["stats"]
    assert visible["stats"]["revenue_today"] == 0


def test_doctor_list_uses_bulk_specialty_query(specialty_db):
    from sqlalchemy import event
    from modules.clinics import service
    from modules.clinics.service_specialties import create_specialty

    with specialty_db.app_context():
        spec = create_specialty(1, {"name_ar": "قياس", "code": "bulk_query"})
        for index in range(8):
            service.create_doctor(1, {"full_name": f"طبيب {index}", "primary_specialty_id": spec["id"]})
        db.session.commit()
        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            if "clinic" in statement.lower():
                statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", capture)
        try:
            doctors = service.list_doctors(1)
        finally:
            event.remove(db.engine, "before_cursor_execute", capture)
        assert len(doctors) == 8
        specialty_queries = [sql for sql in statements if "clinic_doctor_specialty" in sql.lower()]
        # One bulk link query (SQLite may emit a companion statement while
        # resolving the joined specialty rows); crucially it is constant,
        # not one query per doctor.
        assert len(specialty_queries) <= 2
