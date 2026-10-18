"""Cheap, patient-data-free facts about the tenant used by tutorial dependencies and titles."""
from __future__ import annotations

FACT_NAMES = (
    "doctors_count", "specialties_count", "patients_count",
    "appointments_scheduled_today", "appointments_arrived_today", "appointments_waiting_today",
    "open_visits_count", "treatment_items_count", "staff_accounts_count",
    "dentistry_active", "payable_invoices_count", "refundable_invoices_count",
)
SCHEDULED_STATUSES = ("pending", "confirmed", "scheduled")  # not arrived yet
# A tutorial's `availability.required_specialty` is normalized through this map, then checked as fact `<code>_active`.
SPECIALTY_ALIASES = {"dental": "dentistry", "dentistry": "dentistry"}
OPERATORS = {
    "eq": lambda a, b: a == b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
}


def collect_facts(tenant_id: int) -> dict[str, int]:
    from datetime import date

    from modules.clinics.models import ClinicAppointment, ClinicDoctor, ClinicInvoice, ClinicPatient, ClinicSpecialty, ClinicVisit
    from models.employee import Employee
    from modules.clinics.models import ClinicDentalTreatmentPlanItem

    def today_count(*statuses: str) -> int:
        return ClinicAppointment.query.filter(
            ClinicAppointment.tenant_id == tenant_id, ClinicAppointment.appointment_date == date.today(),
            ClinicAppointment.status.in_(statuses)).count()

    return {
        "doctors_count": ClinicDoctor.query.filter_by(tenant_id=tenant_id, active=True).count(),
        "specialties_count": ClinicSpecialty.query.filter_by(tenant_id=tenant_id, is_active=True).count(),
        "patients_count": ClinicPatient.query.filter(ClinicPatient.tenant_id == tenant_id, ClinicPatient.status != "archived").count(),
        "appointments_scheduled_today": today_count(*SCHEDULED_STATUSES),
        "appointments_arrived_today": today_count("arrived"),
        "appointments_waiting_today": today_count("waiting"),
        "staff_accounts_count": Employee.query.filter(
            Employee.tenant_id == tenant_id, Employee.is_active.is_(True), Employee.role.like("clinic\_%", escape="\\")).count(),
        "open_visits_count": ClinicVisit.query.filter_by(tenant_id=tenant_id, status="open").count(),
        "treatment_items_count": ClinicDentalTreatmentPlanItem.query.filter(
            ClinicDentalTreatmentPlanItem.tenant_id == tenant_id, ClinicDentalTreatmentPlanItem.archived_at.is_(None),
            ClinicDentalTreatmentPlanItem.status != "cancelled").count(),
        "dentistry_active": int(ClinicSpecialty.query.filter(
            ClinicSpecialty.tenant_id == tenant_id, ClinicSpecialty.is_active.is_(True),
            ClinicSpecialty.code.in_(("dentistry", "dental"))).count() > 0),
        # An invoice that can actually take a payment right now: real money owed, not void/cancelled.
        "payable_invoices_count": ClinicInvoice.query.filter(
            ClinicInvoice.tenant_id == tenant_id, ClinicInvoice.balance > 0,
            ClinicInvoice.status.notin_(("void", "cancelled"))).count(),
        # An invoice with money already paid on it, so a refund has something real to give back.
        "refundable_invoices_count": ClinicInvoice.query.filter(
            ClinicInvoice.tenant_id == tenant_id, ClinicInvoice.paid > 0).count(),
    }


def fact_met(rule: dict, facts: dict[str, int]) -> bool:
    """`rule` = {"name": fact, "op": eq|gt|gte|lt, "value": int}."""
    return OPERATORS[rule["op"]](int(facts[rule["name"]]), int(rule["value"]))
