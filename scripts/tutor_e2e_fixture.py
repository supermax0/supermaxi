"""State helpers for the AI Tutor browser E2E (throwaway tenants only).

    py scripts/tutor_e2e_fixture.py reset [--features]  # progress + logs cleared, specialties re-activated (+ feature off with --features)
    py scripts/tutor_e2e_fixture.py enable <slug>     # turn the feature on for one tenant
    py scripts/tutor_e2e_fixture.py logs <slug>       # progress + training logs as JSON
    py scripts/tutor_e2e_fixture.py strip <slug>      # clinic with NO doctors, specialties or services (clean slate)
    py scripts/tutor_e2e_fixture.py clear-patients <slug>  # remove patients/appointments/visits/plans/invoices a run created

Refuses any tenant that is not one of the provisioned E2E tenants.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FINORA_DISABLE_SCHEDULERS", "1")
os.environ.setdefault("DISABLE_CLINICS_SCHEDULER", "1")
os.environ.setdefault("DISABLE_PUBLISHER_SCHEDULER", "1")

SLUGS = ("tutor-e2e-a", "tutor-e2e-b", "tutor-e2e-c")
PROGRESS_TABLES = ("user_training_progress", "training_activity_logs")
STRIP_TABLES = (
    "clinic_doctor_schedule", "clinic_doctor_service", "clinic_doctor_specialty", "clinic_doctor_time_off",
    "clinic_service_specialty", "clinic_service", "clinic_doctor", "clinic_specialty",
)
PATIENT_TABLES = (
    "clinic_invoice_item", "clinic_invoice", "clinic_dental_treatment_plan_item_link", "clinic_dental_treatment_plan_item",
    "clinic_dental_treatment_plan", "clinic_visit", "clinic_appointment_status_history", "clinic_appointment", "clinic_patient",
)


def _db(slug: str) -> sqlite3.Connection:
    if slug not in SLUGS:
        raise SystemExit(f"refusing {slug!r}: not an E2E tenant")
    return sqlite3.connect(ROOT / "tenants" / f"{slug}.db")


def _delete(con: sqlite3.Connection, tables: tuple[str, ...]) -> None:
    con.execute("PRAGMA foreign_keys=OFF")
    for table in tables:
        try:
            con.execute(f"DELETE FROM {table}")
        except sqlite3.OperationalError:
            pass  # table is created lazily / not part of this schema


def reset() -> None:
    for slug in SLUGS:
        if not (ROOT / "tenants" / f"{slug}.db").exists():
            continue
        con = _db(slug)
        try:
            with con:
                _delete(con, PROGRESS_TABLES)
                try:
                    con.execute("UPDATE clinic_specialty SET is_active = 1")
                except sqlite3.OperationalError:
                    pass
        finally:
            con.close()
    if "--features" in sys.argv:
        from app import app
        from services import feature_service as fs

        with app.app_context():
            for slug in SLUGS:
                if (ROOT / "tenants" / f"{slug}.db").exists():
                    fs.set_feature(slug, fs.AI_TUTOR, enabled=False, actor="e2e-reset")
    print("state reset")


def enable(slug: str) -> None:
    _db(slug).close()
    from app import app
    from services import feature_service as fs

    with app.app_context():
        fs.set_feature(slug, fs.AI_TUTOR, enabled=True, actor="e2e-fixture")
    print(f"{slug}: AI Tutor enabled")


def logs(slug: str) -> None:
    """Every column of every training log + progress row (the privacy spec greps this for patient data)."""
    import json

    con = _db(slug)
    try:
        out = {}
        for table in PROGRESS_TABLES:
            cur = con.execute(f"SELECT * FROM {table}")
            names = [d[0] for d in cur.description]
            out[table] = [dict(zip(names, row)) for row in cur.fetchall()]
        print(json.dumps(out, ensure_ascii=False, default=str))
    finally:
        con.close()


def strip(slug: str) -> None:
    con = _db(slug)
    try:
        with con:
            _delete(con, PATIENT_TABLES + STRIP_TABLES + PROGRESS_TABLES)
    finally:
        con.close()
    print(f"{slug}: stripped to an empty clinic")


def clear_patients(slug: str) -> None:
    con = _db(slug)
    try:
        with con:
            _delete(con, PATIENT_TABLES)
    finally:
        con.close()
    print(f"{slug}: patients and dependants removed")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "reset":
        reset()
    elif len(args) == 2 and args[0] == "enable":
        enable(args[1])
    elif len(args) == 2 and args[0] == "logs":
        logs(args[1])
    elif len(args) == 2 and args[0] == "strip":
        strip(args[1])
    elif len(args) == 2 and args[0] == "clear-patients":
        clear_patients(args[1])
    else:
        raise SystemExit(__doc__)
