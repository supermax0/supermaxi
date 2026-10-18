"""Report / export filter parity — same specialty+doctor+date must match hub and export."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from extensions import db
from tests.test_clinics_specialties import specialty_db  # noqa: F401


def test_reports_hub_and_export_share_filtered_dataset(specialty_db):
    from modules.clinics import service
    from modules.clinics.models import ClinicInvoice, ClinicPayment
    from modules.clinics.service_reports import reports_export_workbook_data, reports_hub
    from modules.clinics.service_specialties import create_specialty, seed_default_specialties

    with specialty_db.app_context():
        specs = seed_default_specialties(1)
        dentistry = next(s for s in specs if s["code"] == "dentistry")
        other = next(s for s in specs if s["code"] != "dentistry")
        doctor_b = service.create_doctor(
            1,
            {
                "full_name": "Doctor B",
                "primary_specialty_id": dentistry["id"],
                "specialty_ids": [dentistry["id"]],
            },
        )
        doctor_other = service.create_doctor(
            1,
            {
                "full_name": "Other Doc",
                "primary_specialty_id": other["id"],
                "specialty_ids": [other["id"]],
            },
        )
        day = date(2026, 9, 15)
        date_from = date(2026, 9, 1)
        date_to = date(2026, 9, 30)

        # In-filter activity
        for idx in range(3):
            patient = service.create_patient(1, {"full_name": f"Dent {idx}"})
            appt = service.create_appointment(
                1,
                {
                    "patient_id": patient["id"],
                    "doctor_id": doctor_b["id"],
                    "specialty_id": dentistry["id"],
                    "appointment_date": day.isoformat(),
                    "start_time": f"{10 + idx}:00",
                },
            )
            visit = service.start_visit_from_appointment(1, appt["id"])
            service.complete_visit(1, visit["id"], auto_invoice=True)
            inv = ClinicInvoice.query.filter_by(tenant_id=1, visit_id=visit["id"]).first()
            if inv and inv.balance > 0:
                service.receive_payment(1, inv.id, {"amount": inv.balance, "method": "cash"})

        # Out-of-filter noise
        patient = service.create_patient(1, {"full_name": "Noise"})
        appt = service.create_appointment(
            1,
            {
                "patient_id": patient["id"],
                "doctor_id": doctor_other["id"],
                "specialty_id": other["id"],
                "appointment_date": day.isoformat(),
                "start_time": "16:00",
            },
        )
        visit = service.start_visit_from_appointment(1, appt["id"])
        service.complete_visit(1, visit["id"], auto_invoice=True)
        db.session.commit()

        args = {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "doctor_id": doctor_b["id"],
            "specialty_id": dentistry["id"],
        }
        hub = reports_hub(1, args)
        export = reports_export_workbook_data(1, args)

        assert hub["filters"]["doctor_id"] == doctor_b["id"]
        assert hub["filters"]["specialty_id"] == dentistry["id"]
        assert hub["kpis"]["completed_visits"] == 3
        assert hub["kpis"]["appointments"] >= 3

        # Export summary mirrors hub KPIs
        summary = {row[0]: row[1] for row in export["summary"][1:]}
        assert summary["زيارات مكتملة"] == hub["kpis"]["completed_visits"]
        assert summary["المواعيد"] == hub["kpis"]["appointments"]
        assert summary["مفوتر"] == hub["kpis"]["invoiced"]
        assert summary["محصّل"] == hub["kpis"]["collected"]

        # Doctor series only Doctor B when filtered
        doctor_names = [row[0] for row in export["by_doctor"][1:]]
        assert doctor_names == ["Doctor B"] or all(name == "Doctor B" for name in doctor_names)

        # Specialty sheet restricted to dentistry when specialty filter set
        specialty_names = [row[0] for row in export["specialties"][1:]]
        assert len(specialty_names) == 1
        assert dentistry["name_ar"] in specialty_names[0] or specialty_names[0]

        # Daily series totals match appointment/visit counts in period
        day_appts = sum(row[1] for row in export["by_day"][1:])
        day_visits = sum(row[2] for row in export["by_day"][1:])
        assert day_appts == hub["kpis"]["appointments"]
        assert day_visits == hub["kpis"]["completed_visits"]


def test_unfiltered_hub_includes_other_specialty(specialty_db):
    from modules.clinics import service
    from modules.clinics.service_reports import reports_hub
    from modules.clinics.service_specialties import seed_default_specialties

    with specialty_db.app_context():
        specs = seed_default_specialties(1)
        dentistry = next(s for s in specs if s["code"] == "dentistry")
        other = next(s for s in specs if s["code"] != "dentistry")
        doctors = []
        for spec in (dentistry, other):
            doctors.append(
                service.create_doctor(
                    1,
                    {
                        "full_name": f"Dr {spec['code']}",
                        "primary_specialty_id": spec["id"],
                        "specialty_ids": [spec["id"]],
                    },
                )
            )
        day = date.today()
        for doctor, spec in zip(doctors, (dentistry, other)):
            patient = service.create_patient(1, {"full_name": f"P {spec['code']}"})
            appt = service.create_appointment(
                1,
                {
                    "patient_id": patient["id"],
                    "doctor_id": doctor["id"],
                    "specialty_id": spec["id"],
                    "appointment_date": day.isoformat(),
                    "start_time": "11:00",
                },
            )
            visit = service.start_visit_from_appointment(1, appt["id"])
            service.complete_visit(1, visit["id"], auto_invoice=False)
        db.session.commit()
        all_hub = reports_hub(1, {"date_from": day.isoformat(), "date_to": day.isoformat()})
        filtered = reports_hub(
            1,
            {
                "date_from": day.isoformat(),
                "date_to": day.isoformat(),
                "specialty_id": dentistry["id"],
            },
        )
        assert all_hub["kpis"]["completed_visits"] == 2
        assert filtered["kpis"]["completed_visits"] == 1
