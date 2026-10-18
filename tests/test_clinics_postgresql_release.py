"""Release gates that must run against an actual PostgreSQL server.

Set CLINICS_TEST_POSTGRES_URL to a dedicated, disposable database.  These tests
drop and recreate its schema and are intentionally skipped for ordinary SQLite
test runs.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import os
import threading

import pytest
from flask import Flask
from sqlalchemy import inspect, text

from extensions import db


@pytest.fixture(scope="module")
def pg_app():
    url = os.environ.get("CLINICS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("CLINICS_TEST_POSTGRES_URL is required for PostgreSQL release gates")
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        SECRET_KEY="clinics-postgres-release",
    )
    db.init_app(app)
    import models  # noqa: F401
    from models.delivery_agent import DeliveryAgent  # noqa: F401
    from modules.clinics.models import CLINIC_MODELS  # noqa: F401

    with app.app_context():
        # The URL must point at a dedicated disposable database. Resetting its
        # public schema also avoids unrelated application FK cycles in drop_all.
        with db.engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        with db.engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))


def test_schema_upgrade_is_idempotent_on_postgresql(pg_app):
    from modules.clinics import schema

    with pg_app.app_context():
        # Simulate the pre-hardening state for additive objects introduced in
        # v19/v20, then execute the production initializer twice.
        db.session.execute(text("DROP TABLE IF EXISTS clinic_prescription_template_item CASCADE"))
        db.session.execute(text("DROP TABLE IF EXISTS clinic_prescription_template CASCADE"))
        db.session.execute(text("DROP TABLE IF EXISTS clinic_procedure_specialty CASCADE"))
        db.session.execute(text("ALTER TABLE clinic_invoice DROP CONSTRAINT IF EXISTS uq_clinic_invoice_visit"))
        db.session.execute(text("ALTER TABLE clinic_invoice DROP CONSTRAINT IF EXISTS uq_clinic_invoice_number"))
        db.session.execute(text("DROP INDEX IF EXISTS uq_clinic_invoice_visit"))
        db.session.execute(text("DROP INDEX IF EXISTS uq_clinic_invoice_number"))
        db.session.commit()

        schema.clear_clinics_schema_cache()
        schema.ensure_clinics_schema()
        schema.clear_clinics_schema_cache()
        schema.ensure_clinics_schema()

        inspector = inspect(db.engine)
        assert inspector.has_table("clinic_prescription_template")
        assert inspector.has_table("clinic_prescription_template_item")
        assert inspector.has_table("clinic_procedure_specialty")
        indexes = {row["name"] for row in inspector.get_indexes("clinic_invoice")}
        assert {"uq_clinic_invoice_visit", "uq_clinic_invoice_number"} <= indexes


def _run_parallel(app, workers):
    barrier = threading.Barrier(len(workers))

    def invoke(worker):
        with app.app_context():
            try:
                barrier.wait(timeout=10)
                value = worker()
                db.session.commit()
                return ("ok", value)
            except Exception as exc:  # expected for one conflicting booking
                db.session.rollback()
                return ("error", str(exc))
            finally:
                db.session.remove()

    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        return list(pool.map(invoke, workers))


def test_postgresql_serializes_overlapping_bookings(pg_app):
    from modules.clinics import service
    from modules.clinics.models import ClinicAppointment

    with pg_app.app_context():
        doctor = service.create_doctor(501, {"full_name": "طبيب التزامن"})
        patient = service.create_patient(501, {"full_name": "مريض التزامن"})
        db.session.commit()
        doctor_id, patient_id = doctor["id"], patient["id"]

    payload = {
        "doctor_id": doctor_id,
        "patient_id": patient_id,
        "appointment_date": date.today().isoformat(),
        "start_time": "10:00",
        "duration_minutes": 30,
    }
    results = _run_parallel(pg_app, [
        lambda: service.create_appointment(501, payload),
        lambda: service.create_appointment(501, payload),
    ])
    assert [status for status, _ in results].count("ok") == 1
    assert [status for status, _ in results].count("error") == 1
    assert "تعارض" in next(message for status, message in results if status == "error")
    with pg_app.app_context():
        assert ClinicAppointment.query.filter_by(tenant_id=501).count() == 1


def test_postgresql_visit_completion_and_invoice_numbers_are_idempotent(pg_app):
    from modules.clinics import service
    from modules.clinics.models import ClinicInvoice
    from modules.clinics.service_ops import complete_visit_extended

    with pg_app.app_context():
        doctor = service.create_doctor(502, {"full_name": "طبيب الفاتورة"})
        patient = service.create_patient(502, {"full_name": "مريض الفاتورة"})
        visit = service.create_walkin_visit(502, {"doctor_id": doctor["id"], "patient_id": patient["id"]})
        db.session.commit()
        visit_id = visit["id"]

    results = _run_parallel(pg_app, [
        lambda: complete_visit_extended(502, visit_id, auto_invoice=True, create_followup=False),
        lambda: complete_visit_extended(502, visit_id, auto_invoice=True, create_followup=False),
    ])
    assert all(status == "ok" for status, _ in results)
    with pg_app.app_context():
        assert ClinicInvoice.query.filter_by(tenant_id=502, visit_id=visit_id).count() == 1

        # Concurrently complete two other visits; tenant invoice numbering must
        # remain unique even when both requests calculate a number at once.
        visit_a = service.create_walkin_visit(502, {"doctor_id": doctor["id"], "patient_id": patient["id"]})
        visit_b = service.create_walkin_visit(502, {"doctor_id": doctor["id"], "patient_id": patient["id"]})
        db.session.commit()
        ids = (visit_a["id"], visit_b["id"])
    results = _run_parallel(pg_app, [
        lambda: complete_visit_extended(502, ids[0], auto_invoice=True, create_followup=False),
        lambda: complete_visit_extended(502, ids[1], auto_invoice=True, create_followup=False),
    ])
    assert all(status == "ok" for status, _ in results)
    with pg_app.app_context():
        numbers = [row.invoice_number for row in ClinicInvoice.query.filter_by(tenant_id=502).all()]
        assert len(numbers) == 3
        assert len(set(numbers)) == 3


def test_postgresql_concurrent_payments_cannot_overpay(pg_app):
    from modules.clinics import service
    from modules.clinics.models import ClinicInvoice, ClinicPayment

    with pg_app.app_context():
        doctor = service.create_doctor(503, {"full_name": "طبيب الدفع"})
        patient = service.create_patient(503, {"full_name": "مريض الدفع"})
        visit = service.create_walkin_visit(503, {"doctor_id": doctor["id"], "patient_id": patient["id"]})
        service.complete_visit(503, visit["id"], auto_invoice=True)
        inv = ClinicInvoice.query.filter_by(tenant_id=503, visit_id=visit["id"]).one()
        inv.total = 100000
        inv.subtotal = 100000
        inv.paid = 0
        inv.balance = 100000
        inv.status = "unpaid"
        invoice_id = inv.id
        db.session.commit()

    payload = {"amount": 100000, "method": "cash"}
    results = _run_parallel(pg_app, [
        lambda: service.receive_payment(503, invoice_id, payload),
        lambda: service.receive_payment(503, invoice_id, payload),
    ])
    assert [status for status, _ in results].count("ok") == 1
    assert [status for status, _ in results].count("error") == 1
    with pg_app.app_context():
        inv = ClinicInvoice.query.filter_by(tenant_id=503, id=invoice_id).one()
        assert float(inv.paid) == 100000
        assert float(inv.balance) == 0
        assert ClinicPayment.query.filter_by(tenant_id=503, invoice_id=invoice_id).count() == 1


def test_postgresql_concurrent_procedure_inventory_never_goes_negative(pg_app):
    """Stock=1; two procedure completions that each need 1 → one wins, stock stays >= 0."""
    from decimal import Decimal

    from modules.clinics import service
    from modules.clinics.models import (
        ClinicInventoryItem,
        ClinicInventoryMovement,
        ClinicProcedure,
        ClinicProcedureRecipeItem,
        ClinicVisitProcedure,
    )
    from modules.clinics.service_clinical_ops import transition_execution
    from modules.clinics.service_ops import create_inventory_item

    with pg_app.app_context():
        doctor = service.create_doctor(504, {"full_name": "طبيب إجراء"})
        patient = service.create_patient(504, {"full_name": "مريض إجراء"})
        visit_a = service.create_walkin_visit(504, {"doctor_id": doctor["id"], "patient_id": patient["id"]})
        visit_b = service.create_walkin_visit(504, {"doctor_id": doctor["id"], "patient_id": patient["id"]})
        item = create_inventory_item(
            504,
            {"name": "مادة نادرة", "sku": "PROC-1", "purchase_price": 1000, "selling_price": 1000, "current_stock": 1},
        )
        proc = ClinicProcedure(
            tenant_id=504,
            name="إجراء يستهلك وحدة",
            price=5000,
            consumes_inventory=True,
            active=True,
        )
        db.session.add(proc)
        db.session.flush()
        db.session.add(
            ClinicProcedureRecipeItem(
                tenant_id=504,
                procedure_id=proc.id,
                item_id=item["id"],
                quantity=Decimal("1"),
            )
        )
        exec_a = ClinicVisitProcedure(
            tenant_id=504,
            visit_id=visit_a["id"],
            patient_id=patient["id"],
            doctor_id=doctor["id"],
            procedure_id=proc.id,
            status="in_progress",
            quantity=Decimal("1"),
            price=5000,
        )
        exec_b = ClinicVisitProcedure(
            tenant_id=504,
            visit_id=visit_b["id"],
            patient_id=patient["id"],
            doctor_id=doctor["id"],
            procedure_id=proc.id,
            status="in_progress",
            quantity=Decimal("1"),
            price=5000,
        )
        db.session.add_all([exec_a, exec_b])
        db.session.commit()
        ids = (exec_a.id, exec_b.id)
        item_id = item["id"]

    results = _run_parallel(
        pg_app,
        [
            lambda: transition_execution(504, ids[0], {"status": "completed", "expected_status": "in_progress"}),
            lambda: transition_execution(504, ids[1], {"status": "completed", "expected_status": "in_progress"}),
        ],
    )
    assert [status for status, _ in results].count("ok") == 1
    assert [status for status, _ in results].count("error") == 1
    with pg_app.app_context():
        stock = ClinicInventoryItem.query.filter_by(tenant_id=504, id=item_id).one()
        assert float(stock.current_stock) == 0
        assert float(stock.current_stock) >= 0
        movements = ClinicInventoryMovement.query.filter_by(
            tenant_id=504, item_id=item_id, movement_type="out"
        ).count()
        assert movements == 1
        completed = ClinicVisitProcedure.query.filter_by(tenant_id=504, status="completed").count()
        assert completed == 1


def test_postgresql_procedure_inventory_consume_is_idempotent(pg_app):
    from decimal import Decimal

    from modules.clinics import service
    from modules.clinics.models import (
        ClinicInventoryItem,
        ClinicInventoryMovement,
        ClinicProcedure,
        ClinicProcedureRecipeItem,
        ClinicVisitProcedure,
    )
    from modules.clinics.service_clinical_ops import transition_execution
    from modules.clinics.service_ops import create_inventory_item

    with pg_app.app_context():
        doctor = service.create_doctor(505, {"full_name": "طبيب إعادة"})
        patient = service.create_patient(505, {"full_name": "مريض إعادة"})
        visit = service.create_walkin_visit(505, {"doctor_id": doctor["id"], "patient_id": patient["id"]})
        item = create_inventory_item(
            505,
            {"name": "مادة", "sku": "PROC-IDEM", "purchase_price": 500, "current_stock": 5},
        )
        proc = ClinicProcedure(tenant_id=505, name="إجراء", price=1000, consumes_inventory=True, active=True)
        db.session.add(proc)
        db.session.flush()
        db.session.add(
            ClinicProcedureRecipeItem(
                tenant_id=505, procedure_id=proc.id, item_id=item["id"], quantity=Decimal("1")
            )
        )
        execution = ClinicVisitProcedure(
            tenant_id=505,
            visit_id=visit["id"],
            patient_id=patient["id"],
            doctor_id=doctor["id"],
            procedure_id=proc.id,
            status="in_progress",
            quantity=Decimal("1"),
            price=1000,
        )
        db.session.add(execution)
        db.session.commit()
        execution_id = execution.id
        item_id = item["id"]

    first = _run_parallel(
        pg_app,
        [lambda: transition_execution(505, execution_id, {"status": "completed", "expected_status": "in_progress"})],
    )
    assert first[0][0] == "ok"
    # Retry completing the same execution must not consume again.
    with pg_app.app_context():
        row = ClinicVisitProcedure.query.filter_by(tenant_id=505, id=execution_id).one()
        row.status = "in_progress"
        row.inventory_deducted = True  # already consumed
        db.session.commit()
    second = _run_parallel(
        pg_app,
        [lambda: transition_execution(505, execution_id, {"status": "completed", "expected_status": "in_progress"})],
    )
    assert second[0][0] == "ok"
    with pg_app.app_context():
        stock = ClinicInventoryItem.query.filter_by(tenant_id=505, id=item_id).one()
        assert float(stock.current_stock) == 4
        assert ClinicInventoryMovement.query.filter_by(
            tenant_id=505, reference_type="visit_procedure", reference_id=execution_id
        ).count() == 1


def test_postgresql_dental_treatment_plan_tables_and_concurrent_link(pg_app):
    from modules.clinics import schema, service
    from modules.clinics.models import (
        ClinicDentalTreatmentPlanItemLink,
        ClinicProcedure,
    )
    from modules.clinics.service_dental_treatment import (
        add_plan_item,
        create_plan,
        link_item_procedure,
    )
    from modules.clinics.service_ops import add_visit_procedure
    from modules.clinics.service_specialties import seed_default_specialties

    with pg_app.app_context():
        schema.clear_clinics_schema_cache()
        schema.ensure_clinics_schema()
        schema.clear_clinics_schema_cache()
        schema.ensure_clinics_schema()
        inspector = inspect(db.engine)
        assert inspector.has_table("clinic_dental_treatment_plan")
        assert inspector.has_table("clinic_dental_treatment_plan_item")
        assert inspector.has_table("clinic_dental_treatment_plan_item_link")
        assert inspector.has_table("clinic_dental_record")
        # Phase D pediatric tables must coexist with dental data after double ensure.
        assert inspector.has_table("clinic_pediatric_profile")
        assert inspector.has_table("clinic_pediatric_vaccination")
        assert inspector.has_table("clinic_pediatric_development")
        vital_cols = {c["name"] for c in inspector.get_columns("clinic_vital")}
        assert "head_circumference_cm" in vital_cols

        specialties = seed_default_specialties(506)
        dentistry = next(row for row in specialties if row["code"] == "dentistry")
        doctor = service.create_doctor(
            506,
            {
                "full_name": "د. خطة",
                "primary_specialty_id": dentistry["id"],
                "specialty_ids": [dentistry["id"]],
            },
        )
        patient = service.create_patient(506, {"full_name": "مريض خطة"})
        visit = service.create_walkin_visit(
            506,
            {
                "patient_id": patient["id"],
                "doctor_id": doctor["id"],
                "specialty_id": dentistry["id"],
            },
        )
        proc = ClinicProcedure(tenant_id=506, name="علاج عصب", price=100000, active=True)
        db.session.add(proc)
        db.session.flush()
        plan = create_plan(
            506, patient["id"], {"status": "active", "created_by_doctor_id": doctor["id"]}
        )
        detail = add_plan_item(
            506,
            plan["plan"]["id"],
            {"tooth_number": "16", "procedure_id": proc.id, "estimated_sessions": 2},
        )
        procs = add_visit_procedure(506, visit["id"], {"procedure_id": proc.id, "price": 100000})
        db.session.commit()
        item_id = detail["items"][0]["id"]
        vp_id = procs[0]["id"]

    results = _run_parallel(
        pg_app,
        [
            lambda: link_item_procedure(506, item_id, vp_id),
            lambda: link_item_procedure(506, item_id, vp_id),
        ],
    )
    assert all(status == "ok" for status, _ in results)
    with pg_app.app_context():
        assert ClinicDentalTreatmentPlanItemLink.query.filter_by(
            tenant_id=506, treatment_plan_item_id=item_id, visit_procedure_id=vp_id
        ).count() == 1
