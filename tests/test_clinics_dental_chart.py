"""Phase B — Interactive Dental Chart service/API regression."""
from __future__ import annotations

import pytest
from flask import Flask, g

from extensions import db


@pytest.fixture()
def specialty_db():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        SECRET_KEY="dental-chart-test",
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


def _dentistry_visit(tenant_id=1):
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
    patient = service.create_patient(tenant_id, {"full_name": "مريض أسنان"})
    visit = service.create_walkin_visit(
        tenant_id,
        {
            "patient_id": patient["id"],
            "doctor_id": doctor["id"],
            "specialty_id": dentistry["id"],
        },
    )
    return dentistry, doctor, patient, visit


def test_dental_chart_validation_and_surfaces(specialty_db):
    from modules.clinics.service_dental import upsert_tooth_finding, get_visit_dental_chart

    with specialty_db.app_context():
        _, _, _, visit = _dentistry_visit()
        with pytest.raises(ValueError, match="غير صالح"):
            upsert_tooth_finding(1, visit["id"], "99", {"status": "caries"})
        with pytest.raises(ValueError, match="حالة"):
            upsert_tooth_finding(1, visit["id"], "16", {"status": "magic"})
        with pytest.raises(ValueError, match="سطح"):
            upsert_tooth_finding(1, visit["id"], "16", {"status": "caries", "surfaces": ["foo"]})

        chart = upsert_tooth_finding(
            1,
            visit["id"],
            "16",
            {"status": "caries", "surfaces": ["mesial", "occlusal", "mesial"], "notes": "ملاحظة"},
        )
        assert chart["has_chart"] is True
        tooth = next(t for t in chart["teeth"] if t["tooth_number"] == "16")
        assert tooth["status"] == "caries"
        assert tooth["surfaces"] == ["mesial", "occlusal"]
        assert tooth["dentition"] == "permanent"

        chart = upsert_tooth_finding(
            1, visit["id"], "55", {"status": "filled", "surfaces": ["incisal"], "dentition_mode": "primary"}
        )
        assert chart["dentition_mode"] == "primary"
        primary = next(t for t in chart["teeth"] if t["tooth_number"] == "55")
        assert primary["dentition"] == "primary"
        loaded = get_visit_dental_chart(1, visit["id"])
        assert len(loaded["teeth"]) == 2


def test_dental_history_preserves_visits_and_current_state(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_dental import get_patient_dental_history, upsert_tooth_finding

    with specialty_db.app_context():
        dentistry, doctor, patient, visit1 = _dentistry_visit()
        upsert_tooth_finding(1, visit1["id"], "16", {"status": "caries", "surfaces": ["occlusal"]})
        service.complete_visit(1, visit1["id"], auto_invoice=False)
        visit2 = service.create_walkin_visit(
            1,
            {
                "patient_id": patient["id"],
                "doctor_id": doctor["id"],
                "specialty_id": dentistry["id"],
            },
        )
        upsert_tooth_finding(1, visit2["id"], "16", {"status": "root_canal", "surfaces": ["occlusal"]})
        history = get_patient_dental_history(1, patient["id"])
        statuses = [h["status"] for h in history["history"] if h["tooth_number"] == "16"]
        assert statuses == ["root_canal", "caries"]
        current = next(t for t in history["current_state"] if t["tooth_number"] == "16")
        assert current["status"] == "root_canal"
        chart2 = __import__("modules.clinics.service_dental", fromlist=["get_visit_dental_chart"]).get_visit_dental_chart(
            1, visit2["id"]
        )
        assert chart2["history_summary"]["16"]["status"] == "caries"


def test_patient_chart_persists_into_new_visit_and_patient_file(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_dental import (
        get_patient_dental_chart,
        get_visit_dental_chart,
        upsert_tooth_finding,
    )

    with specialty_db.app_context():
        dentistry, doctor, patient, visit1 = _dentistry_visit()
        upsert_tooth_finding(
            1, visit1["id"], "16",
            {"status": "caries", "surfaces": ["occlusal"], "notes": "من الزيارة الأولى"},
        )
        service.complete_visit(1, visit1["id"], auto_invoice=False)
        visit2 = service.create_walkin_visit(
            1,
            {
                "patient_id": patient["id"],
                "doctor_id": doctor["id"],
                "specialty_id": dentistry["id"],
            },
        )

        carried = get_visit_dental_chart(1, visit2["id"])
        tooth = next(row for row in carried["teeth"] if row["tooth_number"] == "16")
        assert tooth["status"] == "caries"
        assert tooth["visit_id"] == visit1["id"]
        assert carried["record_id"] is None
        assert carried["has_chart"] is True
        assert carried["scope"] == "patient"

        patient_chart = get_patient_dental_chart(1, patient["id"])
        saved = next(row for row in patient_chart["teeth"] if row["tooth_number"] == "16")
        assert saved["status"] == "caries"
        assert saved["notes"] == "من الزيارة الأولى"
        assert patient_chart["permissions"]["can_edit"] is False

        upsert_tooth_finding(1, visit2["id"], "16", {"status": "root_canal"})
        updated = get_patient_dental_chart(1, patient["id"])
        assert next(row for row in updated["teeth"] if row["tooth_number"] == "16")["status"] == "root_canal"


def test_dental_tenant_isolation(specialty_db):
    from modules.clinics.service_dental import get_visit_dental_chart, upsert_tooth_finding

    with specialty_db.app_context():
        _, _, _, visit = _dentistry_visit(1)
        upsert_tooth_finding(1, visit["id"], "16", {"status": "caries"})
        with pytest.raises(ValueError, match="غير موجودة"):
            get_visit_dental_chart(2, visit["id"])
        with pytest.raises(ValueError, match="غير موجودة"):
            upsert_tooth_finding(2, visit["id"], "16", {"status": "filled"})


def test_dental_completed_visit_readonly(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_dental import get_visit_dental_chart, upsert_tooth_finding

    with specialty_db.app_context():
        _, _, _, visit = _dentistry_visit()
        upsert_tooth_finding(1, visit["id"], "16", {"status": "caries"})
        service.complete_visit(1, visit["id"], auto_invoice=False)
        chart = get_visit_dental_chart(1, visit["id"])
        assert chart["permissions"]["can_edit"] is False
        assert any(t["tooth_number"] == "16" for t in chart["teeth"])
        with pytest.raises(ValueError, match="بعد إكمال"):
            upsert_tooth_finding(1, visit["id"], "16", {"status": "filled"})


def test_concurrent_findings_can_be_resolved_independently(specialty_db):
    from modules.clinics.models import ClinicDentalToothEvent
    from modules.clinics.service_dental import add_active_tooth_finding, resolve_active_tooth_finding

    with specialty_db.app_context():
        _, _, _, visit = _dentistry_visit()
        chart = add_active_tooth_finding(
            1, visit["id"], "16", {"status": "caries", "surfaces": ["occlusal"]}
        )
        chart = add_active_tooth_finding(
            1, visit["id"], "16", {"status": "fracture", "surfaces": ["distal"]}
        )
        tooth = next(row for row in chart["teeth"] if row["tooth_number"] == "16")
        assert {row["status"] for row in tooth["findings"]} == {"caries", "fracture"}
        assert set(tooth["visual_statuses"]) == {"caries", "fracture"}
        caries = next(row for row in tooth["findings"] if row["status"] == "caries")
        chart = resolve_active_tooth_finding(1, visit["id"], "16", caries["id"], {})
        tooth = next(row for row in chart["teeth"] if row["tooth_number"] == "16")
        assert [row["status"] for row in tooth["findings"]] == ["fracture"]
        assert ClinicDentalToothEvent.query.filter_by(
            tenant_id=1, supersedes_event_id=caries["id"], event_type="finding_resolved"
        ).count() == 1


def test_dental_procedure_link_reuses_visit_procedure(specialty_db):
    from modules.clinics.models import ClinicDentalToothProcedure, ClinicProcedure
    from modules.clinics.service_dental import upsert_tooth_finding
    from modules.clinics.service_ops import add_visit_procedure

    with specialty_db.app_context():
        dentistry, _, _, visit = _dentistry_visit()
        proc = ClinicProcedure(
            tenant_id=1,
            name="حشوة",
            price=25000,
            active=True,
        )
        db.session.add(proc)
        db.session.flush()
        procs = add_visit_procedure(1, visit["id"], {"procedure_id": proc.id, "price": 25000})
        vp_id = procs[0]["id"]
        chart = upsert_tooth_finding(
            1,
            visit["id"],
            "16",
            {"status": "filled", "link_visit_procedure_id": vp_id},
        )
        tooth = next(t for t in chart["teeth"] if t["tooth_number"] == "16")
        assert tooth["procedures"][0]["visit_procedure_id"] == vp_id
        assert ClinicDentalToothProcedure.query.filter_by(tenant_id=1, visit_procedure_id=vp_id).count() == 1
        # Idempotent re-link
        upsert_tooth_finding(
            1, visit["id"], "16", {"status": "filled", "link_visit_procedure_id": vp_id}
        )
        assert ClinicDentalToothProcedure.query.filter_by(tenant_id=1, visit_procedure_id=vp_id).count() == 1
        assert dentistry["code"] == "dentistry"


def test_dental_doctor_scope_blocks_foreign_visit(specialty_db, monkeypatch):
    from types import SimpleNamespace

    from modules.clinics import guards, service
    from modules.clinics.models import ClinicDoctor
    from modules.clinics.service_dental import get_visit_dental_chart, upsert_tooth_finding
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
            for name in ("Own Dentist", "Other Dentist")
        ]
        patient = service.create_patient(1, {"full_name": "مشترك"})
        own = service.create_walkin_visit(
            1, {"patient_id": patient["id"], "doctor_id": doctors[0]["id"], "specialty_id": dentistry["id"]}
        )
        other = service.create_walkin_visit(
            1, {"patient_id": patient["id"], "doctor_id": doctors[1]["id"], "specialty_id": dentistry["id"]}
        )
        upsert_tooth_finding(1, other["id"], "16", {"status": "caries"})
        db.session.commit()

        employee = SimpleNamespace(
            id=10,
            role="doctor",
            is_active=True,
            has_permission=lambda key: key in {"clinics_clinical"},
        )
        monkeypatch.setattr(guards, "current_employee", lambda: employee)
        monkeypatch.setattr(guards, "current_tenant_id", lambda: 1)
        monkeypatch.setattr(guards, "is_clinics_tenant", lambda: True)
        monkeypatch.setattr(
            guards, "get_current_clinic_doctor", lambda: db.session.get(ClinicDoctor, doctors[0]["id"])
        )

        @guards.require_clinics("clinics_clinical", json_mode=True)
        def read_other():
            return get_visit_dental_chart(1, other["id"])

        @guards.require_clinics("clinics_clinical", json_mode=True)
        def write_other():
            return upsert_tooth_finding(1, other["id"], "16", {"status": "filled"})

        @guards.require_clinics("clinics_clinical", json_mode=True)
        def read_own():
            return get_visit_dental_chart(1, own["id"])

        with specialty_db.test_request_context("/clinics/api/visits/x/dental-chart"):
            assert read_own()["visit_id"] == own["id"]
            with pytest.raises(ValueError):
                read_other()
            with pytest.raises(ValueError):
                write_other()


def test_dentistry_seed_template_includes_dental_chart(specialty_db):
    from modules.clinics.models import ClinicVisitTemplateField
    from modules.clinics.service_specialties import seed_default_specialties

    with specialty_db.app_context():
        dentistry = next(row for row in seed_default_specialties(1) if row["code"] == "dentistry")
        fields = ClinicVisitTemplateField.query.filter_by(
            tenant_id=1, template_id=dentistry["default_visit_template_id"]
        ).all()
        assert any(f.field_type == "dental_chart" for f in fields)


def test_dental_chart_rtl_anatomical_order_in_static_asset():
    """RTL must not reverse FDI anatomical order — chart root forces dir=ltr."""
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "static" / "clinics" / "dental-chart.js").read_text(
        encoding="utf-8"
    )
    css = (Path(__file__).resolve().parents[1] / "static" / "clinics" / "dental-chart.css").read_text(
        encoding="utf-8"
    )
    assert 'dir="ltr"' in js
    assert '["18", "17", "16", "15", "14", "13", "12", "11"]' in js
    assert '["21", "22", "23", "24", "25", "26", "27", "28"]' in js
    assert ".cx-dental" in css
