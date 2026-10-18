"""Backend-only coverage for specialty resolution and the dental platform."""
from datetime import date

import pytest
from flask import Flask

from extensions import db


@pytest.fixture()
def clinic_db():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        SECRET_KEY="dental-platform",
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


def _setup(tenant_id=1, *, estimated_sessions=2):
    from modules.clinics import service
    from modules.clinics.models import ClinicProcedure
    from modules.clinics.service_dental_treatment import add_plan_item, create_plan
    from modules.clinics.service_specialties import seed_default_specialties

    specs = seed_default_specialties(tenant_id)
    dental = next(item for item in specs if item["code"] == "dentistry")
    general = next(item for item in specs if item["code"] == "general_medicine")
    doctor = service.create_doctor(
        tenant_id,
        {
            "full_name": f"Dentist {tenant_id}",
            "primary_specialty_id": dental["id"],
            "specialty_ids": [dental["id"]],
        },
    )
    patient = service.create_patient(tenant_id, {"full_name": f"Patient {tenant_id}"})
    visit = service.create_walkin_visit(
        tenant_id,
        {"patient_id": patient["id"], "doctor_id": doctor["id"]},
    )
    procedure = ClinicProcedure(
        tenant_id=tenant_id, name="Root canal", price=100, active=True
    )
    db.session.add(procedure)
    db.session.flush()
    plan = create_plan(
        tenant_id,
        patient["id"],
        {"status": "active", "created_by_doctor_id": doctor["id"]},
    )
    detail = add_plan_item(
        tenant_id,
        plan["plan"]["id"],
        {
            "procedure_id": procedure.id,
            "tooth_number": "16",
            "estimated_sessions": estimated_sessions,
        },
    )
    return {
        "dental": dental,
        "general": general,
        "doctor": doctor,
        "patient": patient,
        "visit": visit,
        "procedure": procedure,
        "plan": plan["plan"],
        "item": detail["items"][0],
    }


def test_resolver_priority_alias_features_and_snapshots(clinic_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicAppointment, ClinicSettings, ClinicVisit
    from modules.clinics.service_specialty_registry import (
        canonical_code,
        resolve_specialty,
    )
    from modules.clinics.service_specialties import seed_default_specialties

    specs = seed_default_specialties(1)
    dental = next(item for item in specs if item["code"] == "dentistry")
    general = next(item for item in specs if item["code"] == "general_medicine")
    settings = service.get_or_create_settings(1)
    settings.primary_specialty_id = dental["id"]
    settings.specialty_features_json = '{"dentistry":{"sessions":false,"custom":true}}'
    assert canonical_code("dental") == "dentistry"
    clinic_default = resolve_specialty(1)
    assert clinic_default["source"] == "clinic_primary"
    assert clinic_default["code"] == "dentistry"
    assert clinic_default["workspace"] == "dental"
    assert clinic_default["features"]["sessions"] is False
    assert clinic_default["features"]["custom"] is True

    doctor = service.create_doctor(
        1,
        {
            "full_name": "General doctor",
            "primary_specialty_id": general["id"],
            "specialty_ids": [general["id"]],
        },
    )
    assert resolve_specialty(1, doctor_id=doctor["id"])["source"] == "doctor_primary"
    patient = service.create_patient(1, {"full_name": "Snapshot patient"})
    appointment = service.create_appointment(
        1,
        {
            "patient_id": patient["id"],
            "doctor_id": doctor["id"],
            "appointment_date": date.today().isoformat(),
            "start_time": "10:00",
        },
    )
    appt = db.session.get(ClinicAppointment, appointment["id"])
    assert appt.specialty_code_snapshot == "general_medicine"
    visit_data = service.start_visit_from_appointment(1, appt.id)
    visit = db.session.get(ClinicVisit, visit_data["id"])
    assert visit.specialty_code_snapshot == "general_medicine"
    settings.primary_specialty_id = dental["id"]
    resolved = resolve_specialty(1, visit=visit)
    assert resolved["source"] == "visit_snapshot"
    assert resolved["code"] == "general_medicine"

    settings.primary_specialty_id = None
    empty = resolve_specialty(2)
    assert empty["source"] == "general"
    assert empty["code"] == "general_medicine"


def test_sessions_completion_is_idempotent_and_final_updates_status(clinic_db):
    from modules.clinics.models import (
        ClinicDentalTreatmentPlan,
        ClinicDentalTreatmentPlanItem,
        ClinicVisitProcedure,
    )
    from modules.clinics.service_dental_platform import (
        complete_session,
        create_session,
        list_sessions,
        update_session,
    )

    data = _setup()
    first = create_session(1, data["item"]["id"], {"visit_id": data["visit"]["id"]})
    second = create_session(1, data["item"]["id"], {"visit_id": data["visit"]["id"]})
    assert update_session(1, first["id"], {"status": "in_progress"})["started_at"]
    done_first = complete_session(1, first["id"], {"visit_id": data["visit"]["id"]})
    first_vp = done_first["visit_procedure_id"]
    assert ClinicVisitProcedure.query.filter_by(tenant_id=1).count() == 1
    repeated = complete_session(1, first["id"], {"visit_id": data["visit"]["id"]})
    assert repeated["visit_procedure_id"] == first_vp
    assert ClinicVisitProcedure.query.filter_by(tenant_id=1).count() == 1
    assert db.session.get(ClinicDentalTreatmentPlanItem, data["item"]["id"]).status == "in_progress"

    complete_session(1, second["id"], {"visit_id": data["visit"]["id"]})
    assert ClinicVisitProcedure.query.filter_by(tenant_id=1).count() == 2
    assert db.session.get(ClinicDentalTreatmentPlanItem, data["item"]["id"]).status == "completed"
    assert db.session.get(ClinicDentalTreatmentPlan, data["plan"]["id"]).status == "completed"
    assert list_sessions(1, item_id=data["item"]["id"])["next_session"] is None


def test_appointment_keeps_plan_item_session_and_multi_tooth_context(clinic_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicAppointment
    from modules.clinics.service_dental_platform import create_session, update_session

    data = _setup()
    session = create_session(1, data["item"]["id"], {"status": "planned"})
    appointment = service.create_appointment(
        1,
        {
            "patient_id": data["patient"]["id"],
            "doctor_id": data["doctor"]["id"],
            "appointment_date": date.today().isoformat(),
            "start_time": "12:00",
            "treatment_plan_id": data["plan"]["id"],
            "treatment_plan_item_id": data["item"]["id"],
            "dental_session_id": session["id"],
            "tooth_numbers": ["16", "15"],
        },
    )
    update_session(1, session["id"], {"appointment_id": appointment["id"], "status": "scheduled"})
    row = db.session.get(ClinicAppointment, appointment["id"])
    assert row.treatment_plan_id == data["plan"]["id"]
    assert row.treatment_plan_item_id == data["item"]["id"]
    assert row.dental_session_id == session["id"]
    assert row.tooth_number == "16"
    assert '"15"' in row.tooth_numbers_json


def test_session_cancellation_requires_reason_and_keeps_audit_context(clinic_db):
    from modules.clinics.models import ClinicAuditLog, ClinicDentalSession
    from modules.clinics.service_dental_platform import cancel_session, create_session

    data = _setup()
    session = create_session(1, data["item"]["id"], {"status": "planned"})
    with pytest.raises(ValueError, match="سبب إلغاء"):
        cancel_session(1, session["id"], actor_id=77, payload={})
    cancelled = cancel_session(
        1,
        session["id"],
        actor_id=77,
        payload={"cancellation_reason": "تعذر حضور المريض"},
    )
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancellation_reason"] == "تعذر حضور المريض"
    assert db.session.get(ClinicDentalSession, session["id"]).cancelled_by == 77
    assert ClinicAuditLog.query.filter_by(
        tenant_id=1,
        entity_type="dental_session",
        entity_id=session["id"],
        action="cancel",
    ).count() == 1


def test_full_dental_return_visit_cycle_uses_shared_ledgers(clinic_db):
    from modules.clinics import service
    from modules.clinics.models import (
        ClinicDentalTreatmentPlan,
        ClinicDentalTreatmentPlanItem,
        ClinicInvoice,
        ClinicPayment,
    )
    from modules.clinics.service_dental_completion import create_invoice_from_treatment_plan
    from modules.clinics.service_dental_platform import complete_session, create_session, list_sessions, update_session

    data = _setup(estimated_sessions=3)
    session1 = create_session(1, data["item"]["id"], {"visit_id": data["visit"]["id"], "status": "in_progress"})
    first = complete_session(1, session1["id"], {"visit_id": data["visit"]["id"]})
    session2 = first["next_session"]
    assert session2 and session2["session_number"] == 2

    invoice = create_invoice_from_treatment_plan(
        1, data["plan"]["id"], {"mode": "full", "visit_id": data["visit"]["id"]}
    )
    paid = service.receive_payment(1, invoice["id"], {"amount": 40, "method": "cash"})
    assert paid["paid"] == 40
    assert paid["balance"] == 60
    assert ClinicInvoice.query.filter_by(tenant_id=1).count() == 1
    assert ClinicPayment.query.filter_by(tenant_id=1).count() == 1

    appointment = service.create_appointment(
        1,
        {
            "patient_id": data["patient"]["id"],
            "doctor_id": data["doctor"]["id"],
            "appointment_date": date.today().isoformat(),
            "start_time": "14:00",
            "treatment_plan_id": data["plan"]["id"],
            "treatment_plan_item_id": data["item"]["id"],
            "dental_session_id": session2["id"],
            "tooth_number": "16",
        },
    )
    update_session(1, session2["id"], {"appointment_id": appointment["id"], "status": "scheduled"})
    service.complete_visit(1, data["visit"]["id"], auto_invoice=False)
    assert db.session.get(ClinicDentalTreatmentPlanItem, data["item"]["id"]).status == "in_progress"

    visit2 = service.start_visit_from_appointment(1, appointment["id"])
    complete_session(1, session2["id"], {"visit_id": visit2["id"]})
    session3 = list_sessions(1, item_id=data["item"]["id"])["next_session"]
    visit3 = service.create_walkin_visit(
        1, {"patient_id": data["patient"]["id"], "doctor_id": data["doctor"]["id"]}
    )
    complete_session(1, session3["id"], {"visit_id": visit3["id"]})
    assert db.session.get(ClinicDentalTreatmentPlanItem, data["item"]["id"]).status == "completed"
    assert db.session.get(ClinicDentalTreatmentPlan, data["plan"]["id"]).status == "completed"


def test_session_reuses_existing_visit_procedure_without_duplicate(clinic_db):
    from modules.clinics.models import ClinicVisitProcedure
    from modules.clinics.service_dental_platform import complete_session, create_session
    from modules.clinics.service_ops import add_visit_procedure

    data = _setup(estimated_sessions=1)
    procedure_rows = add_visit_procedure(
        1, data["visit"]["id"], {"procedure_id": data["procedure"].id, "price": 125}
    )
    vp_id = procedure_rows[0]["id"]
    session = create_session(1, data["item"]["id"], {"visit_id": data["visit"]["id"]})
    result = complete_session(
        1,
        session["id"],
        {"visit_id": data["visit"]["id"], "visit_procedure_id": vp_id},
    )
    assert result["visit_procedure_id"] == vp_id
    assert ClinicVisitProcedure.query.filter_by(tenant_id=1).count() == 1
    assert db.session.get(ClinicVisitProcedure, vp_id).status == "completed"


def test_session_completion_consumes_procedure_recipe_once(clinic_db):
    from decimal import Decimal

    from modules.clinics.models import (
        ClinicInventoryItem,
        ClinicInventoryMovement,
        ClinicProcedureRecipeItem,
    )
    from modules.clinics.service_dental_platform import complete_session, create_session
    from modules.clinics.service_ops import create_inventory_item

    data = _setup(estimated_sessions=1)
    stock = create_inventory_item(
        1,
        {
            "name": "مادة علاج عصب",
            "sku": "DENTAL-ROOT-1",
            "purchase_price": 10,
            "selling_price": 10,
            "current_stock": 2,
        },
    )
    data["procedure"].consumes_inventory = True
    db.session.add(
        ClinicProcedureRecipeItem(
            tenant_id=1,
            procedure_id=data["procedure"].id,
            item_id=stock["id"],
            quantity=Decimal("1"),
        )
    )
    session = create_session(1, data["item"]["id"], {"visit_id": data["visit"]["id"]})
    completed = complete_session(1, session["id"], {"visit_id": data["visit"]["id"]})
    complete_session(1, session["id"], {"visit_id": data["visit"]["id"]})
    assert ClinicInventoryMovement.query.filter_by(
        tenant_id=1,
        reference_type="visit_procedure",
        reference_id=completed["visit_procedure_id"],
    ).count() == 1
    assert float(db.session.get(ClinicInventoryItem, stock["id"]).current_stock) == 1


def test_dental_image_metadata_filters_soft_delete_and_tenant_isolation(clinic_db):
    from modules.clinics.models import ClinicAttachment
    from modules.clinics.service_dental_platform import (
        create_image_metadata,
        delete_image_metadata,
        list_images,
    )

    data = _setup()
    attachment = ClinicAttachment(
        tenant_id=1,
        patient_id=data["patient"]["id"],
        visit_id=data["visit"]["id"],
        category="radiology",
        file_name="tooth.png",
        stored_name="shared-store.png",
        mime_type="image/png",
        size_bytes=10,
    )
    db.session.add(attachment)
    db.session.flush()
    image = create_image_metadata(
        1,
        {
            "attachment_id": attachment.id,
            "image_type": "xray",
            "tooth_number": "16",
            "treatment_plan_item_id": data["item"]["id"],
        },
    )
    assert list_images(1, {"patient_id": data["patient"]["id"], "image_type": "xray"})[0]["id"] == image["id"]
    assert list_images(2, {}) == []
    with pytest.raises(ValueError, match="المرفق"):
        create_image_metadata(2, {"attachment_id": attachment.id})
    delete_image_metadata(1, image["id"])
    assert list_images(1, {}) == []
    assert list_images(1, {"include_deleted": "1"})[0]["archived"] is True
    assert db.session.get(ClinicAttachment, attachment.id) is not None


def test_dental_reports_use_existing_items_and_execution_links(clinic_db):
    from modules.clinics.service_dental_platform import (
        complete_session,
        create_session,
        dental_reports,
    )

    data = _setup(estimated_sessions=2)
    initial = dental_reports(1)
    assert initial["overview"]["pending_treatment_count"] == 1
    assert initial["overview"]["execution_count"] == 0
    assert initial["pending_treatments"][0]["item_id"] == data["item"]["id"]
    session = create_session(1, data["item"]["id"], {"visit_id": data["visit"]["id"]})
    complete_session(1, session["id"], {"visit_id": data["visit"]["id"]})
    after = dental_reports(1, patient_id=data["patient"]["id"])
    assert after["overview"]["execution_count"] == 1
    assert after["overview"]["pending_treatment_count"] == 1
    assert dental_reports(2)["overview"]["treatment_count"] == 0


def test_tooth_events_are_append_only_and_tenant_scoped(clinic_db):
    from modules.clinics.service_dental import upsert_tooth_finding
    from modules.clinics.service_dental_completion import list_tooth_events

    data = _setup()
    upsert_tooth_finding(1, data["visit"]["id"], "16", {"status": "caries", "surfaces": ["occlusal"]})
    upsert_tooth_finding(1, data["visit"]["id"], "16", {"status": "root_canal", "surfaces": ["occlusal"]})
    events = list_tooth_events(1, data["patient"]["id"], "16")
    assert [row["condition_code"] for row in events] == ["root_canal", "caries"]
    assert list_tooth_events(2, data["patient"]["id"]) == []


def test_service_requires_tooth_and_appointment_duration(clinic_db):
    from datetime import date

    from modules.clinics import service
    from modules.clinics.service_dental_completion import seed_dental_services
    from modules.clinics.service_dental_treatment import add_plan_item

    data = _setup()
    seed_dental_services(1)
    root = next(row for row in service.list_services(1) if row["name"] == "علاج عصب")
    assert root["requires_tooth"] is True
    assert root["requires_sessions"] is True
    assert root["default_sessions"] == 3
    assert root["duration_minutes"] == 45
    assert root["default_procedure_id"]
    saved = db.session.get(__import__("modules.clinics.models", fromlist=["ClinicService"]).ClinicService, root["id"])
    saved.price = 123456
    saved.default_sessions = 5
    seed_dental_services(1)
    reseeded = next(row for row in service.list_services(1) if row["id"] == root["id"])
    assert reseeded["price"] == 123456
    assert reseeded["default_sessions"] == 5
    mapped = add_plan_item(
        1, data["plan"]["id"],
        {"service_id": root["id"], "tooth_number": "26"},
    )
    mapped_item = next(item for item in mapped["items"] if item["service_id"] == root["id"])
    assert mapped_item["procedure_id"] == root["default_procedure_id"]
    assert mapped_item["estimated_sessions"] == 5
    with pytest.raises(ValueError, match="السن"):
        service.create_appointment(
            1,
            {
                "patient_id": data["patient"]["id"],
                "doctor_id": data["doctor"]["id"],
                "service_id": root["id"],
                "appointment_date": date.today().isoformat(),
                "start_time": "11:00",
            },
        )
    appointment = service.create_appointment(
        1,
        {
            "patient_id": data["patient"]["id"],
            "doctor_id": data["doctor"]["id"],
            "service_id": root["id"],
            "tooth_number": "16",
            "treatment_plan_item_id": data["item"]["id"],
            "appointment_date": date.today().isoformat(),
            "start_time": "11:00",
        },
    )
    assert appointment["tooth_number"] == "16"
    assert appointment["treatment_plan_item_id"] == data["item"]["id"]
    assert appointment["end_time"] == "11:45"


def test_invoice_from_plan_and_complete_preflight(clinic_db):
    from modules.clinics.models import ClinicInvoice
    from modules.clinics.service_dental_completion import (
        create_invoice_from_treatment_plan,
        visit_complete_preflight,
    )
    from modules.clinics.service_dental_platform import create_session

    data = _setup()
    create_session(1, data["item"]["id"], {"visit_id": data["visit"]["id"]})
    preflight = visit_complete_preflight(1, data["visit"]["id"])
    assert preflight["can_complete"] is True
    assert preflight["open_session_count"] == 1
    assert preflight["has_invoice"] is False
    invoice = create_invoice_from_treatment_plan(
        1, data["plan"]["id"], {"mode": "full", "visit_id": data["visit"]["id"]}
    )
    assert invoice["treatment_plan_id"] == data["plan"]["id"]
    assert invoice["total"] == 100
    assert ClinicInvoice.query.filter_by(tenant_id=1).count() == 1
    with pytest.raises(ValueError):
        create_invoice_from_treatment_plan(2, data["plan"]["id"], {"mode": "full"})

