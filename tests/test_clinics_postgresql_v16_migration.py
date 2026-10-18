"""Populated PostgreSQL clinics-v16 → current (v26) migration gate (idempotent twice).

Requires CLINICS_TEST_POSTGRES_URL pointing at a disposable database.
This is a release blocker: synthetic empty-schema checks are not enough.
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy import inspect, text

from extensions import db


def _url():
    return os.environ.get("CLINICS_TEST_POSTGRES_URL")


@pytest.fixture(scope="module")
def pg_migration_app():
    url = _url()
    if not url:
        pytest.skip("CLINICS_TEST_POSTGRES_URL is required for populated v16→v20 migration")
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        SECRET_KEY="clinics-pg-v16-migration",
    )
    db.init_app(app)
    import models  # noqa: F401
    from models.delivery_agent import DeliveryAgent  # noqa: F401
    from modules.clinics.models import CLINIC_MODELS  # noqa: F401

    with app.app_context():
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


POST_V16_TABLES = (
    "clinic_prescription_template_item",
    "clinic_prescription_template",
    "clinic_procedure_specialty",
    "clinic_doctor_service",
    "clinic_service_specialty",
    "clinic_visit_field_value",
    "clinic_visit_template_field",
    "clinic_visit_template_section",
    "clinic_visit_template",
    "clinic_doctor_specialty",
    "clinic_specialty",
)


def _snapshot(tenant_id: int) -> dict:
    from modules.clinics.models import (
        ClinicAppointment,
        ClinicAttachment,
        ClinicDoctor,
        ClinicExpense,
        ClinicFollowUp,
        ClinicInventoryItem,
        ClinicInventoryMovement,
        ClinicInvoice,
        ClinicLabOrder,
        ClinicPatient,
        ClinicPayment,
        ClinicPrescription,
        ClinicPurchase,
        ClinicRadiologyOrder,
        ClinicRefund,
        ClinicVisit,
        ClinicVital,
        ClinicCashSession,
        ClinicBookingRequest,
        ClinicSpecialty,
        ClinicDoctorSpecialty,
        ClinicServiceSpecialty,
        ClinicDoctorService,
        ClinicProcedureSpecialty,
        ClinicVisitTemplate,
        ClinicVisitFieldValue,
    )

    def count(model):
        return model.query.filter_by(tenant_id=tenant_id).count()

    invoices = ClinicInvoice.query.filter_by(tenant_id=tenant_id).all()
    payments = ClinicPayment.query.filter_by(tenant_id=tenant_id).all()
    inventory = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id).all()
    return {
        "patient_count": count(ClinicPatient),
        "doctor_count": count(ClinicDoctor),
        "appointment_count": count(ClinicAppointment),
        "visit_count": count(ClinicVisit),
        "vital_count": count(ClinicVital),
        "prescription_count": count(ClinicPrescription),
        "invoice_count": count(ClinicInvoice),
        "payment_count": count(ClinicPayment),
        "refund_count": count(ClinicRefund),
        "expense_count": count(ClinicExpense),
        "cash_session_count": count(ClinicCashSession),
        "lab_order_count": count(ClinicLabOrder),
        "radiology_order_count": count(ClinicRadiologyOrder),
        "followup_count": count(ClinicFollowUp),
        "inventory_item_count": count(ClinicInventoryItem),
        "inventory_movement_count": count(ClinicInventoryMovement),
        "purchase_count": count(ClinicPurchase),
        "attachment_count": count(ClinicAttachment),
        "booking_request_count": count(ClinicBookingRequest),
        "invoice_total": float(sum(Decimal(str(i.total or 0)) for i in invoices)),
        "payment_total": float(sum(Decimal(str(p.amount or 0)) for p in payments)),
        "inventory_qty_total": float(sum(Decimal(str(i.current_stock or 0)) for i in inventory)),
        "specialty_count": count(ClinicSpecialty),
        "doctor_specialty_count": count(ClinicDoctorSpecialty),
        "service_specialty_count": count(ClinicServiceSpecialty),
        "doctor_service_count": count(ClinicDoctorService),
        "procedure_specialty_count": count(ClinicProcedureSpecialty),
        "visit_template_count": count(ClinicVisitTemplate),
        "visit_field_value_count": count(ClinicVisitFieldValue),
    }


def _downgrade_to_v16_shape():
    """Remove post-v16 specialty objects so migrate_legacy_specialties must rebuild them."""
    with db.engine.begin() as connection:
        for table in POST_V16_TABLES:
            connection.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
        # Clear specialty pointers that would not exist on v16 rows.
        connection.execute(text("UPDATE clinic_appointment SET specialty_id = NULL WHERE specialty_id IS NOT NULL"))
        connection.execute(
            text(
                "UPDATE clinic_visit SET specialty_id = NULL, visit_template_id = NULL "
                "WHERE specialty_id IS NOT NULL OR visit_template_id IS NOT NULL"
            )
        )
        # Force organization_mode re-derivation from legacy clinic_type where relevant.
        connection.execute(
            text(
                "UPDATE clinic_settings SET organization_mode = 'solo_clinic', specialty_pack_seeded = FALSE"
            )
        )
        # Clear the one-time migration marker so the v17 specialty migrator runs again.
        connection.execute(
            text(
                "DELETE FROM clinic_audit_log WHERE action = 'specialties_v17_migrated'"
            )
        )


def _seed_populated_v16(tenant_id: int = 1) -> dict:
    """Seed realistic pre-specialty business data using legacy clinic_type / doctor.specialty text."""
    from modules.clinics.models import (
        ClinicAppointment,
        ClinicAttachment,
        ClinicCashSession,
        ClinicDoctor,
        ClinicExpense,
        ClinicFollowUp,
        ClinicInventoryBatch,
        ClinicInventoryItem,
        ClinicInventoryMovement,
        ClinicInvoice,
        ClinicInvoiceItem,
        ClinicLabOrder,
        ClinicLabTest,
        ClinicPatient,
        ClinicPayment,
        ClinicPrescription,
        ClinicPrescriptionItem,
        ClinicProcedure,
        ClinicPurchase,
        ClinicRadiologyOrder,
        ClinicRefund,
        ClinicRoom,
        ClinicService,
        ClinicSettings,
        ClinicVisit,
        ClinicVital,
        ClinicBookingRequest,
        ClinicConversation,
        ClinicConversationMessage,
        ClinicDiagnosis,
        ClinicSupplier,
    )

    day = date.today() - timedelta(days=3)
    settings = ClinicSettings(
        tenant_id=tenant_id,
        clinic_type="dental",
        organization_mode="solo_clinic",
        clinic_name="عيادة ترحيل v16",
        allow_online_booking=True,
        specialty_pack_seeded=False,
    )
    db.session.add(settings)

    doctors = []
    for name, specialty in (
        ("د. أسنان قديم", "الأسنان"),
        ("د. أطفال قديم", "الأطفال"),
        ("د. جلدية قديم", "جلدية"),
    ):
        row = ClinicDoctor(tenant_id=tenant_id, full_name=name, specialty=specialty, active=True, commission_pct=10)
        db.session.add(row)
        doctors.append(row)
    db.session.flush()

    patients = []
    for idx in range(1, 11):
        row = ClinicPatient(
            tenant_id=tenant_id,
            full_name=f"مريض ترحيل {idx}",
            phone=f"0770{idx:07d}",
            file_number=f"P-{idx:04d}",
            allergies="بنسلين" if idx % 3 == 0 else None,
            chronic_conditions="ربو" if idx % 4 == 0 else None,
        )
        db.session.add(row)
        patients.append(row)
    db.session.flush()

    services = []
    for name, price in (("كشف أسنان", 25000), ("حشو", 50000), ("كشف أطفال", 20000)):
        row = ClinicService(tenant_id=tenant_id, name=name, duration_minutes=30, price=price, active=True)
        db.session.add(row)
        services.append(row)
    room = ClinicRoom(tenant_id=tenant_id, name="غرفة 1", active=True)
    db.session.add(room)
    procedure = ClinicProcedure(tenant_id=tenant_id, name="تنظيف لثة", price=40000, active=True)
    lab = ClinicLabTest(tenant_id=tenant_id, name="CBC", price=15000, active=True)
    supplier = ClinicSupplier(tenant_id=tenant_id, name="مورد تجريبي", active=True)
    db.session.add_all([procedure, lab, supplier])
    db.session.flush()

    appointments = []
    for idx, patient in enumerate(patients):
        doctor = doctors[idx % len(doctors)]
        service = services[idx % len(services)]
        appt = ClinicAppointment(
            tenant_id=tenant_id,
            patient_id=patient.id,
            doctor_id=doctor.id,
            service_id=service.id,
            appointment_date=day,
            start_time=time(9 + (idx % 6), 0),
            end_time=time(9 + (idx % 6), 30),
            status="completed" if idx < 7 else "confirmed",
            source="reception",
        )
        db.session.add(appt)
        appointments.append(appt)
    db.session.flush()

    visits = []
    first_invoice = None
    for idx, appt in enumerate(appointments[:7]):
        visit = ClinicVisit(
            tenant_id=tenant_id,
            patient_id=appt.patient_id,
            doctor_id=appt.doctor_id,
            service_id=appt.service_id,
            appointment_id=appt.id,
            visit_date=day,
            status="completed",
            chief_complaint="ألم",
            clinical_notes="ملاحظة سريرية تاريخية",
            completed_at=datetime.utcnow(),
        )
        db.session.add(visit)
        visits.append(visit)
    db.session.flush()

    for visit in visits:
        db.session.add(
            ClinicVital(
                tenant_id=tenant_id,
                visit_id=visit.id,
                patient_id=visit.patient_id,
                weight_kg=70,
                temperature=37,
                blood_pressure="120/80",
            )
        )
        db.session.add(
            ClinicDiagnosis(
                tenant_id=tenant_id,
                visit_id=visit.id,
                patient_id=visit.patient_id,
                title="التهاب لثة",
                code="K05",
            )
        )
        rx = ClinicPrescription(tenant_id=tenant_id, visit_id=visit.id, patient_id=visit.patient_id, doctor_id=visit.doctor_id)
        db.session.add(rx)
        db.session.flush()
        db.session.add(
            ClinicPrescriptionItem(
                tenant_id=tenant_id,
                prescription_id=rx.id,
                medicine_name="أموكسيسيلين",
                dosage="500mg",
                frequency="3x",
                duration="5 أيام",
            )
        )
        inv = ClinicInvoice(
            tenant_id=tenant_id,
            patient_id=visit.patient_id,
            visit_id=visit.id,
            doctor_id=visit.doctor_id,
            invoice_number=f"LEG-{visit.id:05d}",
            invoice_date=day,
            subtotal=50000,
            discount=0,
            total=50000,
            paid=20000,
            balance=30000,
            status="partial",
        )
        db.session.add(inv)
        db.session.flush()
        if first_invoice is None:
            first_invoice = inv
        db.session.add(
            ClinicInvoiceItem(
                tenant_id=tenant_id,
                invoice_id=inv.id,
                description="كشف",
                quantity=1,
                unit_price=50000,
                line_total=50000,
            )
        )
        db.session.add(
            ClinicPayment(
                tenant_id=tenant_id,
                invoice_id=inv.id,
                patient_id=visit.patient_id,
                amount=20000,
                method="cash",
            )
        )
        db.session.add(
            ClinicLabOrder(
                tenant_id=tenant_id,
                visit_id=visit.id,
                patient_id=visit.patient_id,
                doctor_id=visit.doctor_id,
                status="completed",
            )
        )
        db.session.add(
            ClinicRadiologyOrder(
                tenant_id=tenant_id,
                visit_id=visit.id,
                patient_id=visit.patient_id,
                doctor_id=visit.doctor_id,
                status="completed",
                modality="xray",
            )
        )
        db.session.add(
            ClinicFollowUp(
                tenant_id=tenant_id,
                visit_id=visit.id,
                patient_id=visit.patient_id,
                doctor_id=visit.doctor_id,
                due_date=day + timedelta(days=7),
                status="due",
            )
        )
        db.session.add(
            ClinicAttachment(
                tenant_id=tenant_id,
                patient_id=visit.patient_id,
                visit_id=visit.id,
                category="clinical",
                file_name=f"note-{visit.id}.txt",
                stored_name=f"note-{visit.id}.txt",
                mime_type="text/plain",
            )
        )

    item = ClinicInventoryItem(
        tenant_id=tenant_id,
        name="قفازات",
        sku="GLV-1",
        current_stock=100,
        unit="box",
        purchase_price=5000,
        selling_price=7000,
        active=True,
    )
    db.session.add(item)
    db.session.flush()
    db.session.add(
        ClinicInventoryBatch(
            tenant_id=tenant_id,
            item_id=item.id,
            batch_number="B1",
            quantity_received=100,
            quantity_available=100,
            supplier_id=supplier.id,
        )
    )
    db.session.add(
        ClinicInventoryMovement(
            tenant_id=tenant_id,
            item_id=item.id,
            movement_type="in",
            quantity=100,
            notes="رصيد افتتاحي",
        )
    )
    db.session.add(
        ClinicPurchase(
            tenant_id=tenant_id,
            supplier_id=supplier.id,
            purchase_number="PO-LEG-001",
            purchase_date=day,
            subtotal=500000,
            total=500000,
            paid=500000,
            balance=0,
            status="closed",
            payment_status="paid",
            receipt_status="received",
        )
    )
    db.session.add(ClinicExpense(tenant_id=tenant_id, title="إيجار", amount=100000, expense_date=day, category="تشغيل"))
    db.session.add(
        ClinicRefund(
            tenant_id=tenant_id,
            invoice_id=first_invoice.id,
            patient_id=first_invoice.patient_id,
            amount=5000,
            reason="استرداد جزئي",
            method="cash",
        )
    )
    db.session.add(
        ClinicCashSession(
            tenant_id=tenant_id,
            business_date=day,
            opened_at=datetime.utcnow(),
            opening_cash=0,
            status="open",
        )
    )
    db.session.add(
        ClinicBookingRequest(
            tenant_id=tenant_id,
            patient_id=patients[0].id,
            doctor_id=doctors[0].id,
            service_id=services[0].id,
            requested_start=datetime.combine(day + timedelta(days=2), time(10, 0)),
            status="pending_approval",
            source="public_booking",
        )
    )
    conversation = ClinicConversation(
        tenant_id=tenant_id,
        patient_id=patients[0].id,
        channel="whatsapp",
        status="open",
        contact_phone=patients[0].phone,
    )
    db.session.add(conversation)
    db.session.flush()
    db.session.add(
        ClinicConversationMessage(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            direction="incoming",
            content="مرحباً",
        )
    )
    # Completed historical visit without template — must stay unbound after migration.
    hist = ClinicVisit(
        tenant_id=tenant_id,
        patient_id=patients[-1].id,
        doctor_id=doctors[0].id,
        visit_date=day - timedelta(days=30),
        status="completed",
        chief_complaint="زيارة قديمة بلا نموذج",
        completed_at=datetime.utcnow(),
    )
    db.session.add(hist)
    db.session.commit()
    return {"tenant_id": tenant_id, "historical_visit_id": hist.id, "doctor_ids": [d.id for d in doctors]}


def test_populated_v16_to_v20_migration_twice(pg_migration_app):
    from modules.clinics import schema
    from modules.clinics.models import (
        ClinicAppointment,
        ClinicDoctor,
        ClinicDoctorSpecialty,
        ClinicSettings,
        ClinicSpecialty,
        ClinicVisit,
    )

    with pg_migration_app.app_context():
        meta = _seed_populated_v16(1)
        tenant_id = meta["tenant_id"]
        before = _snapshot(tenant_id)
        assert before["patient_count"] == 10
        assert before["doctor_count"] == 3
        assert before["invoice_count"] >= 7
        assert before["payment_total"] > 0
        assert before["specialty_count"] == 0

        # Release ORM locks before DDL drops on a separate connection.
        db.session.rollback()
        db.session.remove()

        _downgrade_to_v16_shape()
        schema.clear_clinics_schema_cache()
        # Recreate current model metadata tables that were dropped, then migrate.
        for model in __import__("modules.clinics.models", fromlist=["CLINIC_MODELS"]).CLINIC_MODELS:
            model.__table__.create(bind=db.engine, checkfirst=True)
        schema.clear_clinics_schema_cache()
        schema.ensure_clinics_schema()
        after_first = _snapshot(tenant_id)

        # Business records preserved.
        for key in (
            "patient_count",
            "doctor_count",
            "appointment_count",
            "visit_count",
            "prescription_count",
            "invoice_count",
            "payment_count",
            "lab_order_count",
            "radiology_order_count",
            "followup_count",
            "inventory_item_count",
            "purchase_count",
            "attachment_count",
            "invoice_total",
            "payment_total",
            "inventory_qty_total",
        ):
            assert after_first[key] == before[key], f"{key}: {before[key]} -> {after_first[key]}"

        settings = ClinicSettings.query.filter_by(tenant_id=tenant_id).one()
        # dental clinic_type must never become medical_center merely from doctor count.
        # Multiple doctors map to multi_doctor_clinic per migrate_legacy_specialties rules.
        assert settings.organization_mode != "medical_center"
        assert settings.organization_mode == "multi_doctor_clinic"

        # Doctor specialty text converted with one primary max.
        for doctor_id in meta["doctor_ids"]:
            links = ClinicDoctorSpecialty.query.filter_by(tenant_id=tenant_id, doctor_id=doctor_id).all()
            assert len(links) >= 1
            assert sum(1 for link in links if link.is_primary) == 1

        assert ClinicSpecialty.query.filter_by(tenant_id=tenant_id).count() >= 1
        assert ClinicSpecialty.query.filter_by(tenant_id=tenant_id).count() == len(
            {row.code for row in ClinicSpecialty.query.filter_by(tenant_id=tenant_id).all()}
        )

        # Inferable appointment specialties filled where doctors had specialty text.
        filled = ClinicAppointment.query.filter(
            ClinicAppointment.tenant_id == tenant_id, ClinicAppointment.specialty_id.isnot(None)
        ).count()
        assert filled >= 1

        hist = ClinicVisit.query.get(meta["historical_visit_id"])
        assert hist.visit_template_id is None

        # Second run must be idempotent.
        schema.clear_clinics_schema_cache()
        settings.organization_mode = "medical_center"
        db.session.commit()
        schema.ensure_clinics_schema()
        after_second = _snapshot(tenant_id)

        for key in (
            "patient_count",
            "doctor_count",
            "appointment_count",
            "visit_count",
            "invoice_count",
            "payment_count",
            "invoice_total",
            "payment_total",
            "inventory_qty_total",
            "specialty_count",
            "doctor_specialty_count",
        ):
            assert after_second[key] == after_first[key], f"idempotency {key}"

        settings = ClinicSettings.query.filter_by(tenant_id=tenant_id).one()
        assert settings.organization_mode == "medical_center"
        hist = ClinicVisit.query.get(meta["historical_visit_id"])
        assert hist.visit_template_id is None

        inspector = inspect(db.engine)
        assert inspector.has_table("clinic_specialty")
        assert inspector.has_table("clinic_doctor_specialty")
        assert inspector.has_table("clinic_visit_template")
        # Phase H — schema chain through v26 clinical packs (additive only).
        for table in (
            "clinic_dental_record",
            "clinic_dental_tooth_event",
            "clinic_dental_treatment_plan",
            "clinic_pediatric_profile",
            "clinic_gynecology_profile",
            "clinic_pregnancy",
            "clinic_chronic_condition",
            "clinic_patient_medication",
            "clinic_cardiology_profile",
            "clinic_cardiology_ecg",
            "clinic_cardiology_echo",
        ):
            assert inspector.has_table(table), f"missing after v16→current migrate: {table}"
        from modules.clinics.schema import SCHEMA_VERSION
        assert SCHEMA_VERSION.startswith("clinics-v")
        indexes = {row["name"] for row in inspector.get_indexes("clinic_invoice")}
        assert {"uq_clinic_invoice_visit", "uq_clinic_invoice_number"} <= indexes
