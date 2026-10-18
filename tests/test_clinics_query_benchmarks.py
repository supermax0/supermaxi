"""Measured query-count benchmarks for clinics hot paths (not guesses)."""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import event

from extensions import db
from tests.test_clinics_specialties import specialty_db  # noqa: F401

ARTIFACTS = Path(__file__).resolve().parents[1] / "tests" / "_artifacts" / "query_benchmarks"


class QueryCounter:
    def __init__(self, engine):
        self.engine = engine
        self.count = 0

    def __enter__(self):
        self.count = 0
        event.listen(self.engine, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *args):
        event.remove(self.engine, "before_cursor_execute", self._on_execute)

    def _on_execute(self, *args, **kwargs):
        self.count += 1


@pytest.fixture()
def seeded_clinic(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_specialties import seed_default_specialties

    with specialty_db.app_context():
        specs = seed_default_specialties(1)
        doctors = []
        for spec in specs[:4]:
            doctors.append(
                service.create_doctor(
                    1,
                    {
                        "full_name": f"د. {spec['name_ar']}",
                        "primary_specialty_id": spec["id"],
                        "specialty_ids": [spec["id"]],
                    },
                )
            )
        for i in range(8):
            service.create_service(
                1,
                {
                    "name": f"خدمة {i}",
                    "price": 10000 + i,
                    "specialty_ids": [specs[i % len(specs[:4])]["id"]],
                    "doctor_ids": [doctors[i % len(doctors)]["id"]],
                },
            )
        patient = service.create_patient(1, {"full_name": "مريض أداء"})
        day = date.today()
        for i, doctor in enumerate(doctors):
            appt = service.create_appointment(
                1,
                {
                    "patient_id": patient["id"],
                    "doctor_id": doctor["id"],
                    "specialty_id": specs[i % 4]["id"],
                    "appointment_date": day.isoformat(),
                    "start_time": f"{9 + i}:00",
                },
            )
            service.start_visit_from_appointment(1, appt["id"])
        db.session.commit()
        yield {"patient_id": patient["id"], "day": day, "app": specialty_db}


def test_hot_path_query_budgets(seeded_clinic):
    from modules.clinics import service
    from modules.clinics.service_appointments import get_appointments_board
    from modules.clinics.service_booking import public_clinic_info
    from modules.clinics.service_dashboard import dashboard_snapshot
    from modules.clinics.service_doctors import doctors_center
    from modules.clinics.service_reports import reports_hub
    from modules.clinics.service_specialties import list_specialties

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    app = seeded_clinic["app"]
    results = {}

    def measure(label, fn, budget):
        with app.app_context():
            with QueryCounter(db.engine) as counter:
                started = time.perf_counter()
                fn()
                elapsed_ms = (time.perf_counter() - started) * 1000
            results[label] = {
                "query_count": counter.count,
                "response_time_ms": round(elapsed_ms, 2),
                "budget": budget,
            }
            assert counter.count <= budget, f"{label}: {counter.count} queries > budget {budget}"

    measure("dashboard", lambda: dashboard_snapshot(1, seeded_clinic["day"]), 80)
    measure("appointments_board", lambda: get_appointments_board(1, seeded_clinic["day"]), 90)
    measure("specialties", lambda: list_specialties(1), 15)
    measure("doctors_center", lambda: doctors_center(1, {}), 120)
    measure("patient_profile", lambda: service.get_patient(1, seeded_clinic["patient_id"]), 60)
    measure("reports", lambda: reports_hub(1, {"date_from": seeded_clinic["day"].isoformat(), "date_to": seeded_clinic["day"].isoformat()}), 150)
    measure("public_booking_info", lambda: public_clinic_info(1), 40)
    measure("public_booking_services", lambda: service.list_services(1, active_only=True), 12)
    measure("public_booking_doctors", lambda: service.list_doctors(1, active_only=True), 12)

    (ARTIFACTS / "hot_paths.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    # list_services must stay O(1) link queries (bulk), not 2N.
    assert results["public_booking_services"]["query_count"] <= 12
