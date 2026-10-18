"""Phase H — specialty integration, cross-specialty patient, integrity, UX gates."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from flask import Flask

from extensions import db

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def specialty_db():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        SECRET_KEY="phase-h",
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


def test_schema_is_v26_rc():
    from modules.clinics.schema import SCHEMA_VERSION

    assert SCHEMA_VERSION.startswith("clinics-v")


def test_specialty_integration_matrix_static():
    """Workspace + profile mounts exist for every specialty pack; no sidebar clutter."""
    workspace = (ROOT / "templates/clinics/workspace.html").read_text(encoding="utf-8")
    clinics_js = (ROOT / "static/clinics/clinics.js").read_text(encoding="utf-8")
    profile_js = (ROOT / "static/clinics/patient-profile.js").read_text(encoding="utf-8")
    nav_js = (ROOT / "static/clinics/nav.js").read_text(encoding="utf-8")

    assets = {
        "dentistry": ("dental-chart.js", "dental-treatment-plan.js"),
        "pediatrics": ("pediatric-tools.js",),
        "obstetrics_gynecology": ("gynecology-tools.js",),
        "internal_medicine": ("internal-medicine-tools.js",),
        "cardiology": ("cardiology-tools.js",),
    }
    for code, files in assets.items():
        for name in files:
            assert name in workspace, f"{code} missing asset {name}"

    assert 'data-tab="treatment"' in clinics_js  # dental treatment
    assert 'data-tab="pediatrics"' in clinics_js
    assert 'data-tab="gynecology"' in clinics_js
    assert 'data-tab="internal"' in clinics_js
    assert 'data-tab="cardiology"' in clinics_js

    for section in ("dental", "pediatrics", "gynecology", "internal_medicine", "cardiology"):
        assert section in profile_js

    # Specialty tools must not become sidebar destinations
    for forbidden in ('data-nav-key="ecg"', 'data-nav-key="pregnancy"', 'data-nav-key="diabetes"'):
        assert forbidden not in nav_js
        assert forbidden not in workspace


def test_patient_hub_top_level_limited():
    profile = (ROOT / "static/clinics/patient-profile.js").read_text(encoding="utf-8")
    assert 'overview: "نظرة عامة"' in profile
    assert 'schedule: "المواعيد والزيارات"' in profile
    assert 'clinical: "السجل السريري"' in profile
    assert 'treatment: "العلاج والمتابعة"' in profile
    assert 'files: "الملفات"' in profile
    assert 'finance: "المالية"' in profile
    # Specialty labels are nested section labels, not hub keys
    assert "hubLabels" in profile
    assert "cardiology:" in profile or "cardiology," in profile
    assert 'key: "cardiology"' not in profile  # not a top-level hub


def test_cross_specialty_unified_patient(specialty_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicPatient, ClinicVisit
    from modules.clinics.service_cardiology import create_ecg, upsert_cardiology_profile
    from modules.clinics.service_gynecology import create_pregnancy, upsert_gynecology_profile
    from modules.clinics.service_internal_medicine import create_chronic_condition
    from modules.clinics.service_specialties import seed_default_specialties

    with specialty_db.app_context():
        specs = {s["code"]: s for s in seed_default_specialties(1)}
        doctor = service.create_doctor(
            1,
            {
                "full_name": "د. متعدد",
                "primary_specialty_id": specs["internal_medicine"]["id"],
                "specialty_ids": [
                    specs["internal_medicine"]["id"],
                    specs["dentistry"]["id"],
                    specs["cardiology"]["id"],
                    specs["obstetrics_gynecology"]["id"],
                ],
            },
        )
        patient = service.create_patient(
            1, {"full_name": "مريض موحد", "date_of_birth": date(1990, 1, 1).isoformat()}
        )
        visits = {}
        for code in ("internal_medicine", "dentistry", "cardiology", "obstetrics_gynecology"):
            visits[code] = service.create_walkin_visit(
                1,
                {
                    "patient_id": patient["id"],
                    "doctor_id": doctor["id"],
                    "specialty_id": specs[code]["id"],
                },
            )
        create_chronic_condition(
            1, patient["id"], {"condition_code": "diabetes", "status": "active"}, actor_id=1
        )
        upsert_cardiology_profile(1, patient["id"], {"smoking_status": "never"}, actor_id=1)
        create_ecg(
            1,
            patient["id"],
            {"visit_id": visits["cardiology"]["id"], "rhythm": "sinus"},
            actor_id=1,
        )
        upsert_gynecology_profile(1, patient["id"], {"cycle_regular": True}, actor_id=1)
        create_pregnancy(
            1,
            patient["id"],
            {"lmp_date": (date.today() - timedelta(days=70)).isoformat(), "use_suggested_edd": True},
            actor_id=1,
            doctor_id=doctor["id"],
        )
        db.session.commit()

        assert ClinicPatient.query.filter_by(tenant_id=1).count() == 1
        assert ClinicVisit.query.filter_by(tenant_id=1, patient_id=patient["id"]).count() == 4
        # Each visit keeps its specialty
        for code, visit in visits.items():
            row = ClinicVisit.query.get(visit["id"])
            assert row.patient_id == patient["id"]
            assert row.specialty_id == specs[code]["id"]
            detail = service.get_visit_detail(1, visit["id"])
            assert detail["specialty"]["code"] == code
            assert detail.get("template") is not None


def test_completed_visit_integrity_multi_specialty(specialty_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicVisit
    from modules.clinics.service_cardiology import create_ecg, create_echo
    from modules.clinics.service_gynecology import add_observation, create_pregnancy
    from modules.clinics.service_specialties import seed_default_specialties

    with specialty_db.app_context():
        specs = {s["code"]: s for s in seed_default_specialties(1)}
        doctor = service.create_doctor(
            1,
            {
                "full_name": "د. سلامة",
                "primary_specialty_id": specs["cardiology"]["id"],
                "specialty_ids": [specs["cardiology"]["id"], specs["obstetrics_gynecology"]["id"]],
            },
        )
        patient = service.create_patient(1, {"full_name": "مريض سلامة"})
        cardio_visit = service.create_walkin_visit(
            1,
            {
                "patient_id": patient["id"],
                "doctor_id": doctor["id"],
                "specialty_id": specs["cardiology"]["id"],
            },
        )
        create_ecg(1, patient["id"], {"visit_id": cardio_visit["id"], "rhythm": "sinus"}, actor_id=1)
        create_echo(1, patient["id"], {"visit_id": cardio_visit["id"], "lvef_percent": 55}, actor_id=1)
        ClinicVisit.query.get(cardio_visit["id"]).status = "completed"
        db.session.flush()
        with pytest.raises(ValueError, match="مكتملة"):
            create_ecg(1, patient["id"], {"visit_id": cardio_visit["id"], "rhythm": "af"}, actor_id=1)
        with pytest.raises(ValueError, match="مكتملة"):
            create_echo(1, patient["id"], {"visit_id": cardio_visit["id"], "lvef_percent": 40}, actor_id=1)

        gyn_visit = service.create_walkin_visit(
            1,
            {
                "patient_id": patient["id"],
                "doctor_id": doctor["id"],
                "specialty_id": specs["obstetrics_gynecology"]["id"],
            },
        )
        preg = create_pregnancy(
            1,
            patient["id"],
            {"lmp_date": (date.today() - timedelta(days=60)).isoformat(), "use_suggested_edd": True},
            actor_id=1,
            doctor_id=doctor["id"],
        )
        add_observation(
            1, preg["id"], {"visit_id": gyn_visit["id"], "clinical_notes": "ok"}, actor_id=1
        )
        ClinicVisit.query.get(gyn_visit["id"]).status = "completed"
        db.session.flush()
        with pytest.raises(ValueError):
            add_observation(
                1, preg["id"], {"visit_id": gyn_visit["id"], "clinical_notes": "edit"}, actor_id=1
            )


def test_no_duplicate_longitudinal_engines():
    cardio = (ROOT / "modules/clinics/service_cardiology.py").read_text(encoding="utf-8")
    assert "get_vital_trends" in cardio
    assert "get_lab_trends" in cardio
    assert "compare_visits" in cardio
    assert "ClinicPatientMedication" in cardio
    assert "ClinicChronicCondition" in cardio or "list_chronic_conditions" in cardio
    # No second trend service file
    assert not (ROOT / "modules/clinics/service_cardiology_trends.py").exists()
    assert not (ROOT / "static/clinics/cardiology-vital-trends.js").exists()


def test_terminology_consistency_static():
    clinics_js = (ROOT / "static/clinics/clinics.js").read_text(encoding="utf-8")
    profile = (ROOT / "static/clinics/patient-profile.js").read_text(encoding="utf-8")
    assert "الباطنية والأمراض المزمنة" in clinics_js or "الباطنية" in clinics_js
    assert "القلب والأوعية" in clinics_js
    assert "النسائية والتوليد" in clinics_js
    assert "طب الأطفال" in clinics_js
    assert "القلب والأوعية" in profile
    assert "الباطنية والأمراض المزمنة" in profile


def test_health_endpoint_safe(specialty_db):
    from modules.clinics import init_clinics

    init_clinics(specialty_db)
    client = specialty_db.test_client()
    response = client.get("/clinics/api/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["service"] == "clinics"
    assert payload["database"] == "up"
    assert "password" not in str(payload).lower()
    assert "tenant" not in payload
