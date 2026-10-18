"""Phase F — Internal Medicine longitudinal clinical tools."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import event

from extensions import db


@pytest.fixture()
def specialty_db():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        SECRET_KEY="im-test",
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


def _im_setup(tenant_id=1):
    from modules.clinics import service
    from modules.clinics.service_specialties import seed_default_specialties

    specialties = seed_default_specialties(tenant_id)
    im = next(row for row in specialties if row["code"] == "internal_medicine")
    doctor = service.create_doctor(
        tenant_id,
        {"full_name": "د. باطنية", "primary_specialty_id": im["id"], "specialty_ids": [im["id"]]},
    )
    patient = service.create_patient(
        tenant_id,
        {"full_name": "مريض مزمن", "date_of_birth": date(1980, 3, 10).isoformat()},
    )
    visit = service.create_walkin_visit(
        tenant_id,
        {"patient_id": patient["id"], "doctor_id": doctor["id"], "specialty_id": im["id"]},
    )
    return im, doctor, patient, visit


def test_schema_v25_and_models():
    from modules.clinics.models import ClinicChronicCondition, ClinicPatientMedication, CLINIC_MODELS
    from modules.clinics.schema import SCHEMA_VERSION

    assert SCHEMA_VERSION.startswith("clinics-v")
    major = int(SCHEMA_VERSION.split("-")[1].lstrip("v"))
    assert major >= 25
    assert ClinicChronicCondition in CLINIC_MODELS
    assert ClinicPatientMedication in CLINIC_MODELS


def test_chronic_condition_crud_and_archive(specialty_db):
    from modules.clinics.service_internal_medicine import (
        create_chronic_condition,
        list_chronic_conditions,
        update_chronic_condition,
    )

    with specialty_db.app_context():
        _, doctor, patient, _ = _im_setup()
        created = create_chronic_condition(
            1,
            patient["id"],
            {
                "condition_code": "diabetes",
                "condition_name": "السكري",
                "status": "active",
                "severity": "moderate",
                "diagnosis_date": "2020-01-15",
            },
            actor_id=1,
            doctor_id=doctor["id"],
        )
        assert len(created["active"]) == 1
        assert created["active"][0]["condition_code"] == "diabetes"

        create_chronic_condition(
            1,
            patient["id"],
            {"condition_code": "hypertension", "status": "controlled", "condition_name": "ضغط"},
            actor_id=1,
            doctor_id=doctor["id"],
        )
        create_chronic_condition(
            1,
            patient["id"],
            {"condition_code": "other", "condition_name": "التهاب مفاصل مزمن", "status": "active"},
            actor_id=1,
        )
        listed = list_chronic_conditions(1, patient["id"])
        assert len(listed["items"]) == 3
        assert len(listed["active"]) == 3

        cond_id = listed["items"][0]["id"]
        updated = update_chronic_condition(
            1, cond_id, {"status": "resolved", "notes": "محلول"}, actor_id=1
        )
        resolved = next(c for c in updated["items"] if c["id"] == cond_id)
        assert resolved["status"] == "resolved"
        assert resolved["notes"] == "محلول"

        archived = update_chronic_condition(1, cond_id, {"archive": True}, actor_id=1)
        assert all(c["id"] != cond_id for c in archived["items"])


def test_promote_diagnosis_to_chronic(specialty_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicDiagnosis
    from modules.clinics.service_internal_medicine import promote_diagnosis_to_chronic

    with specialty_db.app_context():
        _, doctor, patient, visit = _im_setup()
        service.add_diagnosis(1, visit["id"], {"title": "داء سكري من النمط 2", "code": "E11"}, actor_id=1)
        diag = ClinicDiagnosis.query.filter_by(tenant_id=1, patient_id=patient["id"]).first()
        result = promote_diagnosis_to_chronic(
            1,
            patient["id"],
            diag.id,
            {"condition_code": "diabetes"},
            actor_id=1,
            doctor_id=doctor["id"],
        )
        assert any(c["linked_diagnosis_id"] == diag.id for c in result["items"])
        assert any(c["source"] == "diagnosis_promote" for c in result["items"])


def test_medications_and_prescription_history(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_internal_medicine import list_patient_medications, upsert_patient_medication

    with specialty_db.app_context():
        _, doctor, patient, visit = _im_setup()
        service.save_prescription(
            1,
            visit["id"],
            {"items": [{"medicine_name": "ميتفورمين", "dosage": "500mg", "frequency": "مرتين"}]},
            actor_id=1,
        )
        upsert_patient_medication(
            1,
            patient["id"],
            {
                "drug_name": "ميتفورمين",
                "dose_text": "500mg",
                "frequency": "مرتين",
                "status": "active",
            },
            actor_id=1,
            doctor_id=doctor["id"],
        )
        meds = list_patient_medications(1, patient["id"])
        assert len(meds["active"]) == 1
        assert meds["prescription_history"]
        assert meds["prescription_history"][0]["medicine_name"] == "ميتفورمين"

        mid = meds["active"][0]["id"]
        stopped = upsert_patient_medication(
            1,
            patient["id"],
            {"status": "stopped", "end_date": date.today().isoformat()},
            actor_id=1,
            medication_id=mid,
        )
        assert stopped["active"] == []
        assert any(m["status"] == "stopped" for m in stopped["items"])


def test_vital_trends_parse_bp(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_internal_medicine import get_vital_trends

    with specialty_db.app_context():
        im, doctor, patient, visit = _im_setup()
        service.save_vitals(
            1,
            visit["id"],
            {"blood_pressure": "130/85", "weight_kg": 82, "blood_glucose": 140},
            actor_id=1,
        )
        visit2 = service.create_walkin_visit(
            1,
            {"patient_id": patient["id"], "doctor_id": doctor["id"], "specialty_id": im["id"]},
        )
        service.save_vitals(
            1,
            visit2["id"],
            {"blood_pressure": "125/80", "weight_kg": 81},
            actor_id=1,
        )
        trends = get_vital_trends(1, patient["id"], "6m")
        assert trends["latest"]["systolic"] == 125
        assert trends["latest"]["diastolic"] == 80
        assert len(trends["series"]["systolic"]) == 2
        assert trends["auto_labels"] is False


def test_lab_trends_no_unit_conversion(specialty_db):
    from modules.clinics.service_internal_medicine import get_lab_trends
    from modules.clinics.service_ops import create_lab_order, create_lab_test, update_lab_result

    with specialty_db.app_context():
        _, doctor, patient, visit = _im_setup()
        test = create_lab_test(1, {"name": "HbA1c", "code": "HBA1C"})
        order = create_lab_order(
            1,
            {
                "patient_id": patient["id"],
                "doctor_id": doctor["id"],
                "visit_id": visit["id"],
                "test_ids": [test["id"]],
            },
        )
        item_id = order["items"][0]["id"]
        update_lab_result(1, item_id, {"value": "7.2", "unit": "%"}, actor_id=1)
        trends = get_lab_trends(1, patient["id"], analytes=["hba1c"], range_key="1y")
        assert "hba1c" in trends["latest"]
        assert trends["latest"]["hba1c"]["value"] == 7.2
        assert trends["unit_conversion"] is False
        assert "%" in trends["series"]["hba1c"]


def test_visit_comparison(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_internal_medicine import compare_visits

    with specialty_db.app_context():
        im, doctor, patient, visit = _im_setup()
        service.save_vitals(1, visit["id"], {"blood_pressure": "140/90"}, actor_id=1)
        service.add_diagnosis(1, visit["id"], {"title": "ارتفاع ضغط"}, actor_id=1)
        visit2 = service.create_walkin_visit(
            1,
            {"patient_id": patient["id"], "doctor_id": doctor["id"], "specialty_id": im["id"]},
        )
        service.save_vitals(1, visit2["id"], {"blood_pressure": "130/85"}, actor_id=1)
        service.save_prescription(
            1,
            visit2["id"],
            {"items": [{"medicine_name": "أملوديبين", "dosage": "5mg"}]},
            actor_id=1,
        )
        cmp = compare_visits(1, patient["id"], [visit["id"], visit2["id"]])
        assert len(cmp["visits"]) == 2
        assert cmp["visits"][0]["diagnoses"]
        assert cmp["visits"][1]["medications"]
        with pytest.raises(ValueError):
            compare_visits(1, patient["id"], [visit["id"]])


def test_internal_medicine_context_and_packs(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_internal_medicine import (
        create_chronic_condition,
        get_internal_medicine_context,
        get_visit_internal_medicine_context,
    )
    from modules.clinics.service_ops import create_lab_order, create_lab_test, update_lab_result

    with specialty_db.app_context():
        _, doctor, patient, visit = _im_setup()
        create_chronic_condition(
            1,
            patient["id"],
            {"condition_code": "diabetes", "condition_name": "السكري", "status": "active"},
            actor_id=1,
        )
        create_chronic_condition(
            1,
            patient["id"],
            {"condition_code": "hypertension", "condition_name": "ضغط", "status": "active"},
            actor_id=1,
        )
        service.save_vitals(1, visit["id"], {"blood_pressure": "128/82", "blood_glucose": 110}, actor_id=1)
        test = create_lab_test(1, {"name": "سكر تراكمي", "code": "A1C"})
        order = create_lab_order(
            1,
            {
                "patient_id": patient["id"],
                "doctor_id": doctor["id"],
                "visit_id": visit["id"],
                "test_ids": [test["id"]],
            },
        )
        update_lab_result(1, order["items"][0]["id"], {"value": "6.8", "unit": "%"}, actor_id=1)
        ctx = get_internal_medicine_context(1, patient["id"], visit_id=visit["id"])
        assert ctx["risk_scoring_available"] is False
        assert ctx["auto_recommendations"] is False
        codes = {p["condition_code"] for p in ctx["disease_packs"]}
        assert "diabetes" in codes
        assert "hypertension" in codes
        assert "hba1c" in (ctx["important_recent_labs"] or {})
        vctx = get_visit_internal_medicine_context(1, visit["id"])
        assert vctx["patient_id"] == patient["id"]


def test_tenant_isolation(specialty_db):
    from modules.clinics.service_internal_medicine import create_chronic_condition, get_internal_medicine_context

    with specialty_db.app_context():
        _, doctor, patient, _ = _im_setup(1)
        create_chronic_condition(
            1,
            patient["id"],
            {"condition_code": "asthma", "condition_name": "ربو", "status": "active"},
            actor_id=1,
            doctor_id=doctor["id"],
        )
        with pytest.raises(ValueError):
            get_internal_medicine_context(2, patient["id"])
        with pytest.raises(ValueError):
            create_chronic_condition(2, patient["id"], {"condition_code": "asthma"}, actor_id=1)


def test_context_query_bound(specialty_db):
    from modules.clinics.service_internal_medicine import create_chronic_condition, get_internal_medicine_context

    with specialty_db.app_context():
        _, doctor, patient, visit = _im_setup()
        for code in ("diabetes", "hypertension", "thyroid_disease"):
            create_chronic_condition(
                1,
                patient["id"],
                {"condition_code": code, "condition_name": code, "status": "active"},
                actor_id=1,
                doctor_id=doctor["id"],
            )
        queries = []

        def before_cursor(conn, cursor, statement, parameters, context, executemany):
            queries.append(statement)

        event.listen(db.engine, "before_cursor_execute", before_cursor)
        try:
            ctx = get_internal_medicine_context(1, patient["id"], visit_id=visit["id"])
        finally:
            event.remove(db.engine, "before_cursor_execute", before_cursor)
        assert ctx["disease_packs"]
        assert len(queries) < 45


def test_no_sidebar_clutter_for_im():
    html = Path("templates/clinics/workspace.html").read_text(encoding="utf-8")
    assert "internal-medicine-tools.js" in html
    assert 'data-nav-key="diabetes"' not in html
    assert 'data-nav-key="chronic"' not in html
    js = Path("static/clinics/clinics.js").read_text(encoding="utf-8")
    assert 'data-tab="internal"' in js
    assert "internal_medicine" in js
    profile = Path("static/clinics/patient-profile.js").read_text(encoding="utf-8")
    assert "internal_medicine" in profile


def test_migration_idempotent_models_present(specialty_db):
    from modules.clinics.models import ClinicChronicCondition, ClinicPatientMedication
    from modules.clinics.schema import ensure_clinics_schema

    with specialty_db.app_context():
        ensure_clinics_schema()
        ensure_clinics_schema()
        assert ClinicChronicCondition.__tablename__ == "clinic_chronic_condition"
        assert ClinicPatientMedication.__tablename__ == "clinic_patient_medication"
        from modules.clinics.models import ClinicPregnancy, ClinicPediatricProfile

        assert ClinicPregnancy.__tablename__
        assert ClinicPediatricProfile.__tablename__