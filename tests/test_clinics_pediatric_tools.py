"""Phase D — Pediatric clinical tools regression."""
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
        SECRET_KEY="pediatric-test",
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


def _ped_setup(tenant_id=1, dob=None):
    from modules.clinics import service
    from modules.clinics.service_specialties import seed_default_specialties

    specialties = seed_default_specialties(tenant_id)
    ped = next(row for row in specialties if row["code"] == "pediatrics")
    doctor = service.create_doctor(
        tenant_id,
        {"full_name": "د. أطفال", "primary_specialty_id": ped["id"], "specialty_ids": [ped["id"]]},
    )
    patient = service.create_patient(
        tenant_id,
        {
            "full_name": "طفل تجريبي",
            "date_of_birth": (dob or date(2024, 1, 15)).isoformat(),
        },
    )
    visit = service.create_walkin_visit(
        tenant_id,
        {"patient_id": patient["id"], "doctor_id": doctor["id"], "specialty_id": ped["id"]},
    )
    return ped, doctor, patient, visit


def test_pediatric_profile_and_tenant_isolation(specialty_db):
    from modules.clinics.service_pediatrics import get_pediatric_profile, upsert_pediatric_profile

    with specialty_db.app_context():
        _, _, patient, _ = _ped_setup()
        empty = get_pediatric_profile(1, patient["id"])
        assert empty["exists"] is False
        saved = upsert_pediatric_profile(
            1,
            patient["id"],
            {
                "gestational_age_weeks": 38,
                "delivery_type": "vaginal",
                "birth_weight": 3.2,
                "feeding_type": "breastfeeding",
                "nicu_admission": False,
            },
        )
        assert saved["exists"] is True
        assert saved["birth_weight"] == 3.2
        with pytest.raises(ValueError):
            get_pediatric_profile(2, patient["id"])
        with pytest.raises(ValueError, match="عمر الحمل"):
            upsert_pediatric_profile(1, patient["id"], {"gestational_age_weeks": 5})


def test_vitals_head_circumference_feeds_growth_history(specialty_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicVital
    from modules.clinics.service_pediatrics import get_pediatric_growth

    with specialty_db.app_context():
        _, _, patient, visit = _ped_setup(dob=date(2023, 6, 1))
        service.save_vitals(
            1,
            visit["id"],
            {"weight_kg": 10.5, "height_cm": 78, "head_circumference_cm": 46.5},
        )
        assert ClinicVital.query.filter_by(tenant_id=1, patient_id=patient["id"]).count() == 1
        growth = get_pediatric_growth(1, patient["id"])
        assert growth["latest"]["weight_kg"] == 10.5
        assert growth["latest"]["head_circumference_cm"] == 46.5
        assert growth["latest"]["bmi"] is not None
        assert growth["percentile_available"] is False
        assert growth["latest"]["age_days"] is not None
        # no duplicate pediatric vital table
        assert len(growth["history"]) == 1


def test_vaccination_archive_and_birth_date_guard(specialty_db):
    from modules.clinics.service_pediatrics import add_vaccination, list_vaccinations, update_vaccination

    with specialty_db.app_context():
        _, _, patient, _ = _ped_setup(dob=date(2024, 1, 1))
        with pytest.raises(ValueError, match="قبل تاريخ الميلاد"):
            add_vaccination(
                1,
                patient["id"],
                {"vaccine_name": "BCG", "administered_date": "2023-01-01", "status": "administered"},
            )
        listed = add_vaccination(
            1,
            patient["id"],
            {
                "vaccine_name": "BCG",
                "dose_label": "جرعة 1",
                "administered_date": "2024-02-01",
                "source": "parent_report",
                "status": "reported_by_parent",
            },
        )
        assert listed["items"][0]["source"] == "parent_report"
        vax_id = listed["items"][0]["id"]
        update_vaccination(1, vax_id, {"archive": True})
        assert list_vaccinations(1, patient["id"])["items"] == []


def test_development_history_preserves_visits(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_pediatrics import add_development, list_development

    with specialty_db.app_context():
        ped, doctor, patient, visit1 = _ped_setup()
        add_development(
            1,
            patient["id"],
            {
                "visit_id": visit1["id"],
                "doctor_id": doctor["id"],
                "domains": {"language": {"status": "documented", "notes": "كلام"}},
            },
        )
        service.complete_visit(1, visit1["id"], auto_invoice=False)
        visit2 = service.create_walkin_visit(
            1,
            {"patient_id": patient["id"], "doctor_id": doctor["id"], "specialty_id": ped["id"]},
        )
        add_development(
            1,
            patient["id"],
            {
                "visit_id": visit2["id"],
                "doctor_id": doctor["id"],
                "domains": {"language": {"status": "concern_noted", "notes": "ملاحظة"}},
            },
        )
        hist = list_development(1, patient["id"])["items"]
        assert len(hist) == 2
        statuses = [h["domains"]["language"]["status"] for h in hist]
        assert statuses == ["concern_noted", "documented"]
        with pytest.raises(ValueError, match="بعد إكمال"):
            add_development(
                1,
                patient["id"],
                {"visit_id": visit1["id"], "domains": {"language": {"status": "documented"}}},
            )


def test_pediatric_context_bulk_and_query_bound(specialty_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicVital
    from modules.clinics.service_pediatrics import (
        add_development,
        add_vaccination,
        get_pediatric_context,
        upsert_pediatric_profile,
    )
    from sqlalchemy import event

    with specialty_db.app_context():
        _, doctor, patient, visit = _ped_setup(dob=date(2022, 1, 1))
        upsert_pediatric_profile(1, patient["id"], {"feeding_type": "mixed", "birth_weight": 3.0})
        base = datetime(2024, 1, 1)
        for i in range(50):
            db.session.add(
                ClinicVital(
                    tenant_id=1,
                    visit_id=visit["id"],
                    patient_id=patient["id"],
                    weight_kg=8 + i * 0.1,
                    height_cm=70 + i * 0.2,
                    head_circumference_cm=42 + i * 0.05,
                    recorded_at=base + timedelta(days=i),
                )
            )
        for i in range(20):
            add_vaccination(1, patient["id"], {"vaccine_name": f"V{i}", "status": "recorded"})
        for i in range(20):
            add_development(
                1,
                patient["id"],
                {
                    "visit_id": visit["id"],
                    "doctor_id": doctor["id"],
                    "domains": {"gross_motor": {"status": "documented"}},
                },
            )
        db.session.commit()

        queries = []

        def before_cursor(*_a, **_k):
            queries.append(1)

        event.listen(db.engine, "before_cursor_execute", before_cursor)
        try:
            ctx = get_pediatric_context(1, patient["id"])
        finally:
            event.remove(db.engine, "before_cursor_execute", before_cursor)

        assert len(ctx["growth_history"]) == 50
        assert len(ctx["vaccinations"]) == 20
        assert len(ctx["development_history"]) == 20
        assert ctx["percentile_available"] is False
        assert len(queries) < 25  # bounded bulk load


def test_schema_version_v23():
    from modules.clinics.schema import SCHEMA_VERSION

    # Phase D locked to v23; later packs bump while retaining pediatric models.
    assert SCHEMA_VERSION.startswith("clinics-v")
    major = int(SCHEMA_VERSION.split("-")[1].lstrip("v"))
    assert major >= 23


def test_dental_suites_still_importable():
    from modules.clinics.schema import SCHEMA_VERSION
    from modules.clinics.service_dental import validate_tooth_number
    from modules.clinics.service_dental_treatment import PLAN_STATUSES
    from modules.clinics.models import ClinicPediatricProfile

    assert validate_tooth_number("16") == "16"
    assert "active" in PLAN_STATUSES
    assert ClinicPediatricProfile.__tablename__
    assert SCHEMA_VERSION.startswith("clinics-v")
