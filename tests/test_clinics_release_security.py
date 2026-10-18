"""Release gates: inspect actual clinical JSON and standalone child queries."""
import json
from types import SimpleNamespace

import pytest
from flask import jsonify

from extensions import db
from tests.test_clinics_specialties import specialty_db  # noqa: F401


@pytest.mark.parametrize("section", ["overview", "timeline", "visits", "diagnoses", "prescriptions", "attachments", "vitals"])
@pytest.mark.parametrize("broader_read", [False, True])
def test_shared_record_requires_explicit_permission(specialty_db, monkeypatch, section, broader_read):
    from modules.clinics import guards, service
    from modules.clinics.service_clinical import clinical_record
    from modules.clinics.models import ClinicDoctor, ClinicDiagnosis, ClinicPrescription, ClinicPrescriptionItem, ClinicAttachment

    doctors = [service.create_doctor(1, {"full_name": name}) for name in ("Own", "Other")]
    patient = service.create_patient(1, {"full_name": "Shared", "allergies": "SHARED_ALLERGY"})
    visits = [service.create_walkin_visit(1, {"patient_id": patient["id"], "doctor_id": d["id"]}) for d in doctors]
    for index, visit in enumerate(visits):
        marker = "OWN_NOTE" if index == 0 else "FOREIGN_PRIVATE_NOTE"
        service.update_visit(1, visit["id"], {"clinical_notes": marker})
        db.session.add(ClinicDiagnosis(tenant_id=1, patient_id=patient["id"], visit_id=visit["id"], title=marker))
        rx = ClinicPrescription(tenant_id=1, patient_id=patient["id"], visit_id=visit["id"], doctor_id=doctors[index]["id"], notes=marker)
        db.session.add(rx)
        db.session.flush()
        db.session.add(ClinicPrescriptionItem(tenant_id=1, prescription_id=rx.id, medicine_name=marker))
        db.session.add(ClinicAttachment(tenant_id=1, patient_id=patient["id"], visit_id=visit["id"], file_name=marker, stored_name=marker))
    db.session.commit()
    permissions = {"clinics_clinical"}
    if broader_read:
        permissions.add("clinics_clinical_shared_read")
    employee = SimpleNamespace(id=10, role="doctor", is_active=True, has_permission=lambda key: key in permissions)
    monkeypatch.setattr(guards, "current_employee", lambda: employee)
    monkeypatch.setattr(guards, "current_tenant_id", lambda: 1)
    monkeypatch.setattr(guards, "is_clinics_tenant", lambda: True)
    monkeypatch.setattr(guards, "get_current_clinic_doctor", lambda: db.session.get(ClinicDoctor, doctors[0]["id"]))

    @guards.require_clinics("clinics_clinical", json_mode=True)
    def api_clinical_record():
        return jsonify(clinical_record(1, patient["id"], section=section))

    @guards.require_clinics("clinics_clinical", json_mode=True)
    def operational_items():
        return [r.medicine_name for r in ClinicPrescriptionItem.query.all()]

    with specialty_db.test_request_context("/clinics/api/clinical/patients/1"):
        payload = api_clinical_record().get_json()
        assert payload["patient"]["allergies"] == "SHARED_ALLERGY"
        if not broader_read:
            assert "FOREIGN_PRIVATE_NOTE" not in json.dumps(payload)
        elif section != "vitals":
            assert "FOREIGN_PRIVATE_NOTE" in json.dumps(payload)
    # The broader READ permission never unlocks operational child queries.
    with specialty_db.test_request_context("/clinics/api/prescriptions"):
        assert operational_items() == ["OWN_NOTE"]


@pytest.mark.parametrize("billing", [False, True])
def test_reception_json_financial_redaction(specialty_db, billing):
    from modules.clinics import service
    from modules.clinics.service_reception import get_reception_board
    doctor = service.create_doctor(1, {"full_name": "Doctor", "commission_pct": 25})
    patient = service.create_patient(1, {"full_name": "Patient"})
    service.create_appointment(1, {"patient_id": patient["id"], "doctor_id": doctor["id"],
                                  "appointment_date": "2026-09-04", "start_time": "10:00"})
    permissions = {"clinics_reception", "clinics_reports"}
    if billing:
        permissions.add("clinics_billing")
    employee = SimpleNamespace(id=10, name="Staff", username="staff", profile_pic=None,
                               role="reception", has_permission=lambda key: key in permissions,
                               roles=[SimpleNamespace(permissions=[SimpleNamespace(name=k) for k in permissions])])
    from datetime import date
    payload = get_reception_board(1, date(2026, 9, 4), employee=employee)
    encoded = json.dumps(payload)
    if not billing:
        for key in ("invoice_total", "invoice_paid", "invoice_balance", "commission_pct", "revenue"):
            assert '"' + key + '"' not in encoded
        assert payload["activities"] == []
    else:
        assert '"invoice_total"' in encoded
        assert "revenue" in payload["stats"]


@pytest.mark.parametrize("endpoint", ["summary", "hub", "export"])
def test_financial_reports_require_billing_permission(specialty_db, monkeypatch, endpoint):
    from modules.clinics import routes, guards
    employee = SimpleNamespace(id=10, role="doctor", is_active=True,
                               has_permission=lambda key: key == "clinics_reports")
    monkeypatch.setattr(guards, "current_employee", lambda: employee)
    monkeypatch.setattr(guards, "current_tenant_id", lambda: 1)
    monkeypatch.setattr(guards, "is_clinics_tenant", lambda: True)
    monkeypatch.setattr(guards, "get_current_clinic_doctor", lambda: None)
    monkeypatch.setattr(routes, "ensure_clinics_schema", lambda: None)
    specialty_db.register_blueprint(routes.clinics_bp)
    response = specialty_db.test_client().get(f"/clinics/api/reports/{endpoint}")
    assert response.status_code == 403
    assert response.get_json()["ok"] is False
    assert "data" not in response.get_json()


def test_patient_and_visit_payloads_hide_unpermitted_sections(specialty_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicInvoice
    doctor = service.create_doctor(1, {"full_name": "Doctor"})
    patient = service.create_patient(1, {"full_name": "Patient"})
    visit = service.create_walkin_visit(1, {"patient_id": patient["id"], "doctor_id": doctor["id"],
                                          "chief_complaint": "PRIVATE_COMPLAINT", "clinical_notes": "PRIVATE_NOTE"})
    db.session.add(ClinicInvoice(tenant_id=1, patient_id=patient["id"], doctor_id=doctor["id"],
                                 visit_id=visit["id"], invoice_number="PRIVATE-INVOICE", total=100, balance=100))
    db.session.commit()
    patient_payload = service.get_patient(1, patient["id"], include_clinical=False)
    encoded_patient = json.dumps(patient_payload)
    assert "PRIVATE_COMPLAINT" not in encoded_patient
    assert "PRIVATE_NOTE" not in encoded_patient
    visit_payload = service.get_visit_detail(1, visit["id"], include_financial=False)
    assert "invoices" not in visit_payload
    assert "bill_lines" not in visit_payload
    assert "PRIVATE-INVOICE" not in json.dumps(visit_payload)


def test_prescription_templates_are_tenant_and_scope_safe(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_prescription_templates import create_template, list_for_visit, archive_template
    from modules.clinics.service_specialties import create_specialty
    specs = [create_specialty(1, {"name_ar": name, "code": code}) for name, code in (("باطنية", "rx_internal"), ("غدد", "rx_endo"))]
    doctors = [service.create_doctor(1, {"full_name": name, "primary_specialty_id": specs[index]["id"]}) for index, name in enumerate(("A", "B"))]
    patient = service.create_patient(1, {"full_name": "P"})
    visits = [service.create_walkin_visit(1, {"patient_id": patient["id"], "doctor_id": doctors[index]["id"], "specialty_id": specs[index]["id"]}) for index in range(2)]
    item = [{"medicine_name": "Medicine", "dosage": "1"}]
    clinic = create_template(1, {"name": "Clinic", "scope_type": "clinic", "items": item})
    specialty = create_template(1, {"name": "Specialty", "scope_type": "specialty", "specialty_id": specs[0]["id"], "items": item})
    personal = create_template(1, {"name": "Personal", "scope_type": "doctor", "doctor_id": doctors[0]["id"], "items": item})
    assert {row["id"] for row in list_for_visit(1, visits[0]["id"])} == {clinic["id"], specialty["id"], personal["id"]}
    assert {row["id"] for row in list_for_visit(1, visits[1]["id"])} == {clinic["id"]}
    with pytest.raises(ValueError, match="الشخصية"):
        create_template(1, {"name": "Forbidden", "scope_type": "clinic", "items": item}, restricted_doctor_id=doctors[0]["id"])
    with pytest.raises(ValueError, match="طبيب آخر"):
        archive_template(1, personal["id"], restricted_doctor_id=doctors[1]["id"])
    with pytest.raises(ValueError, match="الزيارة"):
        list_for_visit(2, visits[0]["id"])
