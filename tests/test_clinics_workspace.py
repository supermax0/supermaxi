"""Regression tests for Finora Clinics foundation."""
from datetime import date

import pytest
from flask import Flask

from extensions import db
from modules.clinics.guards import BUSINESS_TYPE, CLINICS_PERMISSIONS
from modules.clinics.models import CLINIC_MODELS


@pytest.fixture()
def clinics_db():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        SECRET_KEY="test",
        DEBUG=True,
    )
    db.init_app(app)
    import models  # noqa: F401
    from models.delivery_agent import DeliveryAgent  # noqa: F401
    from modules.clinics.models import CLINIC_MODELS as _M  # noqa: F401
    from modules.wholesale.models.warehouse import Warehouse  # noqa: F401

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_business_type_and_permissions_are_isolated():
    from routes.superadmin import BUSINESS_TYPES, _clean_business_type

    assert BUSINESS_TYPE == "clinics"
    assert BUSINESS_TYPES[BUSINESS_TYPE] == "عيادات Finora"
    assert _clean_business_type(BUSINESS_TYPE) == BUSINESS_TYPE
    assert "clinics_dashboard" in CLINICS_PERMISSIONS
    assert all(name.startswith("clinics_") for name in CLINICS_PERMISSIONS)


def test_clinics_blueprint_routes_are_namespaced():
    from modules.clinics.routes import PAGE_CONFIG, calendar_redirect, clinics_bp
    from modules.clinics.public_routes import clinics_public_bp

    assert clinics_bp.url_prefix == "/clinics"
    assert clinics_public_bp.url_prefix == "/book"
    assert "appointments" in PAGE_CONFIG
    assert "calendar" not in PAGE_CONFIG
    assert "expenses" in PAGE_CONFIG
    assert "cash" in PAGE_CONFIG
    assert "attachments" in PAGE_CONFIG
    assert "activity" in PAGE_CONFIG
    assert PAGE_CONFIG["activity"][1] == "clinics_dashboard"
    assert callable(calendar_redirect)


def test_appointment_conflict_and_reschedule(clinics_db):
    from modules.clinics import service

    with clinics_db.app_context():
        patient = service.create_patient(1, {"full_name": "أحمد علي", "phone": "0770111222"})
        doctor = service.create_doctor(1, {"full_name": "د. سارة", "specialty": "عام"})
        day = date.today().isoformat()
        a1 = service.create_appointment(
            1,
            {
                "patient_id": patient["id"],
                "doctor_id": doctor["id"],
                "appointment_date": day,
                "start_time": "10:00",
                "duration_minutes": 30,
            },
        )
        with pytest.raises(ValueError, match="تعارض"):
            service.create_appointment(
                1,
                {
                    "patient_id": patient["id"],
                    "doctor_id": doctor["id"],
                    "appointment_date": day,
                    "start_time": "10:15",
                    "duration_minutes": 30,
                },
            )
        moved = service.reschedule_appointment(
            1,
            a1["id"],
            {"appointment_date": day, "start_time": "11:00"},
        )
        assert moved["start_time"] == "11:00"
        db.session.commit()


def test_doctor_hr_leave_and_termination_block_new_appointments(clinics_db):
    from models.employee import Employee
    from models.hr import HREmployeeProfile, HRLeaveRequest
    from modules.clinics import service
    from modules.clinics.service_ops import upsert_schedule

    with clinics_db.app_context():
        employee = Employee(
            tenant_id=1, name="طبيب موظف", username="doctor-hr", password="x",
            role="doctor", is_active=True, salary=1_500_000,
        )
        db.session.add(employee)
        db.session.flush()
        profile = HREmployeeProfile(
            employee_id=employee.id, employee_code="EMP-0018",
            employment_status="active", employment_type="full_time",
        )
        db.session.add(profile)
        doctor = service.create_doctor(1, {"full_name": "د. مرتبط", "employee_id": employee.id})
        upsert_schedule(1, {
            "doctor_id": doctor["id"], "weekday": date.today().weekday(),
            "start_time": "09:00", "end_time": "17:00",
        })
        patient = service.create_patient(1, {"full_name": "مريض HR"})
        leave = HRLeaveRequest(
            employee_id=employee.id, leave_type="annual", start_date=date.today(),
            end_date=date.today(), days_count=1, status="approved",
        )
        db.session.add(leave)
        db.session.flush()
        with pytest.raises(ValueError, match="إجازة HR"):
            service.create_appointment(1, {
                "patient_id": patient["id"], "doctor_id": doctor["id"],
                "appointment_date": date.today().isoformat(), "start_time": "10:00",
            })

        leave.status = "cancelled"
        profile.employment_status = "terminated"
        with pytest.raises(ValueError, match="الحالة الوظيفية"):
            service.create_appointment(1, {
                "patient_id": patient["id"], "doctor_id": doctor["id"],
                "appointment_date": date.today().isoformat(), "start_time": "10:00",
            })


def test_doctor_center_reads_hr_without_exposing_salary(clinics_db):
    from models.employee import Employee
    from models.hr import HREmployeeProfile
    from modules.clinics import service
    from modules.clinics.service_doctors import doctor_workspace, doctors_center

    with clinics_db.app_context():
        employee = Employee(
            tenant_id=1, name="طبيب خصوصية", username="doctor-private", password="x",
            role="doctor", is_active=True, salary=2_000_000,
        )
        db.session.add(employee)
        db.session.flush()
        db.session.add(HREmployeeProfile(
            employee_id=employee.id, employee_code="EMP-PRIV",
            employment_status="active", employment_type="full_time",
            annual_leave_entitlement=21,
        ))
        doctor = service.create_doctor(1, {
            "full_name": "د. خصوصية", "specialty": "باطنية", "employee_id": employee.id,
        })
        db.session.flush()
        center = doctors_center(1, {"q": "EMP-PRIV", "page": 1, "per_page": 10})
        assert center["total"] == 1
        assert center["items"][0]["employee_code"] == "EMP-PRIV"
        hidden = doctor_workspace(1, doctor["id"], can_view_salary=False)
        visible = doctor_workspace(1, doctor["id"], can_view_salary=True)
        assert hidden["hr"]["salary"] is None
        assert hidden["hr"]["salary_visible"] is False
        assert visible["hr"]["salary"] == 2_000_000


def test_specialty_pack_and_expense_refund_cash(clinics_db):
    from modules.clinics import service
    from modules.clinics.service_extras import (
        close_cash_session,
        create_expense,
        open_cash_session,
        refund_invoice,
        seed_specialty_pack,
    )
    from modules.clinics.models import ClinicInvoice

    with clinics_db.app_context():
        seeded = seed_specialty_pack(1, "dental")
        assert seeded["created"]["services"] >= 1
        expense = create_expense(1, {"title": "كهرباء", "amount": 5000, "expense_date": date.today().isoformat()})
        assert expense["amount"] == 5000
        session = open_cash_session(1, {"opening_cash": 10000, "business_date": date.today().isoformat()})
        assert session["status"] == "open"
        patient = service.create_patient(1, {"full_name": "مريض فاتورة", "phone": "0770333444"})
        doctor = service.create_doctor(1, {"full_name": "د. كريم"})
        svc = service.create_service(1, {"name": "كشف اختبار", "price": 20000, "duration_minutes": 15})
        visit = service.create_walkin_visit(
            1,
            {"patient_id": patient["id"], "doctor_id": doctor["id"], "service_id": svc["id"]},
        )
        service.complete_visit(1, visit["id"], auto_invoice=True)
        inv = ClinicInvoice.query.filter_by(tenant_id=1, visit_id=visit["id"]).first()
        assert inv is not None
        assert inv.total > 0
        total = inv.total
        service.receive_payment(1, inv.id, {"amount": total, "method": "cash"})
        refunded = refund_invoice(1, inv.id, {"amount": total // 2, "reason": "اختبار"})
        assert refunded["invoice"]["paid"] == total - (total // 2)
        closed = close_cash_session(1, session["id"], {})
        assert closed["status"] == "closed"
        db.session.commit()


def test_treatment_bill_lines_and_discount(clinics_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicInvoice
    from modules.clinics.service_ops import (
        add_visit_bill_line,
        complete_visit_extended,
        visit_treatment_bill_preview,
    )

    with clinics_db.app_context():
        patient = service.create_patient(1, {"full_name": "مريض وصفة", "phone": "0770444555"})
        doctor = service.create_doctor(1, {"full_name": "د. ليلى"})
        svc = service.create_service(1, {"name": "كشف", "price": 15000, "duration_minutes": 15})
        visit = service.create_walkin_visit(
            1,
            {"patient_id": patient["id"], "doctor_id": doctor["id"], "service_id": svc["id"]},
        )
        add_visit_bill_line(
            1,
            visit["id"],
            {"description": "حقنة", "quantity": 2, "unit_price": 3000},
        )
        preview = visit_treatment_bill_preview(1, visit["id"])
        assert preview["subtotal"] == 15000 + 6000
        complete_visit_extended(1, visit["id"], discount=2000)
        inv = ClinicInvoice.query.filter_by(tenant_id=1, visit_id=visit["id"]).first()
        assert inv is not None
        assert inv.discount == 2000
        assert inv.total == preview["subtotal"] - 2000
        db.session.commit()


def test_booking_otp_optional(clinics_db):
    from modules.clinics.service import update_settings
    from modules.clinics.service_extras import request_booking_otp, verify_booking_otp

    with clinics_db.app_context():
        update_settings(1, {"booking_otp_enabled": True, "allow_online_booking": True})
        otp = request_booking_otp(1, "0770555666")
        assert otp["required"] is True
        assert otp.get("debug_code")
        assert verify_booking_otp(1, "0770555666", otp["debug_code"]) is True
        db.session.commit()


def test_model_count_covers_phase2_tables():
    names = {m.__tablename__ for m in CLINIC_MODELS}
    for required in (
        "clinic_expense",
        "clinic_refund",
        "clinic_attachment",
        "clinic_consent",
        "clinic_cash_session",
        "clinic_booking_otp",
        "clinic_follow_up",
        "clinic_reminder",
        "clinic_visit_bill_line",
    ):
        assert required in names


def test_patient_clinical_record_uses_existing_visit_records(clinics_db):
    from modules.clinics import service
    from modules.clinics.service_clinical import clinical_record, recent_patients

    with clinics_db.app_context():
        patient = service.create_patient(1, {"full_name": "مريض السجل", "allergies": "بنسلين"})
        doctor = service.create_doctor(1, {"full_name": "د. اختبار"})
        visit = service.create_walkin_visit(1, {"patient_id": patient["id"], "doctor_id": doctor["id"]})
        service.add_diagnosis(1, visit["id"], {"title": "ارتفاع ضغط الدم", "status": "active"})
        service.save_prescription(1, visit["id"], {"items": [{"medicine_name": "Amlodipine", "dosage": "5mg"}]})
        overview = clinical_record(1, patient["id"], "overview")
        timeline = clinical_record(1, patient["id"], "timeline")
        assert overview["patient"]["allergies"] == "بنسلين"
        assert overview["diagnoses"][0]["title"] == "ارتفاع ضغط الدم"
        assert overview["prescriptions"][0]["items"][0]["medicine_name"] == "Amlodipine"
        assert {event["type"] for event in timeline["items"]} >= {"visit", "diagnosis", "prescription"}
        assert recent_patients(1, "مريض")[0]["id"] == patient["id"]


def test_attachment_listing_is_paginated(clinics_db):
    from modules.clinics import service
    from modules.clinics.service_extras import list_attachments

    with clinics_db.app_context():
        patient = service.create_patient(1, {"full_name": "مريض المرفقات"})
        result = list_attachments(1, {"patient_id": patient["id"], "page": 1, "per_page": 25})
        assert result["items"] == []
        assert result["total"] == 0
        assert result["per_page"] == 25
        assert result["stats"]["total"] == 0


def test_clinical_operations_workflows_and_inventory_idempotency(clinics_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicInventoryItem, ClinicInventoryMovement
    from modules.clinics.service_clinical_ops import (
        StateConflict, add_execution, create_followup, save_procedure,
        transition_execution, transition_lab,
    )
    from modules.clinics.service_ops import create_inventory_item, create_lab_order, create_lab_test, update_lab_result

    with clinics_db.app_context():
        patient = service.create_patient(1, {"full_name": "مريض العمليات"})
        doctor = service.create_doctor(1, {"full_name": "د. العمليات"})
        visit = service.create_walkin_visit(1, {"patient_id": patient["id"], "doctor_id": doctor["id"]})
        test = create_lab_test(1, {"name": "CBC"})
        order = create_lab_order(1, {"patient_id": patient["id"], "doctor_id": doctor["id"], "visit_id": visit["id"], "test_ids": [test["id"]]})
        transition_lab(1, order["id"], {"expected_status": "requested", "status": "sample_collected"})
        item_id = order["items"][0]["id"]
        ready = update_lab_result(1, item_id, {"value": "14.8", "unit": "10^9/L", "abnormal_flag": "high"})
        assert ready["status"] == "result_ready"

        stock = create_inventory_item(1, {"name": "شاش", "sku": "GAUZE-QA", "current_stock": 10})
        procedure = save_procedure(1, {"name": "تبديل ضماد", "price": 10000, "recipe": [{"item_id": stock["id"], "quantity": 2}]})
        execution = add_execution(1, {"visit_id": visit["id"], "procedure_id": procedure["id"], "quantity": 1})
        transition_execution(1, execution["id"], {"expected_status": "requested", "status": "completed"})
        transition_execution(1, execution["id"], {"expected_status": "completed", "status": "completed"})
        assert float(ClinicInventoryItem.query.get(stock["id"]).current_stock) == 8
        assert ClinicInventoryMovement.query.filter_by(reference_type="visit_procedure", reference_id=execution["id"]).count() == 1

        due = date.today().isoformat()
        create_followup(1, {"patient_id": patient["id"], "visit_id": visit["id"], "doctor_id": doctor["id"], "followup_type": "treatment_review", "due_date": due})
        with pytest.raises(StateConflict, match="متابعة مشابهة"):
            create_followup(1, {"patient_id": patient["id"], "visit_id": visit["id"], "doctor_id": doctor["id"], "followup_type": "treatment_review", "due_date": due})


def test_services_center_and_update(clinics_db):
    from modules.clinics import service

    with clinics_db.app_context():
        created = service.create_service(
            1,
            {
                "name": "كشف عام",
                "category": "كشف",
                "duration_minutes": 15,
                "price": 20000,
                "doctor_commission_pct": 10,
            },
        )
        service.create_service(
            1,
            {"name": "متابعة", "category": "متابعة", "duration_minutes": 10, "price": 15000, "active": False},
        )

        center = service.services_center(1, {"q": "كشف", "status": "active"})
        assert center["pagination"]["total"] == 1
        assert center["items"][0]["name"] == "كشف عام"
        assert center["kpis"]["total"] == 2
        assert center["kpis"]["active"] == 1

        updated = service.update_service(
            1,
            created["id"],
            {"price": 25000, "duration_minutes": 20, "requires_room": True},
        )
        assert updated["price"] == 25000
        assert updated["duration_minutes"] == 20
        assert updated["requires_room"] is True

        with pytest.raises(ValueError, match="نفس الاسم"):
            service.create_service(1, {"name": "كشف عام", "price": 1000})
        db.session.commit()


def test_prescription_print_template_includes_clinic_branding():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    js = (root / "static/clinics/prescription-print.js").read_text(encoding="utf-8")
    doctor = (root / "static/clinics/doctor.js").read_text(encoding="utf-8")
    clinics = (root / "static/clinics/clinics.js").read_text(encoding="utf-8")
    workspace = (root / "templates/clinics/workspace.html").read_text(encoding="utf-8")
    assert "rx-clinic-name" in js
    assert "rx-logo" in js
    assert "وصفة طبية" in js
    assert "Medical Prescription" in js
    assert "معلومات المريض" not in js
    assert "معلومات الزيارة" not in js
    assert "Patient Information" not in js
    assert "Visit Information" not in js
    assert "ClinicsPrintPrescription" in doctor
    assert "prescription-print.js" in workspace
    assert 'id="set_logo"' in clinics
    assert "public_logo_url" in clinics


def test_visit_dict_includes_print_patient_and_doctor_fields(clinics_db):
    from modules.clinics import service

    with clinics_db.app_context():
        patient = service.create_patient(
            1,
            {
                "full_name": "سجاد احمد",
                "phone": "07734049148",
                "gender": "male",
                "date_of_birth": "2002-01-01",
            },
        )
        doctor = service.create_doctor(
            1,
            {
                "full_name": "د. أحمد النوري",
                "scientific_title": "طبيب عام",
                "license_number": "MD-12345",
            },
        )
        visit = service.create_walkin_visit(1, {"patient_id": patient["id"], "doctor_id": doctor["id"]})
        assert visit["patient_gender"] == "male"
        assert visit["patient_age"] is not None
        assert visit["patient_age"] >= 20
        assert visit["doctor_title"] == "طبيب عام"
        assert visit["doctor_license"] == "MD-12345"
        branded = service.update_settings(
            1,
            {
                "clinic_name": "عيادات فينورا الطبية",
                "public_logo_url": "/static/finora-logo.svg",
                "clinic_whatsapp_number": "07734049148",
                "public_location": "بغداد — العراق",
            },
        )
        assert branded["clinic_name"] == "عيادات فينورا الطبية"
        assert branded["public_logo_url"] == "/static/finora-logo.svg"
        assert branded["clinic_whatsapp_number"] == "07734049148"
