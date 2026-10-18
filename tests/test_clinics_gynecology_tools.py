"""Phase E — Gynecology & Obstetrics clinical tools."""
from __future__ import annotations

from datetime import date, datetime, timedelta

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
        SECRET_KEY="gyn-test",
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


def _gyn_setup(tenant_id=1):
    from modules.clinics import service
    from modules.clinics.service_specialties import seed_default_specialties

    specialties = seed_default_specialties(tenant_id)
    gyn = next(row for row in specialties if row["code"] == "obstetrics_gynecology")
    doctor = service.create_doctor(
        tenant_id,
        {"full_name": "د. نسائية", "primary_specialty_id": gyn["id"], "specialty_ids": [gyn["id"]]},
    )
    patient = service.create_patient(
        tenant_id,
        {"full_name": "مريضة تجريبية", "date_of_birth": date(1995, 5, 1).isoformat()},
    )
    visit = service.create_walkin_visit(
        tenant_id,
        {"patient_id": patient["id"], "doctor_id": doctor["id"], "specialty_id": gyn["id"]},
    )
    return gyn, doctor, patient, visit


def test_edd_and_gestational_age_helpers():
    from modules.clinics.service_gynecology import gestational_age_on, suggest_edd_from_lmp

    lmp = date(2024, 1, 1)
    assert suggest_edd_from_lmp(lmp) == date(2024, 10, 7)  # +280 days incl leap
    # leap year 2024: Jan 1 + 280 = Oct 7
    ga = gestational_age_on(date(2024, 6, 17), lmp=lmp)
    assert ga["weeks"] == 24
    assert ga["days"] == 0
    # leap year boundary
    lmp2 = date(2024, 2, 28)
    assert suggest_edd_from_lmp(lmp2) == date(2024, 12, 4)
    # from EDD alone
    edd = suggest_edd_from_lmp(lmp)
    ga2 = gestational_age_on(date(2024, 6, 17), edd=edd)
    assert ga2["weeks"] == ga["weeks"]


def test_gynecology_profile_and_tenant_isolation(specialty_db):
    from modules.clinics.service_gynecology import get_gynecology_profile, upsert_gynecology_profile

    with specialty_db.app_context():
        _, _, patient, _ = _gyn_setup()
        empty = get_gynecology_profile(1, patient["id"])
        assert empty["exists"] is False
        saved = upsert_gynecology_profile(
            1,
            patient["id"],
            {
                "menarche_age": 13,
                "cycle_regular": True,
                "cycle_length_days": 28,
                "last_menstrual_period": "2026-01-01",
                "gynecologic_history": "لا شيء",
            },
            actor_id=1,
        )
        assert saved["exists"] is True
        assert saved["menarche_age"] == 13
        db.session.commit()
        with pytest.raises(ValueError):
            get_gynecology_profile(2, patient["id"])
        with pytest.raises(ValueError, match="عمر الحيض"):
            upsert_gynecology_profile(1, patient["id"], {"menarche_age": 3})


def test_pregnancy_episodes_preserve_history(specialty_db):
    from modules.clinics.service_gynecology import (
        create_pregnancy,
        list_pregnancies,
        update_pregnancy,
    )

    with specialty_db.app_context():
        _, doctor, patient, _ = _gyn_setup()
        first = create_pregnancy(
            1,
            patient["id"],
            {
                "lmp_date": "2024-01-01",
                "use_suggested_edd": True,
                "dating_method": "lmp",
                "gravida_at_start": 1,
                "para_at_start": 0,
                "abortions_at_start": 0,
            },
            actor_id=1,
            doctor_id=doctor["id"],
        )
        assert first["status"] == "active"
        assert first["edd_date"] == "2024-10-07"
        db.session.commit()

        with pytest.raises(ValueError, match="حمل نشط"):
            create_pregnancy(1, patient["id"], {"lmp_date": "2026-01-01"}, actor_id=1)

        closed = update_pregnancy(
            1,
            first["id"],
            {"close": True, "status": "completed", "outcome": "live_birth", "ended_at": "2024-10-01"},
            actor_id=1,
        )
        assert closed["status"] == "completed"
        db.session.commit()

        second = create_pregnancy(
            1,
            patient["id"],
            {
                "lmp_date": "2026-02-01",
                "edd_date": "2026-11-08",
                "dating_method": "ultrasound",
                "gravida_at_start": 2,
                "para_at_start": 1,
                "abortions_at_start": 0,
            },
            actor_id=1,
            doctor_id=doctor["id"],
        )
        db.session.commit()
        listed = list_pregnancies(1, patient["id"])
        assert len(listed["active"]) == 1
        assert listed["active"][0]["id"] == second["id"]
        assert len(listed["previous"]) == 1
        assert listed["previous"][0]["id"] == first["id"]


def test_observation_snapshot_and_completed_visit_guard(specialty_db):
    from modules.clinics.models import ClinicVisit
    from modules.clinics.service_gynecology import add_observation, create_pregnancy

    with specialty_db.app_context():
        _, doctor, patient, visit = _gyn_setup()
        preg = create_pregnancy(
            1,
            patient["id"],
            {"lmp_date": (date.today() - timedelta(days=100)).isoformat(), "use_suggested_edd": True},
            actor_id=1,
            doctor_id=doctor["id"],
        )
        db.session.commit()
        obs = add_observation(
            1,
            preg["id"],
            {"visit_id": visit["id"], "clinical_notes": "طبيعي", "fetal_heart_rate": 140},
            actor_id=1,
        )
        assert obs["items"]
        assert obs["items"][0]["gestational_age_weeks"] is not None
        db.session.commit()

        row = ClinicVisit.query.get(visit["id"])
        row.status = "completed"
        db.session.commit()
        with pytest.raises(ValueError, match="إكمال"):
            add_observation(1, preg["id"], {"visit_id": visit["id"], "clinical_notes": "x"}, actor_id=1)


def test_non_pregnant_gynecology_context(specialty_db):
    from modules.clinics.service_gynecology import get_gynecology_context, upsert_gynecology_profile

    with specialty_db.app_context():
        _, _, patient, visit = _gyn_setup()
        upsert_gynecology_profile(1, patient["id"], {"cycle_regular": True}, actor_id=1)
        db.session.commit()
        ctx = get_gynecology_context(1, patient["id"], visit_id=visit["id"])
        assert ctx["active_pregnancy"] is None
        assert ctx["profile"]["exists"] is True
        assert ctx["risk_scoring_available"] is False


def test_visit_context_and_timeline(specialty_db):
    from modules.clinics.service_gynecology import (
        add_observation,
        create_pregnancy,
        get_visit_gynecology_context,
    )

    with specialty_db.app_context():
        _, doctor, patient, visit = _gyn_setup()
        preg = create_pregnancy(
            1,
            patient["id"],
            {"lmp_date": (date.today() - timedelta(days=84)).isoformat(), "use_suggested_edd": True, "gravida_at_start": 1},
            actor_id=1,
            doctor_id=doctor["id"],
        )
        db.session.commit()
        add_observation(1, preg["id"], {"visit_id": visit["id"], "clinical_notes": "أسبوع 12 تقريباً"}, actor_id=1)
        db.session.commit()
        ctx = get_visit_gynecology_context(1, visit["id"])
        assert ctx["active_pregnancy"]["id"] == preg["id"]
        assert ctx["summary"]["gestational_age"]["weeks"] >= 11
        assert ctx["current_observation"] is not None
        events = ctx["pregnancy_context"]["timeline"]["events"]
        assert any(e["type"] == "pregnancy_created" for e in events)
        assert any(e["type"] == "antenatal_observation" for e in events)


def test_gynecology_context_query_bound(specialty_db):
    from sqlalchemy import event

    from modules.clinics.models import ClinicVital
    from modules.clinics.service_gynecology import create_pregnancy, get_gynecology_context

    with specialty_db.app_context():
        _, doctor, patient, visit = _gyn_setup()
        # prior closed pregnancy
        old = create_pregnancy(
            1,
            patient["id"],
            {"lmp_date": "2023-01-01", "use_suggested_edd": True, "gravida_at_start": 1},
            actor_id=1,
            doctor_id=doctor["id"],
        )
        from modules.clinics.service_gynecology import update_pregnancy

        update_pregnancy(1, old["id"], {"close": True, "ended_at": "2023-09-01", "outcome": "live_birth"}, actor_id=1)
        db.session.commit()
        create_pregnancy(
            1,
            patient["id"],
            {"lmp_date": (date.today() - timedelta(days=120)).isoformat(), "use_suggested_edd": True, "gravida_at_start": 2},
            actor_id=1,
            doctor_id=doctor["id"],
        )
        db.session.commit()
        for i in range(30):
            db.session.add(
                ClinicVital(
                    tenant_id=1,
                    visit_id=visit["id"],
                    patient_id=patient["id"],
                    weight_kg=60 + i * 0.1,
                    blood_pressure=f"{110 + i}/70",
                    recorded_at=datetime.utcnow() - timedelta(days=30 - i),
                )
            )
        db.session.commit()

        queries = []

        def before_cursor(conn, cursor, statement, parameters, context, executemany):
            queries.append(statement)

        event.listen(db.engine, "before_cursor_execute", before_cursor)
        try:
            ctx = get_gynecology_context(1, patient["id"], visit_id=visit["id"])
        finally:
            event.remove(db.engine, "before_cursor_execute", before_cursor)

        assert ctx["active_pregnancy"]
        assert len(ctx["previous_pregnancies"]) >= 1
        assert len(queries) < 40


def test_schema_v24_and_models():
    from modules.clinics.models import (
        ClinicGynecologyProfile,
        ClinicPregnancy,
        ClinicPregnancyObservation,
        CLINIC_MODELS,
    )
    from modules.clinics.schema import SCHEMA_VERSION

    assert SCHEMA_VERSION.startswith("clinics-v")
    major = int(SCHEMA_VERSION.split("-")[1].lstrip("v"))
    assert major >= 24
    assert ClinicGynecologyProfile in CLINIC_MODELS
    assert ClinicPregnancy in CLINIC_MODELS
    assert ClinicPregnancyObservation in CLINIC_MODELS


def test_no_sidebar_clutter_for_gyn():
    from pathlib import Path

    html = Path("templates/clinics/workspace.html").read_text(encoding="utf-8")
    assert "gynecology-tools.js" in html
    assert 'data-nav-key="pregnancy"' not in html
    assert "تسجيل حمل" not in html  # not a sidebar label
