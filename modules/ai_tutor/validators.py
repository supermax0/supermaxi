"""Server-side checks of real application state (never trust the browser)."""
from __future__ import annotations

from typing import Callable

from modules.ai_tutor.models import UserTrainingProgress


def doctor_created_since_start(tenant_id: int, progress: UserTrainingProgress) -> bool:
    from modules.clinics.models import ClinicDoctor

    if progress.started_at is None:
        return False
    return (
        ClinicDoctor.query.filter(
            ClinicDoctor.tenant_id == tenant_id,
            ClinicDoctor.created_at >= progress.started_at,
        ).count()
        > 0
    )


def specialty_created_since_start(tenant_id: int, progress: UserTrainingProgress) -> bool:
    from modules.clinics.models import ClinicSpecialty

    if progress.started_at is None:
        return False
    return (
        ClinicSpecialty.query.filter(
            ClinicSpecialty.tenant_id == tenant_id,
            ClinicSpecialty.created_at >= progress.started_at,
        ).count()
        > 0
    )


def patient_created_since_start(tenant_id: int, progress: UserTrainingProgress) -> bool:
    from modules.clinics.models import ClinicPatient

    if progress.started_at is None:
        return False
    return (
        ClinicPatient.query.filter(
            ClinicPatient.tenant_id == tenant_id,
            ClinicPatient.created_at >= progress.started_at,
        ).count()
        > 0
    )


def appointment_created_since_start(tenant_id: int, progress: UserTrainingProgress) -> bool:
    from modules.clinics.models import ClinicAppointment

    if progress.started_at is None:
        return False
    return (
        ClinicAppointment.query.filter(
            ClinicAppointment.tenant_id == tenant_id,
            ClinicAppointment.created_at >= progress.started_at,
        ).count()
        > 0
    )


def _status_reached_since_start(tenant_id: int, progress: UserTrainingProgress, status: str) -> bool:
    """An appointment moved INTO `status` after the lesson started (the status history is the server-side proof)."""
    from modules.clinics.models import ClinicAppointmentStatusHistory

    if progress.started_at is None:
        return False
    return (
        ClinicAppointmentStatusHistory.query.filter(
            ClinicAppointmentStatusHistory.tenant_id == tenant_id,
            ClinicAppointmentStatusHistory.to_status == status,
            ClinicAppointmentStatusHistory.changed_at >= progress.started_at,
        ).count()
        > 0
    )


def appointment_checked_in_since_start(tenant_id: int, progress: UserTrainingProgress) -> bool:
    return _status_reached_since_start(tenant_id, progress, "arrived")


def appointment_queued_since_start(tenant_id: int, progress: UserTrainingProgress) -> bool:
    return _status_reached_since_start(tenant_id, progress, "waiting")


def visit_started_since_start(tenant_id: int, progress: UserTrainingProgress) -> bool:
    from modules.clinics.models import ClinicVisit

    if progress.started_at is None:
        return False
    return (
        ClinicVisit.query.filter(
            ClinicVisit.tenant_id == tenant_id,
            ClinicVisit.appointment_id.isnot(None),
            ClinicVisit.created_at >= progress.started_at,
        ).count()
        > 0
    )


def service_created_since_start(tenant_id: int, progress: UserTrainingProgress) -> bool:
    from modules.clinics.models import ClinicService

    if progress.started_at is None:
        return False
    return (
        ClinicService.query.filter(
            ClinicService.tenant_id == tenant_id,
            ClinicService.created_at >= progress.started_at,
        ).count()
        > 0
    )


def treatment_plan_created_since_start(tenant_id: int, progress: UserTrainingProgress) -> bool:
    from modules.clinics.models import ClinicDentalTreatmentPlan

    if progress.started_at is None:
        return False
    return (
        ClinicDentalTreatmentPlan.query.filter(
            ClinicDentalTreatmentPlan.tenant_id == tenant_id,
            ClinicDentalTreatmentPlan.created_at >= progress.started_at,
        ).count()
        > 0
    )


def treatment_item_added_since_start(tenant_id: int, progress: UserTrainingProgress) -> bool:
    from modules.clinics.models import ClinicDentalTreatmentPlanItem

    if progress.started_at is None:
        return False
    return (
        ClinicDentalTreatmentPlanItem.query.filter(
            ClinicDentalTreatmentPlanItem.tenant_id == tenant_id,
            ClinicDentalTreatmentPlanItem.created_at >= progress.started_at,
        ).count()
        > 0
    )


def invoice_created_since_start(tenant_id: int, progress: UserTrainingProgress) -> bool:
    from modules.clinics.models import ClinicInvoice

    if progress.started_at is None:
        return False
    return (
        ClinicInvoice.query.filter(
            ClinicInvoice.tenant_id == tenant_id,
            ClinicInvoice.created_at >= progress.started_at,
        ).count()
        > 0
    )


def employee_created_since_start(tenant_id: int, progress: UserTrainingProgress) -> bool:
    """A NON-doctor staff account created after the lesson started (a doctor account has its own lesson)."""
    from extensions import db
    from models.employee import Employee
    from modules.clinics.models import ClinicDoctor

    if progress.started_at is None:
        return False
    doctor_accounts = db.session.query(ClinicDoctor.employee_id).filter(
        ClinicDoctor.tenant_id == tenant_id, ClinicDoctor.employee_id.isnot(None))
    return (
        Employee.query.filter(
            Employee.tenant_id == tenant_id,
            Employee.created_at >= progress.started_at,
            Employee.role.like("clinic\\_%", escape="\\"),
            Employee.role != "clinic_doctor",
            ~Employee.id.in_(doctor_accounts),
        ).count()
        > 0
    )


def staff_permissions_updated_since_start(tenant_id: int, progress: UserTrainingProgress) -> bool:
    """The clinic audit trail shows a staff account was updated after the lesson started."""
    from modules.clinics.models import ClinicAuditLog

    if progress.started_at is None:
        return False
    return (
        ClinicAuditLog.query.filter(
            ClinicAuditLog.tenant_id == tenant_id,
            ClinicAuditLog.entity_type == "clinic_staff",
            ClinicAuditLog.action == "update",
            ClinicAuditLog.created_at >= progress.started_at,
        ).count()
        > 0
    )


def schedule_created_since_start(tenant_id: int, progress: UserTrainingProgress) -> bool:
    from modules.clinics.models import ClinicDoctorSchedule

    if progress.started_at is None:
        return False
    return (
        ClinicDoctorSchedule.query.filter(
            ClinicDoctorSchedule.tenant_id == tenant_id,
            ClinicDoctorSchedule.created_at >= progress.started_at,
        ).count()
        > 0
    )


def payment_recorded_since_start(tenant_id: int, progress: UserTrainingProgress) -> bool:
    from modules.clinics.models import ClinicPayment

    if progress.started_at is None:
        return False
    return (
        ClinicPayment.query.filter(
            ClinicPayment.tenant_id == tenant_id,
            ClinicPayment.created_at >= progress.started_at,
        ).count()
        > 0
    )


def refund_recorded_since_start(tenant_id: int, progress: UserTrainingProgress) -> bool:
    from modules.clinics.models import ClinicRefund

    if progress.started_at is None:
        return False
    return (
        ClinicRefund.query.filter(
            ClinicRefund.tenant_id == tenant_id,
            ClinicRefund.created_at >= progress.started_at,
        ).count()
        > 0
    )


VALIDATORS: dict[str, Callable[[int, UserTrainingProgress], bool]] = {
    "doctor.created_since_start": doctor_created_since_start,
    "specialty.created_since_start": specialty_created_since_start,
    "patient.created_since_start": patient_created_since_start,
    "appointment.created_since_start": appointment_created_since_start,
    "appointment.checked_in_since_start": appointment_checked_in_since_start,
    "appointment.queued_since_start": appointment_queued_since_start,
    "visit.started_since_start": visit_started_since_start,
    "service.created_since_start": service_created_since_start,
    "treatment_plan.created_since_start": treatment_plan_created_since_start,
    "invoice.created_since_start": invoice_created_since_start,
    "employee.created_since_start": employee_created_since_start,
    "schedule.created_since_start": schedule_created_since_start,
    "staff.permissions_updated_since_start": staff_permissions_updated_since_start,
    "treatment_plan.item_added_since_start": treatment_item_added_since_start,
    "payment.recorded_since_start": payment_recorded_since_start,
    "refund.recorded_since_start": refund_recorded_since_start,
}
