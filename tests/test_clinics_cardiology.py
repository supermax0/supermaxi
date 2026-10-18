"""Phase G — Cardiology clinical tools (reuses Phase F longitudinal engines)."""
from __future__ import annotations

from datetime import date
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
        SECRET_KEY="cardio-test",
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


def _cardio_setup(tenant_id=1):
    from modules.clinics import service
    from modules.clinics.service_specialties import seed_default_specialties

    specialties = seed_default_specialties(tenant_id)
    cardio = next(row for row in specialties if row["code"] == "cardiology")
    doctor = service.create_doctor(
        tenant_id,
        {"full_name": "د. قلب", "primary_specialty_id": cardio["id"], "specialty_ids": [cardio["id"]]},
    )
    patient = service.create_patient(
        tenant_id,
        {"full_name": "مريض قلبي", "date_of_birth": date(1975, 4, 1).isoformat(), "allergies": "أسبرين"},
    )
    visit = service.create_walkin_visit(
        tenant_id,
        {"patient_id": patient["id"], "doctor_id": doctor["id"], "specialty_id": cardio["id"]},
    )
    return cardio, doctor, patient, visit


def test_schema_v26_and_models():
    from modules.clinics.models import (
        CLINIC_MODELS,
        ClinicCardiologyECG,
        ClinicCardiologyEcho,
        ClinicCardiologyProfile,
    )
    from modules.clinics.schema import SCHEMA_VERSION

    assert SCHEMA_VERSION.startswith("clinics-v")
    assert ClinicCardiologyProfile in CLINIC_MODELS
    assert ClinicCardiologyECG in CLINIC_MODELS
    assert ClinicCardiologyEcho in CLINIC_MODELS


def test_cardiology_profile_and_tenant_isolation(specialty_db):
    from modules.clinics.service_cardiology import get_cardiology_profile, upsert_cardiology_profile

    with specialty_db.app_context():
        _, _, patient, _ = _cardio_setup()
        empty = get_cardiology_profile(1, patient["id"])
        assert empty["exists"] is False
        saved = upsert_cardiology_profile(
            1,
            patient["id"],
            {
                "smoking_status": "former",
                "family_cardiac_history": "أب احتشاء",
                "device_type": "pacemaker",
                "previous_mi_date": "2019-06-01",
            },
            actor_id=1,
        )
        assert saved["exists"] is True
        assert saved["smoking_status"] == "former"
        assert saved["device_type"] == "pacemaker"
        with pytest.raises(ValueError):
            get_cardiology_profile(2, patient["id"])
        with pytest.raises(ValueError):
            upsert_cardiology_profile(1, patient["id"], {"smoking_status": "heavy"}, actor_id=1)


def test_ecg_crud_archive_completed_visit(specialty_db):
    from modules.clinics.models import ClinicVisit
    from modules.clinics.service_cardiology import create_ecg, list_ecgs, update_ecg

    with specialty_db.app_context():
        _, doctor, patient, visit = _cardio_setup()
        created = create_ecg(
            1,
            patient["id"],
            {
                "visit_id": visit["id"],
                "heart_rate": 72,
                "rhythm": "sinus",
                "interpretation": "طبيعي نسبياً",
            },
            actor_id=1,
            doctor_id=doctor["id"],
        )
        assert created["items"]
        assert created["items"][0]["auto_interpretation"] is False
        ecg_id = created["items"][0]["id"]
        updated = update_ecg(1, ecg_id, {"qtc_ms": 420, "notes": "مراجعة"}, actor_id=1)
        assert updated["items"][0]["qtc_ms"] == 420

        row = ClinicVisit.query.get(visit["id"])
        row.status = "completed"
        db.session.flush()
        with pytest.raises(ValueError, match="مكتملة"):
            create_ecg(1, patient["id"], {"visit_id": visit["id"], "rhythm": "af"}, actor_id=1)

        # new open visit can still archive older ECG via direct update if visit was open — reopen guard:
        # archive without visit restriction when original visit completed: update checks visit
        with pytest.raises(ValueError, match="مكتملة"):
            update_ecg(1, ecg_id, {"archive": True}, actor_id=1)

        # patient-level list still works
        hist = list_ecgs(1, patient["id"])
        assert len(hist["items"]) == 1


def test_echo_and_lvef_no_auto_class(specialty_db):
    from modules.clinics.service_cardiology import create_echo, update_echo

    with specialty_db.app_context():
        _, doctor, patient, visit = _cardio_setup()
        created = create_echo(
            1,
            patient["id"],
            {"visit_id": visit["id"], "lvef_percent": 55, "impression": "وظيفة محفوظة نسبياً"},
            actor_id=1,
            doctor_id=doctor["id"],
        )
        assert created["items"][0]["lvef_percent"] == 55
        assert created["items"][0]["auto_classification"] is False
        with pytest.raises(ValueError):
            create_echo(1, patient["id"], {"lvef_percent": 140}, actor_id=1)
        echo_id = created["items"][0]["id"]
        archived = update_echo(1, echo_id, {"archive": True}, actor_id=1)
        assert archived["items"] == []


def test_condition_and_med_reuse(specialty_db):
    from modules.clinics.service_cardiology import get_cardiology_context
    from modules.clinics.service_internal_medicine import create_chronic_condition, upsert_patient_medication

    with specialty_db.app_context():
        _, doctor, patient, visit = _cardio_setup()
        create_chronic_condition(
            1,
            patient["id"],
            {"condition_code": "coronary_artery_disease", "condition_name": "CAD", "status": "active"},
            actor_id=1,
            doctor_id=doctor["id"],
        )
        create_chronic_condition(
            1,
            patient["id"],
            {"condition_code": "hypertension", "condition_name": "ضغط", "status": "active"},
            actor_id=1,
        )
        upsert_patient_medication(
            1,
            patient["id"],
            {"drug_name": "أسبرين", "dose_text": "100mg", "status": "active"},
            actor_id=1,
            doctor_id=doctor["id"],
        )
        ctx = get_cardiology_context(1, patient["id"], visit_id=visit["id"])
        codes = {c["condition_code"] for c in ctx["conditions"]["items"]}
        assert "coronary_artery_disease" in codes
        assert ctx["medications"]["active"]
        assert ctx["engines"]["conditions"] == "ClinicChronicCondition"
        assert ctx["engines"]["medications"] == "ClinicPatientMedication"
        assert ctx["risk_scoring_available"] is False
        assert any(f["code"] == "known_cad" and f["present"] for f in ctx["risk_factors"])
        assert any(f["code"] == "hypertension" and f["present"] for f in ctx["risk_factors"])


def test_trend_engine_reuse(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_cardiology import get_cardiology_context
    from modules.clinics.service_internal_medicine import get_vital_trends

    with specialty_db.app_context():
        _, doctor, patient, visit = _cardio_setup()
        service.save_vitals(
            1, visit["id"], {"blood_pressure": "135/85", "heart_rate": 78, "weight_kg": 90}, actor_id=1
        )
        trends = get_vital_trends(1, patient["id"], "6m")
        ctx = get_cardiology_context(1, patient["id"])
        assert ctx["engines"]["vital_trends"].endswith("get_vital_trends")
        assert ctx["summary"]["latest_bp"] == trends["latest"]["blood_pressure"]
        assert "systolic" in (ctx["vital_trends_summary"]["preset"] or [])


def test_visit_comparison_attaches_ecg_echo(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_cardiology import cardiology_visit_comparison, create_ecg, create_echo

    with specialty_db.app_context():
        cardio, doctor, patient, visit = _cardio_setup()
        visit2 = service.create_walkin_visit(
            1, {"patient_id": patient["id"], "doctor_id": doctor["id"], "specialty_id": cardio["id"]}
        )
        create_ecg(1, patient["id"], {"visit_id": visit["id"], "rhythm": "sinus"}, actor_id=1)
        create_echo(1, patient["id"], {"visit_id": visit2["id"], "lvef_percent": 48}, actor_id=1)
        cmp = cardiology_visit_comparison(1, patient["id"], [visit["id"], visit2["id"]])
        assert cmp["engine"].endswith("compare_visits")
        assert cmp["visits"][0]["ecg"]["rhythm"] == "sinus"
        assert cmp["visits"][1]["echo"]["lvef_percent"] == 48


def test_context_query_bound(specialty_db):
    from modules.clinics.service_cardiology import create_ecg, create_echo, get_cardiology_context, upsert_cardiology_profile
    from modules.clinics.service_internal_medicine import create_chronic_condition

    with specialty_db.app_context():
        _, doctor, patient, visit = _cardio_setup()
        upsert_cardiology_profile(1, patient["id"], {"smoking_status": "current"}, actor_id=1)
        create_chronic_condition(
            1, patient["id"], {"condition_code": "heart_failure", "status": "active"}, actor_id=1
        )
        for i in range(3):
            create_ecg(1, patient["id"], {"visit_id": visit["id"], "rhythm": f"r{i}"}, actor_id=1, doctor_id=doctor["id"])
            create_echo(1, patient["id"], {"visit_id": visit["id"], "lvef_percent": 50 + i}, actor_id=1)
        queries = []

        def before_cursor(conn, cursor, statement, parameters, context, executemany):
            queries.append(statement)

        event.listen(db.engine, "before_cursor_execute", before_cursor)
        try:
            ctx = get_cardiology_context(1, patient["id"], visit_id=visit["id"])
        finally:
            event.remove(db.engine, "before_cursor_execute", before_cursor)
        assert ctx["recent_ecgs"]
        assert len(queries) < 50


def test_cardiology_template_seeded(specialty_db):
    from modules.clinics.models import ClinicVisitTemplate
    from modules.clinics.service_specialties import seed_default_specialties

    with specialty_db.app_context():
        specs = seed_default_specialties(1)
        cardio = next(s for s in specs if s["code"] == "cardiology")
        tpl = ClinicVisitTemplate.query.filter_by(tenant_id=1, specialty_id=cardio["id"]).first()
        assert tpl is not None
        assert tpl.is_active


def test_no_sidebar_clutter_cardio():
    html = Path("templates/clinics/workspace.html").read_text(encoding="utf-8")
    assert "cardiology-tools.js" in html
    nav = Path("static/clinics/nav.js").read_text(encoding="utf-8")
    assert 'data-nav-key="ecg"' not in nav
    assert "Cardiac Risk" not in html
    js = Path("static/clinics/clinics.js").read_text(encoding="utf-8")
    assert 'data-tab="cardiology"' in js
    profile = Path("static/clinics/patient-profile.js").read_text(encoding="utf-8")
    assert "cardiology" in profile


def test_migration_idempotent(specialty_db):
    from modules.clinics.models import ClinicCardiologyECG, ClinicChronicCondition, ClinicPregnancy
    from modules.clinics.schema import ensure_clinics_schema

    with specialty_db.app_context():
        ensure_clinics_schema()
        ensure_clinics_schema()
        assert ClinicCardiologyECG.__tablename__
        assert ClinicChronicCondition.__tablename__
        assert ClinicPregnancy.__tablename__
