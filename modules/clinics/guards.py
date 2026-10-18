"""Business-type and permission guards for Finora Clinics."""

from __future__ import annotations



from functools import wraps
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, with_loader_criteria
from flask import has_request_context



from flask import g, jsonify, redirect, request, session



from extensions import db

from models.employee import Employee

from models.tenant import Tenant



BUSINESS_TYPE = "clinics"



CLINICS_PERMISSIONS = (

    "clinics_dashboard",

    "clinics_reception",

    "clinics_appointments",

    "clinics_patients",

    "clinics_visits",

    "clinics_clinical",
    "clinics_clinical_shared_read",

    "clinics_billing",

    "clinics_inventory",

    "clinics_admin",

    "clinics_reports",

    "clinics_settings",
    "clinics_communications_view",
    "clinics_communications_reply",
    "clinics_communications_assign",
    "clinics_communications_close",
    "clinics_booking_requests_view",
    "clinics_booking_requests_approve",
    "clinics_booking_settings_manage",
    "clinics_reminders_view",
    "clinics_reminders_manage",
    "clinics_templates_manage",
    "clinics_whatsapp_manage",
    "clinics_patient_contact_sensitive_view",
)



CLINICS_PURCHASE_PERMISSIONS = (

    "purchases.view",

    "purchases.create",

    "purchases.edit",

    "purchases.approve",

    "purchases.cancel",

    "purchases.receive",

    "purchases.return",

    "purchases.payment.create",

    "purchases.payment.view",

    "purchases.cost.view",

    "purchases.export",

    "purchase_request.create",

    "purchase_request.approve",

)



CLINICS_PERMISSION_FALLBACKS = {

    "clinics_communications_view": "clinics_settings",
    "clinics_communications_reply": "clinics_reception",
    "clinics_communications_assign": "clinics_reception",
    "clinics_communications_close": "clinics_reception",
    "clinics_booking_requests_view": "clinics_appointments",
    "clinics_booking_requests_approve": "clinics_reception",
    "clinics_booking_settings_manage": "clinics_settings",
    "clinics_reminders_view": "clinics_settings",
    "clinics_reminders_manage": "clinics_settings",
    "clinics_templates_manage": "clinics_settings",
    "clinics_whatsapp_manage": "clinics_settings",
    "clinics_patient_contact_sensitive_view": "clinics_patients",
    # Dental permissions are independently assignable. Existing clinic roles
    # inherit their previous capabilities during the compatibility period.
    "dental.view": "clinics_clinical",
    "dental.chart.view": "clinics_clinical",
    "dental.chart.edit": "clinics_clinical",
    "dental.treatment_plan.view": "clinics_clinical",
    "dental.treatment_plan.create": "clinics_clinical",
    "dental.treatment_plan.edit": "clinics_clinical",
    "dental.treatment_plan.delete": "clinics_clinical",
    "dental.treatment_plan.approve": "clinics_clinical",
    "dental.sessions.view": "clinics_clinical",
    "dental.sessions.create": "clinics_clinical",
    "dental.sessions.edit": "clinics_clinical",
    "dental.sessions.complete": "clinics_clinical",
    "dental.images.view": "clinics_clinical",
    "dental.images.upload": "clinics_clinical",
    "dental.images.delete": "clinics_clinical",
    "dental.reports.view": "clinics_reports",

    "purchases.view": "clinics_inventory",

    "purchases.create": "clinics_inventory",

    "purchases.edit": "clinics_inventory",

    "purchases.approve": "clinics_inventory",

    "purchases.cancel": "clinics_inventory",

    "purchases.receive": "clinics_inventory",

    "purchases.return": "clinics_inventory",

    "purchases.payment.create": "clinics_inventory",

    "purchases.payment.view": "purchases.payment.create",

    # cost_finance stays explicit — never inherit from clinics_inventory alone
    "purchases.export": "clinics_inventory",

    "purchase_request.create": "clinics_inventory",

    "purchase_request.approve": "clinics_inventory",

}





def tenant_business_type() -> str:

    try:

        row = Tenant.query.first()

        if row and getattr(row, "business_type", None):

            return str(row.business_type).strip()

    except Exception:

        db.session.rollback()

    return str(session.get("business_type") or "general").strip()





def is_clinics_tenant() -> bool:

    return tenant_business_type() == BUSINESS_TYPE





def current_employee() -> Employee | None:

    employee_id = session.get("user_id")

    return db.session.get(Employee, employee_id) if employee_id else None





def current_tenant_id() -> int:

    value = session.get("tenant_id")

    try:

        if value is not None:

            return int(value)

    except (TypeError, ValueError):

        pass

    row = Tenant.query.first()

    return int(row.id) if row else 1





def current_branch_id() -> int | None:

    value = session.get("branch_id")

    try:

        if value is not None:

            return int(value)

    except (TypeError, ValueError):

        pass

    return None





def can_use_clinics(permission: str | None = None) -> bool:

    employee = current_employee()

    if not employee or not employee.is_active:

        return False

    if employee.role == "admin":

        return True

    if not permission:

        return True

    if employee.has_permission(permission):

        return True

    fallback = CLINICS_PERMISSION_FALLBACKS.get(permission)

    return bool(fallback and employee.has_permission(fallback))





def clinics_purchase_permissions() -> dict[str, bool]:

    return {

        "view": can_use_clinics("purchases.view"),

        "create": can_use_clinics("purchases.create"),

        "edit": can_use_clinics("purchases.edit"),

        "approve": can_use_clinics("purchases.approve"),

        "cancel": can_use_clinics("purchases.cancel"),

        "receive": can_use_clinics("purchases.receive"),

        "return": can_use_clinics("purchases.return"),

        "pay": can_use_clinics("purchases.payment.create"),

        "payment_view": can_use_clinics("purchases.payment.view"),

        "cost_view": can_use_clinics("purchases.cost.view"),

        "export": can_use_clinics("purchases.export"),

        "request_create": can_use_clinics("purchase_request.create"),

        "request_approve": can_use_clinics("purchase_request.approve"),

    }





def clinics_guard_response(json_mode: bool = False):

    if not is_clinics_tenant():

        message = "هذه المساحة مخصصة لنشاط العيادات والمراكز الطبية."

        return (jsonify({"ok": False, "error": message}), 403) if json_mode else redirect("/")

    return None





def require_clinics(permission: str | None = None, *, json_mode: bool = False):

    def decorator(fn):

        @wraps(fn)

        def wrapped(*args, **kwargs):

            denied = clinics_guard_response(json_mode=json_mode)

            if denied:

                return denied

            if not can_use_clinics(permission):

                message = "ليس لديك صلاحية لهذه العملية."

                return (

                    (jsonify({"ok": False, "error": message}), 403)

                    if json_mode

                    else redirect("/clinics/")

                )

            g.clinics_employee = current_employee()

            g.clinics_tenant_id = current_tenant_id()

            g.clinics_branch_id = current_branch_id()

            doctor = get_current_clinic_doctor()
            employee = g.clinics_employee
            restricted = doctor is not None and employee.role != "admin" and not employee.has_permission("clinics_admin")
            # Shared patient demographics do not grant access to other doctors'
            # encounter notes. Broader history access is explicit and read-only.
            shared_read = (request.method == "GET" and fn.__name__ == "api_clinical_record"
                           and employee.has_permission("clinics_clinical_shared_read"))
            g.clinics_doctor_scope = doctor.id if restricted and not shared_read else None
            if restricted:
                payload = request.get_json(silent=True) if request.is_json else request.form
                payload = payload if isinstance(payload, dict) or hasattr(payload, "get") else {}
                target = payload.get("doctor_id") or (request.view_args or {}).get("doctor_id")
                if target and str(target) != str(doctor.id):
                    return jsonify({"ok": False, "error": "لا يمكنك تعديل عمل طبيب آخر"}), 403
                for key, model in _scoped_route_models().items():
                    value = kwargs.get(key) or payload.get(key)
                    if value and not model.query.filter_by(tenant_id=g.clinics_tenant_id, id=value, doctor_id=doctor.id).first():
                        return jsonify({"ok": False, "error": "السجل غير متاح لهذا الطبيب"}), 403

            return fn(*args, **kwargs)

        # Introspection hook for the AI Tutor system analyzer (permission <-> endpoint map).
        wrapped.clinics_permission = permission

        return wrapped



    return decorator


def get_current_clinic_doctor():
    """Resolve the authenticated employee link, never names or email addresses."""
    from modules.clinics.models import ClinicDoctor
    employee = current_employee()
    if not employee or not employee.is_active:
        return None
    return ClinicDoctor.query.filter_by(tenant_id=current_tenant_id(), employee_id=employee.id, active=True).first()


def _scoped_route_models():
    from modules.clinics.models import ClinicAppointment, ClinicVisit, ClinicFollowUp
    return {"appointment_id": ClinicAppointment, "visit_id": ClinicVisit, "followup_id": ClinicFollowUp}


@event.listens_for(Session, "do_orm_execute")
def _scope_clinic_operational_queries(execute_state):
    if not has_request_context() or not getattr(g, "clinics_doctor_scope", None):
        return
    if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
        return
    from modules.clinics.models import ClinicAppointment, ClinicVisit, ClinicFollowUp, ClinicLabOrder, ClinicRadiologyOrder
    doctor_id = g.clinics_doctor_scope
    tenant_id = g.clinics_tenant_id
    for model in (ClinicAppointment, ClinicVisit, ClinicFollowUp, ClinicLabOrder, ClinicRadiologyOrder):
        execute_state.statement = execute_state.statement.options(with_loader_criteria(
            model, (model.doctor_id == doctor_id) & (model.tenant_id == tenant_id), include_aliases=True))
    # Child entities can be queried without joining their visit (clinical record,
    # attachments, prescription items). Scope these paths as well as parent lists.
    from sqlalchemy import select
    from modules.clinics.models import (
        ClinicDiagnosis, ClinicVital, ClinicPrescription, ClinicPrescriptionItem,
        ClinicAttachment, ClinicVisitProcedure, ClinicVisitFieldValue, ClinicLabOrderItem,
        ClinicDentalRecord, ClinicDentalToothFinding, ClinicDentalToothEvent, ClinicDentalToothProcedure,
        ClinicDentalTreatmentPlan, ClinicDentalTreatmentPlanItem, ClinicDentalTreatmentPlanItemLink,
        ClinicDentalSession, ClinicDentalImage,
        ClinicPediatricDevelopmentRecord, ClinicPregnancyObservation, ClinicPregnancy,
        ClinicChronicCondition, ClinicPatientMedication,
        ClinicCardiologyECG, ClinicCardiologyEcho,
    )
    visits = select(ClinicVisit.id).where(ClinicVisit.tenant_id == tenant_id, ClinicVisit.doctor_id == doctor_id)
    for model in (ClinicDiagnosis, ClinicVital, ClinicPrescription, ClinicAttachment,
                  ClinicVisitProcedure, ClinicVisitFieldValue,
                  ClinicDentalRecord, ClinicDentalToothFinding, ClinicDentalToothEvent, ClinicDentalToothProcedure,
                  ClinicPediatricDevelopmentRecord, ClinicPregnancyObservation,
                  ClinicCardiologyECG, ClinicCardiologyEcho):
        execute_state.statement = execute_state.statement.options(with_loader_criteria(
            model, (model.tenant_id == tenant_id) & model.visit_id.in_(visits), include_aliases=True))
    # Patient-level dental treatment plans: scoped to the creating doctor when restricted.
    execute_state.statement = execute_state.statement.options(with_loader_criteria(
        ClinicDentalTreatmentPlan,
        (ClinicDentalTreatmentPlan.tenant_id == tenant_id)
        & (ClinicDentalTreatmentPlan.created_by_doctor_id == doctor_id),
        include_aliases=True,
    ))
    # Pregnancy episodes created by this doctor (shared-read bypasses this scope).
    execute_state.statement = execute_state.statement.options(with_loader_criteria(
        ClinicPregnancy,
        (ClinicPregnancy.tenant_id == tenant_id)
        & (
            (ClinicPregnancy.created_by_doctor_id == doctor_id)
            | ClinicPregnancy.created_by_doctor_id.is_(None)
        ),
        include_aliases=True,
    ))
    # Chronic conditions / patient meds: creator doctor when restricted.
    execute_state.statement = execute_state.statement.options(with_loader_criteria(
        ClinicChronicCondition,
        (ClinicChronicCondition.tenant_id == tenant_id)
        & (
            (ClinicChronicCondition.created_by_doctor_id == doctor_id)
            | ClinicChronicCondition.created_by_doctor_id.is_(None)
        ),
        include_aliases=True,
    ))
    execute_state.statement = execute_state.statement.options(with_loader_criteria(
        ClinicPatientMedication,
        (ClinicPatientMedication.tenant_id == tenant_id)
        & (
            (ClinicPatientMedication.created_by_doctor_id == doctor_id)
            | ClinicPatientMedication.created_by_doctor_id.is_(None)
        ),
        include_aliases=True,
    ))
    plans = select(ClinicDentalTreatmentPlan.id).where(
        ClinicDentalTreatmentPlan.tenant_id == tenant_id,
        ClinicDentalTreatmentPlan.created_by_doctor_id == doctor_id,
    )
    execute_state.statement = execute_state.statement.options(with_loader_criteria(
        ClinicDentalTreatmentPlanItem,
        (ClinicDentalTreatmentPlanItem.tenant_id == tenant_id)
        & ClinicDentalTreatmentPlanItem.plan_id.in_(plans),
        include_aliases=True,
    ))
    items = select(ClinicDentalTreatmentPlanItem.id).where(
        ClinicDentalTreatmentPlanItem.tenant_id == tenant_id,
        ClinicDentalTreatmentPlanItem.plan_id.in_(plans),
    )
    execute_state.statement = execute_state.statement.options(with_loader_criteria(
        ClinicDentalTreatmentPlanItemLink,
        (ClinicDentalTreatmentPlanItemLink.tenant_id == tenant_id)
        & ClinicDentalTreatmentPlanItemLink.treatment_plan_item_id.in_(items),
        include_aliases=True,
    ))
    execute_state.statement = execute_state.statement.options(with_loader_criteria(
        ClinicDentalSession,
        (ClinicDentalSession.tenant_id == tenant_id) & ClinicDentalSession.plan_id.in_(plans),
        include_aliases=True,
    ))
    execute_state.statement = execute_state.statement.options(with_loader_criteria(
        ClinicDentalImage,
        (ClinicDentalImage.tenant_id == tenant_id) & ClinicDentalImage.visit_id.in_(visits),
        include_aliases=True,
    ))
    prescriptions = select(ClinicPrescription.id).where(
        ClinicPrescription.tenant_id == tenant_id, ClinicPrescription.visit_id.in_(visits))
    orders = select(ClinicLabOrder.id).where(
        ClinicLabOrder.tenant_id == tenant_id, ClinicLabOrder.doctor_id == doctor_id)
    for model, condition in (
        (ClinicPrescriptionItem, ClinicPrescriptionItem.prescription_id.in_(prescriptions)),
        (ClinicLabOrderItem, ClinicLabOrderItem.order_id.in_(orders)),
    ):
        execute_state.statement = execute_state.statement.options(with_loader_criteria(
            model, (model.tenant_id == tenant_id) & condition, include_aliases=True))


@event.listens_for(Session, "before_flush")
def _protect_clinic_operational_writes(session, flush_context, instances):
    if not has_request_context() or not getattr(g, "clinics_doctor_scope", None):
        return
    from modules.clinics.models import (
        ClinicVisit, ClinicAppointment, ClinicFollowUp, ClinicLabOrder, ClinicRadiologyOrder,
        ClinicLabOrderItem, ClinicPrescription, ClinicPrescriptionItem,
        ClinicDentalTreatmentPlan, ClinicDentalTreatmentPlanItem, ClinicDentalTreatmentPlanItemLink,
        ClinicDentalSession, ClinicDentalImage,
        ClinicPregnancy, ClinicChronicCondition, ClinicPatientMedication,
    )
    direct = (ClinicVisit, ClinicAppointment, ClinicFollowUp, ClinicLabOrder, ClinicRadiologyOrder)
    for row in session.new.union(session.dirty).union(session.deleted):
        if isinstance(row, direct):
            original_doctors = inspect(row).attrs.doctor_id.history.deleted
            if original_doctors and original_doctors[0] != g.clinics_doctor_scope:
                raise ValueError("لا يمكنك نقل سجل طبيب آخر إلى نطاقك")
            if row.tenant_id != g.clinics_tenant_id or row.doctor_id != g.clinics_doctor_scope:
                raise ValueError("لا يمكنك تعديل عمل طبيب آخر")
        elif isinstance(row, ClinicDentalTreatmentPlan):
            if row.tenant_id != g.clinics_tenant_id or row.created_by_doctor_id != g.clinics_doctor_scope:
                raise ValueError("لا يمكنك تعديل خطة علاج طبيب آخر")
        elif isinstance(row, ClinicPregnancy):
            if row.tenant_id != g.clinics_tenant_id:
                raise ValueError("سجل الحمل غير متاح")
            if row.created_by_doctor_id not in (None, g.clinics_doctor_scope):
                raise ValueError("لا يمكنك تعديل سجل حمل طبيب آخر")
        elif isinstance(row, (ClinicChronicCondition, ClinicPatientMedication)):
            if row.tenant_id != g.clinics_tenant_id:
                raise ValueError("السجل السريري غير متاح")
            if row.created_by_doctor_id not in (None, g.clinics_doctor_scope):
                raise ValueError("لا يمكنك تعديل سجل طبيب آخر")
        elif isinstance(row, ClinicDentalTreatmentPlanItem):
            if row.tenant_id != g.clinics_tenant_id or not ClinicDentalTreatmentPlan.query.filter_by(
                tenant_id=g.clinics_tenant_id, id=row.plan_id
            ).first():
                raise ValueError("بند خطة العلاج غير متاح لهذا الطبيب")
        elif isinstance(row, ClinicDentalTreatmentPlanItemLink):
            if row.tenant_id != g.clinics_tenant_id or not ClinicDentalTreatmentPlanItem.query.filter_by(
                tenant_id=g.clinics_tenant_id, id=row.treatment_plan_item_id
            ).first():
                raise ValueError("ربط خطة العلاج غير متاح لهذا الطبيب")
        elif isinstance(row, ClinicDentalSession):
            if row.tenant_id != g.clinics_tenant_id or not ClinicDentalTreatmentPlan.query.filter_by(
                tenant_id=g.clinics_tenant_id, id=row.plan_id
            ).first():
                raise ValueError("جلسة الأسنان غير متاحة لهذا الطبيب")
        elif isinstance(row, ClinicDentalImage):
            if row.tenant_id != g.clinics_tenant_id:
                raise ValueError("صورة الأسنان غير متاحة لهذا الطبيب")
            if row.visit_id and not ClinicVisit.query.filter_by(
                tenant_id=g.clinics_tenant_id, id=row.visit_id
            ).first():
                raise ValueError("صورة الأسنان غير متاحة لهذا الطبيب")
        elif isinstance(row, ClinicLabOrderItem):
            if not ClinicLabOrder.query.filter_by(tenant_id=g.clinics_tenant_id, id=row.order_id).first():
                raise ValueError("طلب التحليل غير متاح لهذا الطبيب")
        elif isinstance(row, ClinicPrescriptionItem):
            if row.tenant_id != g.clinics_tenant_id or not ClinicPrescription.query.filter_by(tenant_id=g.clinics_tenant_id, id=row.prescription_id).first():
                raise ValueError("الوصفة غير متاحة لهذا الطبيب")
        elif getattr(row, "__tablename__", "").startswith("clinic_") and getattr(row, "visit_id", None):
            if not ClinicVisit.query.filter_by(tenant_id=g.clinics_tenant_id, id=row.visit_id).first():
                raise ValueError("الزيارة غير متاحة لهذا الطبيب")


