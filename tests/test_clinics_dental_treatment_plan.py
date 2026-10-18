"""Phase C — Dental Treatment Plan regression."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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
        SECRET_KEY="dental-tp-test",
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


def _dentistry_setup(tenant_id=1):
    from modules.clinics import service
    from modules.clinics.service_specialties import seed_default_specialties

    specialties = seed_default_specialties(tenant_id)
    dentistry = next(row for row in specialties if row["code"] == "dentistry")
    doctor = service.create_doctor(
        tenant_id,
        {
            "full_name": "د. أسنان",
            "primary_specialty_id": dentistry["id"],
            "specialty_ids": [dentistry["id"]],
        },
    )
    patient = service.create_patient(tenant_id, {"full_name": "مريض خطة"})
    visit = service.create_walkin_visit(
        tenant_id,
        {
            "patient_id": patient["id"],
            "doctor_id": doctor["id"],
            "specialty_id": dentistry["id"],
        },
    )
    return dentistry, doctor, patient, visit


def test_create_plan_items_tooth_and_general(specialty_db):
    from modules.clinics.models import ClinicProcedure
    from modules.clinics.service_dental_treatment import (
        add_plan_item,
        create_plan,
        list_patient_plans,
        update_plan_item,
    )

    with specialty_db.app_context():
        dentistry, doctor, patient, visit = _dentistry_setup()
        proc = ClinicProcedure(tenant_id=1, name="علاج عصب", price=150000, active=True)
        db.session.add(proc)
        db.session.flush()
        plan = create_plan(
            1,
            patient["id"],
            {
                "name": "خطة أسنان",
                "status": "active",
                "created_by_doctor_id": doctor["id"],
                "specialty_id": dentistry["id"],
                "source_visit_id": visit["id"],
            },
        )
        detail = add_plan_item(
            1,
            plan["plan"]["id"],
            {
                "tooth_number": "16",
                "procedure_id": proc.id,
                "priority": "high",
                "estimated_sessions": 3,
                "estimated_price": 300000,
            },
        )
        detail = add_plan_item(
            1,
            plan["plan"]["id"],
            {"title": "تنظيف كامل", "tooth_number": None, "estimated_price": 50000, "priority": "normal"},
        )
        assert detail["summary"]["item_count"] == 2
        assert detail["summary"]["estimated_total"] == 350000
        tooth = next(i for i in detail["items"] if i["tooth_number"] == "16")
        assert tooth["estimated_sessions"] == 3
        assert tooth["procedure_id"] == proc.id
        assert next(i for i in detail["items"] if i["tooth_number"] is None)["title"] == "تنظيف كامل"
        updated = update_plan_item(1, tooth["id"], {"priority": "urgent"})
        assert next(i for i in updated["items"] if i["id"] == tooth["id"])["priority"] == "urgent"
        listed = list_patient_plans(1, patient["id"])
        assert listed["active_plan"]["plan"]["id"] == plan["plan"]["id"]
        with pytest.raises(ValueError, match="غير صالح"):
            add_plan_item(1, plan["plan"]["id"], {"tooth_number": "99", "title": "x"})


def test_multi_visit_procedure_links_and_finance(specialty_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicInvoice, ClinicProcedure
    from modules.clinics.service_dental_treatment import (
        add_plan_item,
        create_plan,
        link_item_procedure,
        plan_detail,
    )
    from modules.clinics.service_ops import add_visit_procedure

    with specialty_db.app_context():
        dentistry, doctor, patient, visit1 = _dentistry_setup()
        proc = ClinicProcedure(tenant_id=1, name="علاج عصب", price=100000, active=True)
        db.session.add(proc)
        db.session.flush()
        plan = create_plan(
            1, patient["id"],
            {"status": "active", "created_by_doctor_id": doctor["id"], "specialty_id": dentistry["id"]},
        )
        detail = add_plan_item(
            1, plan["plan"]["id"],
            {"tooth_number": "16", "procedure_id": proc.id, "estimated_sessions": 3, "estimated_price": 300000},
        )
        item_id = detail["items"][0]["id"]

        prices = [100000, 120000, 80000]
        visits = [visit1]
        for price in prices[1:]:
            visits.append(
                service.create_walkin_visit(
                    1,
                    {
                        "patient_id": patient["id"],
                        "doctor_id": doctor["id"],
                        "specialty_id": dentistry["id"],
                    },
                )
            )
        for visit, price in zip(visits, prices):
            procs = add_visit_procedure(1, visit["id"], {"procedure_id": proc.id, "price": price})
            link_item_procedure(1, item_id, procs[0]["id"])
            inv = ClinicInvoice(
                tenant_id=1,
                patient_id=patient["id"],
                visit_id=visit["id"],
                doctor_id=doctor["id"],
                invoice_number=f"INV-{visit['id']}",
                subtotal=price,
                total=price,
                paid=price,
                balance=0,
                status="paid",
            )
            db.session.add(inv)
        db.session.flush()
        detail = plan_detail(1, plan["plan"]["id"], include_financial=True)
        item = detail["items"][0]
        assert item["actual_sessions"] == 3
        assert item["actual_billed"] == 300000
        assert item["paid"] == 300000
        assert len(item["executions"]) == 3
        # Linking again is idempotent
        link_item_procedure(1, item_id, item["executions"][0]["visit_procedure_id"])
        assert plan_detail(1, plan["plan"]["id"])["items"][0]["actual_sessions"] == 3


def test_complete_plan_requires_confirmation(specialty_db):
    from modules.clinics.service_dental_treatment import add_plan_item, create_plan, update_plan

    with specialty_db.app_context():
        _, doctor, patient, _ = _dentistry_setup()
        plan = create_plan(1, patient["id"], {"status": "active", "created_by_doctor_id": doctor["id"]})
        add_plan_item(1, plan["plan"]["id"], {"title": "حشوة", "tooth_number": "11"})
        with pytest.raises(ValueError, match="غير مكتمل"):
            update_plan(1, plan["plan"]["id"], {"status": "completed"})
        done = update_plan(1, plan["plan"]["id"], {"status": "completed", "confirm_incomplete": True})
        assert done["plan"]["status"] == "completed"


def test_tenant_isolation_treatment_plan(specialty_db):
    from modules.clinics.service_dental_treatment import create_plan, list_patient_plans, plan_detail

    with specialty_db.app_context():
        _, doctor, patient, _ = _dentistry_setup(1)
        plan = create_plan(1, patient["id"], {"status": "active", "created_by_doctor_id": doctor["id"]})
        with pytest.raises(ValueError):
            plan_detail(2, plan["plan"]["id"])
        with pytest.raises(ValueError):
            list_patient_plans(2, patient["id"])


def test_financial_redaction_without_billing_flag(specialty_db):
    from modules.clinics.models import ClinicProcedure
    from modules.clinics.service_dental_treatment import add_plan_item, create_plan, plan_detail

    with specialty_db.app_context():
        _, doctor, patient, _ = _dentistry_setup()
        proc = ClinicProcedure(tenant_id=1, name="حشوة", price=25000, active=True)
        db.session.add(proc)
        db.session.flush()
        plan = create_plan(1, patient["id"], {"status": "active", "created_by_doctor_id": doctor["id"]})
        add_plan_item(1, plan["plan"]["id"], {"procedure_id": proc.id, "tooth_number": "21", "estimated_price": 25000})
        clinical = plan_detail(1, plan["plan"]["id"], include_financial=False)
        assert "estimated_price" not in clinical["items"][0]
        assert "discount" not in clinical["items"][0]
        assert "actual_billed" not in clinical["items"][0]
        assert "actual_billed" not in clinical["summary"]
        assert "estimated_total" not in clinical["summary"]


def test_options_acceptance_multi_teeth_and_cancellation_audit(specialty_db):
    from modules.clinics.service_dental_treatment import (
        accept_plan,
        add_plan_item,
        create_plan,
        create_treatment_option,
        update_plan_item,
    )

    with specialty_db.app_context():
        _, doctor, patient, _ = _dentistry_setup()
        plan = create_plan(1, patient["id"], {"status": "proposed", "created_by_doctor_id": doctor["id"]})
        detail = create_treatment_option(
            1, plan["plan"]["id"],
            {"title": "الخطة المحافظة", "is_recommended": True},
            actor_id=doctor["id"],
        )
        option = detail["options"][0]
        detail = add_plan_item(
            1, plan["plan"]["id"],
            {
                "title": "تنظيف عميق",
                "tooth_numbers": ["16", "15", "14"],
                "treatment_option_id": option["id"],
                "quantity": 3,
                "estimated_price": 100,
                "discount": 25,
            },
        )
        item = detail["items"][0]
        assert item["tooth_numbers"] == ["16", "15", "14"]
        assert detail["summary"]["estimated_total"] == 275
        accepted = accept_plan(
            1, plan["plan"]["id"],
            {"selected_option_id": option["id"], "acceptance_method": "verbal", "activate": True},
            actor_id=doctor["id"],
        )
        assert accepted["plan"]["status"] == "active"
        assert accepted["plan"]["accepted_at"]
        assert accepted["options"][0]["status"] == "selected"
        with pytest.raises(ValueError, match="سبب إلغاء"):
            update_plan_item(1, item["id"], {"status": "cancelled"}, actor_id=doctor["id"])
        cancelled = update_plan_item(
            1, item["id"],
            {"status": "cancelled", "cancellation_reason": "غيّر المريض رأيه"},
            actor_id=doctor["id"],
        )
        assert cancelled["items"][0]["cancellation_reason"] == "غيّر المريض رأيه"


def test_doctor_scope_blocks_foreign_plan(specialty_db, monkeypatch):
    from modules.clinics import guards, service
    from modules.clinics.models import ClinicDoctor
    from modules.clinics.service_dental_treatment import create_plan, plan_detail, update_plan_item, add_plan_item
    from modules.clinics.service_specialties import seed_default_specialties

    with specialty_db.app_context():
        specialties = seed_default_specialties(1)
        dentistry = next(row for row in specialties if row["code"] == "dentistry")
        doctors = [
            service.create_doctor(
                1,
                {
                    "full_name": name,
                    "primary_specialty_id": dentistry["id"],
                    "specialty_ids": [dentistry["id"]],
                },
            )
            for name in ("Own", "Other")
        ]
        patient = service.create_patient(1, {"full_name": "مشترك"})
        foreign = create_plan(
            1, patient["id"], {"status": "active", "created_by_doctor_id": doctors[1]["id"]}
        )
        add_plan_item(1, foreign["plan"]["id"], {"title": "خاص", "tooth_number": "16"})
        db.session.commit()

        employee = SimpleNamespace(
            id=10, role="doctor", is_active=True,
            has_permission=lambda key: key in {"clinics_clinical"},
        )
        monkeypatch.setattr(guards, "current_employee", lambda: employee)
        monkeypatch.setattr(guards, "current_tenant_id", lambda: 1)
        monkeypatch.setattr(guards, "is_clinics_tenant", lambda: True)
        monkeypatch.setattr(
            guards, "get_current_clinic_doctor", lambda: db.session.get(ClinicDoctor, doctors[0]["id"])
        )

        @guards.require_clinics("clinics_clinical", json_mode=True)
        def read_foreign():
            return plan_detail(1, foreign["plan"]["id"])

        with specialty_db.test_request_context("/clinics/api/dental-treatment-plans/x"):
            with pytest.raises(ValueError):
                read_foreign()


def test_archive_plan_keeps_links(specialty_db):
    from modules.clinics.models import ClinicDentalTreatmentPlan, ClinicProcedure
    from modules.clinics.service_dental_treatment import (
        add_plan_item,
        create_plan,
        link_item_procedure,
        plan_detail,
        update_plan,
    )
    from modules.clinics.service_ops import add_visit_procedure

    with specialty_db.app_context():
        dentistry, doctor, patient, visit = _dentistry_setup()
        proc = ClinicProcedure(tenant_id=1, name="قلع", price=40000, active=True)
        db.session.add(proc)
        db.session.flush()
        plan = create_plan(1, patient["id"], {"status": "active", "created_by_doctor_id": doctor["id"]})
        detail = add_plan_item(1, plan["plan"]["id"], {"procedure_id": proc.id, "tooth_number": "18"})
        procs = add_visit_procedure(1, visit["id"], {"procedure_id": proc.id})
        link_item_procedure(1, detail["items"][0]["id"], procs[0]["id"])
        update_plan(1, plan["plan"]["id"], {"status": "archived"})
        row = ClinicDentalTreatmentPlan.query.get(plan["plan"]["id"])
        assert row.archived_at is not None
        historical = plan_detail(1, plan["plan"]["id"])
        assert historical["items"][0]["actual_sessions"] == 1


def test_phase_b_dental_chart_still_works(specialty_db):
    from modules.clinics.service_dental import upsert_tooth_finding, get_visit_dental_chart

    with specialty_db.app_context():
        _, _, _, visit = _dentistry_setup()
        upsert_tooth_finding(1, visit["id"], "16", {"status": "caries", "surfaces": ["occlusal"]})
        chart = get_visit_dental_chart(1, visit["id"])
        assert any(t["tooth_number"] == "16" for t in chart["teeth"])


def test_schema_version_includes_dental_treatment_plan_models():
    from modules.clinics.models import ClinicDentalTreatmentPlan, ClinicDentalTreatmentPlanItem
    from modules.clinics.schema import SCHEMA_VERSION

    assert SCHEMA_VERSION.startswith("clinics-v")
    assert ClinicDentalTreatmentPlan.__tablename__ == "clinic_dental_treatment_plan"
    assert ClinicDentalTreatmentPlanItem.__tablename__ == "clinic_dental_treatment_plan_item"
