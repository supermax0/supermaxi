"""Clinic workspace models — isolated medical workflow tables."""
from __future__ import annotations

from datetime import date, datetime, time

from extensions import db


class ClinicSettings(db.Model):
    __tablename__ = "clinic_settings"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    clinic_type = db.Column(db.String(60), nullable=False, default="general_practice")
    organization_mode = db.Column(db.String(30), nullable=False, default="solo_clinic")
    clinic_name = db.Column(db.String(200), nullable=True)
    default_currency = db.Column(db.String(10), nullable=False, default="IQD")
    appointment_slot_minutes = db.Column(db.Integer, nullable=False, default=15)
    allow_online_booking = db.Column(db.Boolean, nullable=False, default=False)
    queue_display_enabled = db.Column(db.Boolean, nullable=False, default=True)
    doctor_commission_default_pct = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    doctor_availability_requires_attendance = db.Column(db.Boolean, nullable=False, default=False)
    language = db.Column(db.String(10), nullable=False, default="ar")
    booking_welcome_text = db.Column(db.Text, nullable=True)
    whatsapp_notifications_enabled = db.Column(db.Boolean, nullable=False, default=False)
    default_followup_days = db.Column(db.Integer, nullable=False, default=7)
    reminder_hours_before = db.Column(db.Integer, nullable=False, default=24)
    booking_rate_limit_per_hour = db.Column(db.Integer, nullable=False, default=10)
    booking_otp_enabled = db.Column(db.Boolean, nullable=False, default=False)
    booking_mode = db.Column(db.String(30), nullable=False, default="direct")
    minimum_booking_notice_hours = db.Column(db.Integer, nullable=False, default=2)
    maximum_advance_booking_days = db.Column(db.Integer, nullable=False, default=60)
    allow_same_day_booking = db.Column(db.Boolean, nullable=False, default=True)
    allow_public_reschedule = db.Column(db.Boolean, nullable=False, default=True)
    allow_public_cancellation = db.Column(db.Boolean, nullable=False, default=True)
    cancellation_deadline_hours = db.Column(db.Integer, nullable=False, default=4)
    max_active_appointments_per_patient = db.Column(db.Integer, nullable=False, default=3)
    public_show_prices = db.Column(db.Boolean, nullable=False, default=False)
    clinic_whatsapp_number = db.Column(db.String(40), nullable=True)
    public_profile_enabled = db.Column(db.Boolean, nullable=False, default=True)
    public_chat_enabled = db.Column(db.Boolean, nullable=False, default=True)
    public_logo_url = db.Column(db.String(500), nullable=True)
    public_location = db.Column(db.String(300), nullable=True)
    public_working_hours = db.Column(db.String(300), nullable=True)
    specialty_pack_seeded = db.Column(db.Boolean, nullable=False, default=False)
    display_sound_enabled = db.Column(db.Boolean, nullable=False, default=True)
    display_voice_enabled = db.Column(db.Boolean, nullable=False, default=False)
    display_volume = db.Column(db.Integer, nullable=False, default=70)
    display_show_short_name = db.Column(db.Boolean, nullable=False, default=False)
    display_footer_message = db.Column(db.Text, nullable=True)
    purchase_warn_expiry_days = db.Column(db.Integer, nullable=False, default=90)
    purchase_price_warn_pct = db.Column(db.Integer, nullable=False, default=20)
    purchase_approval_limit = db.Column(db.Integer, nullable=False, default=500000)
    primary_specialty_id = db.Column(db.Integer, db.ForeignKey("clinic_specialty.id"), nullable=True, index=True)
    specialty_features_json = db.Column(db.Text, nullable=True)
    dental_config_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicPatient(db.Model):
    __tablename__ = "clinic_patient"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "file_number", name="uq_clinic_patient_file"),
        db.Index("ix_clinic_patient_phone", "tenant_id", "phone"),
        db.Index("ix_clinic_patient_name", "tenant_id", "full_name"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    file_number = db.Column(db.String(40), nullable=False)
    full_name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(40), nullable=True)
    secondary_phone = db.Column(db.String(40), nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    blood_type = db.Column(db.String(10), nullable=True)
    national_id = db.Column(db.String(60), nullable=True)
    address = db.Column(db.String(300), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    emergency_contact = db.Column(db.String(200), nullable=True)
    emergency_phone = db.Column(db.String(40), nullable=True)
    allergies = db.Column(db.Text, nullable=True)
    chronic_conditions = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicDoctor(db.Model):
    __tablename__ = "clinic_doctor"
    __table_args__ = (
        db.Index("ix_clinic_doctor_name", "tenant_id", "full_name"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    employee_id = db.Column(db.Integer, nullable=True, index=True)
    full_name = db.Column(db.String(200), nullable=False)
    specialty = db.Column(db.String(120), nullable=True)
    photo_url = db.Column(db.String(500), nullable=True)
    scientific_title = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(40), nullable=True)
    license_number = db.Column(db.String(80), nullable=True)
    commission_pct = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    color = db.Column(db.String(20), nullable=True, default="#0D9488")
    active = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicSpecialty(db.Model):
    __tablename__ = "clinic_specialty"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "code", name="uq_clinic_specialty_code"),
        db.Index("ix_clinic_specialty_name", "tenant_id", "name_ar"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    name_ar = db.Column(db.String(160), nullable=False)
    name_en = db.Column(db.String(160), nullable=True)
    code = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(80), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    default_visit_template_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicDoctorSpecialty(db.Model):
    __tablename__ = "clinic_doctor_specialty"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "doctor_id", "specialty_id", name="uq_clinic_doctor_specialty"),
        db.Index("ix_clinic_doctor_specialty_primary", "tenant_id", "doctor_id", "is_primary"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=False, index=True)
    specialty_id = db.Column(db.Integer, db.ForeignKey("clinic_specialty.id"), nullable=False, index=True)
    is_primary = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicRoom(db.Model):
    __tablename__ = "clinic_room"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    room_type = db.Column(db.String(40), nullable=False, default="consultation")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicService(db.Model):
    __tablename__ = "clinic_service"
    __table_args__ = (
        db.Index("ix_clinic_service_name", "tenant_id", "name"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    duration_minutes = db.Column(db.Integer, nullable=False, default=15)
    price = db.Column(db.Integer, nullable=False, default=0)
    doctor_commission_pct = db.Column(db.Numeric(5, 2), nullable=True)
    requires_room = db.Column(db.Boolean, nullable=False, default=False)
    requires_tooth = db.Column(db.Boolean, nullable=False, default=False)
    allows_multiple_teeth = db.Column(db.Boolean, nullable=False, default=False)
    requires_sessions = db.Column(db.Boolean, nullable=False, default=False)
    default_sessions = db.Column(db.Integer, nullable=False, default=1)
    default_procedure_id = db.Column(
        db.Integer, db.ForeignKey("clinic_procedure.id"), nullable=True, index=True
    )
    active = db.Column(db.Boolean, nullable=False, default=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicServiceSpecialty(db.Model):
    __tablename__ = "clinic_service_specialty"
    __table_args__ = (db.UniqueConstraint("tenant_id", "service_id", "specialty_id"),)
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("clinic_service.id"), nullable=False, index=True)
    specialty_id = db.Column(db.Integer, db.ForeignKey("clinic_specialty.id"), nullable=False)


class ClinicDoctorService(db.Model):
    __tablename__ = "clinic_doctor_service"
    __table_args__ = (db.UniqueConstraint("tenant_id", "service_id", "doctor_id"),)
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("clinic_service.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=False)


class ClinicDoctorSchedule(db.Model):
    __tablename__ = "clinic_doctor_schedule"
    __table_args__ = (
        db.Index("ix_clinic_doctor_schedule_day", "tenant_id", "doctor_id", "weekday"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=False, index=True)
    weekday = db.Column(db.Integer, nullable=False)  # 0=Monday … 6=Sunday
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    break_start = db.Column(db.Time, nullable=True)
    break_end = db.Column(db.Time, nullable=True)
    slot_minutes = db.Column(db.Integer, nullable=False, default=15)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicAppointment(db.Model):
    __tablename__ = "clinic_appointment"
    __table_args__ = (
        db.Index("ix_clinic_appt_day", "tenant_id", "appointment_date", "status"),
        db.Index("ix_clinic_appt_doctor", "tenant_id", "doctor_id", "appointment_date"),
        db.Index("ix_clinic_appt_patient", "tenant_id", "patient_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("clinic_service.id"), nullable=True, index=True)
    specialty_id = db.Column(db.Integer, db.ForeignKey("clinic_specialty.id"), nullable=True, index=True)
    specialty_code_snapshot = db.Column(db.String(80), nullable=True, index=True)
    workspace_snapshot = db.Column(db.String(80), nullable=True)
    room_id = db.Column(db.Integer, db.ForeignKey("clinic_room.id"), nullable=True)
    appointment_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=True)
    appointment_type = db.Column(db.String(40), nullable=False, default="visit")
    source = db.Column(db.String(40), nullable=False, default="reception")
    status = db.Column(db.String(30), nullable=False, default="pending", index=True)
    queue_number = db.Column(db.Integer, nullable=True)
    queue_priority = db.Column(db.Integer, nullable=False, default=0)
    payment_status = db.Column(db.String(30), nullable=False, default="unpaid")
    notes = db.Column(db.Text, nullable=True)
    cancelled_reason = db.Column(db.String(255), nullable=True)
    checked_in_at = db.Column(db.DateTime, nullable=True)
    treatment_plan_item_id = db.Column(
        db.Integer, db.ForeignKey("clinic_dental_treatment_plan_item.id"), nullable=True, index=True
    )
    treatment_plan_id = db.Column(
        db.Integer, db.ForeignKey("clinic_dental_treatment_plan.id"), nullable=True, index=True
    )
    dental_session_id = db.Column(
        db.Integer, db.ForeignKey("clinic_dental_session.id"), nullable=True, index=True
    )
    tooth_number = db.Column(db.String(4), nullable=True, index=True)
    tooth_numbers_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)

    patient = db.relationship("ClinicPatient", lazy=True)
    doctor = db.relationship("ClinicDoctor", lazy=True)
    service = db.relationship("ClinicService", lazy=True)
    treatment_plan_item = db.relationship(
        "ClinicDentalTreatmentPlanItem", foreign_keys=[treatment_plan_item_id], lazy=True
    )
    dental_session = db.relationship(
        "ClinicDentalSession", foreign_keys=[dental_session_id], lazy=True
    )


class ClinicAppointmentStatusHistory(db.Model):
    __tablename__ = "clinic_appointment_status_history"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    appointment_id = db.Column(
        db.Integer, db.ForeignKey("clinic_appointment.id"), nullable=False, index=True
    )
    from_status = db.Column(db.String(30), nullable=True)
    to_status = db.Column(db.String(30), nullable=False)
    note = db.Column(db.String(255), nullable=True)
    changed_by = db.Column(db.Integer, nullable=True)
    changed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ClinicVisit(db.Model):
    __tablename__ = "clinic_visit"
    __table_args__ = (
        db.Index("ix_clinic_visit_day", "tenant_id", "visit_date", "status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("clinic_appointment.id"), nullable=True, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("clinic_service.id"), nullable=True)
    specialty_id = db.Column(db.Integer, db.ForeignKey("clinic_specialty.id"), nullable=True, index=True)
    specialty_code_snapshot = db.Column(db.String(80), nullable=True, index=True)
    workspace_snapshot = db.Column(db.String(80), nullable=True)
    visit_template_id = db.Column(db.Integer, db.ForeignKey("clinic_visit_template.id"), nullable=True, index=True)
    room_id = db.Column(db.Integer, db.ForeignKey("clinic_room.id"), nullable=True)
    visit_date = db.Column(db.Date, nullable=False, default=date.today)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="open", index=True)
    chief_complaint = db.Column(db.Text, nullable=True)
    clinical_notes = db.Column(db.Text, nullable=True)
    follow_up_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)

    patient = db.relationship("ClinicPatient", lazy=True)
    doctor = db.relationship("ClinicDoctor", lazy=True)
    appointment = db.relationship("ClinicAppointment", lazy=True)


class ClinicVital(db.Model):
    __tablename__ = "clinic_vital"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    blood_pressure = db.Column(db.String(20), nullable=True)
    heart_rate = db.Column(db.Integer, nullable=True)
    temperature = db.Column(db.Numeric(4, 1), nullable=True)
    weight_kg = db.Column(db.Numeric(6, 2), nullable=True)
    height_cm = db.Column(db.Numeric(6, 2), nullable=True)
    oxygen_sat = db.Column(db.Integer, nullable=True)
    bmi = db.Column(db.Numeric(6, 2), nullable=True)
    respiratory_rate = db.Column(db.Integer, nullable=True)
    blood_glucose = db.Column(db.Numeric(7, 2), nullable=True)
    head_circumference_cm = db.Column(db.Numeric(6, 2), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicVisitTemplate(db.Model):
    __tablename__ = "clinic_visit_template"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "specialty_id", "version", name="uq_clinic_visit_template_version"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    specialty_id = db.Column(db.Integer, db.ForeignKey("clinic_specialty.id"), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicVisitTemplateSection(db.Model):
    __tablename__ = "clinic_visit_template_section"
    __table_args__ = (
        db.Index("ix_clinic_template_section_order", "tenant_id", "template_id", "sort_order"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    template_id = db.Column(db.Integer, db.ForeignKey("clinic_visit_template.id"), nullable=False, index=True)
    title_ar = db.Column(db.String(200), nullable=False)
    title_en = db.Column(db.String(200), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_collapsible = db.Column(db.Boolean, nullable=False, default=True)
    default_open = db.Column(db.Boolean, nullable=False, default=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class ClinicVisitTemplateField(db.Model):
    __tablename__ = "clinic_visit_template_field"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "template_id", "key", name="uq_clinic_template_field_key"),
        db.Index("ix_clinic_template_field_order", "tenant_id", "section_id", "sort_order"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    template_id = db.Column(db.Integer, db.ForeignKey("clinic_visit_template.id"), nullable=False, index=True)
    section_id = db.Column(db.Integer, db.ForeignKey("clinic_visit_template_section.id"), nullable=False, index=True)
    key = db.Column(db.String(100), nullable=False)
    label_ar = db.Column(db.String(200), nullable=False)
    label_en = db.Column(db.String(200), nullable=True)
    field_type = db.Column(db.String(30), nullable=False, default="text")
    required = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    unit = db.Column(db.String(40), nullable=True)
    placeholder = db.Column(db.String(255), nullable=True)
    options_json = db.Column(db.Text, nullable=True)
    validation_json = db.Column(db.Text, nullable=True)
    visibility_rules_json = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class ClinicVisitFieldValue(db.Model):
    __tablename__ = "clinic_visit_field_value"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "visit_id", "field_id", name="uq_clinic_visit_field_value"),
        db.Index("ix_clinic_visit_field_values", "tenant_id", "visit_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=False, index=True)
    field_id = db.Column(db.Integer, db.ForeignKey("clinic_visit_template_field.id"), nullable=False, index=True)
    value_text = db.Column(db.Text, nullable=True)
    value_number = db.Column(db.Numeric(18, 4), nullable=True)
    value_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicDiagnosis(db.Model):
    __tablename__ = "clinic_diagnosis"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    code = db.Column(db.String(40), nullable=True)
    title = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="active")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicPrescription(db.Model):
    __tablename__ = "clinic_prescription"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicPrescriptionItem(db.Model):
    __tablename__ = "clinic_prescription_item"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    prescription_id = db.Column(
        db.Integer, db.ForeignKey("clinic_prescription.id"), nullable=False, index=True
    )
    medicine_name = db.Column(db.String(200), nullable=False)
    dosage = db.Column(db.String(120), nullable=True)
    frequency = db.Column(db.String(120), nullable=True)
    duration = db.Column(db.String(120), nullable=True)
    instructions = db.Column(db.String(255), nullable=True)


class ClinicPrescriptionTemplate(db.Model):
    __tablename__ = "clinic_prescription_template"
    __table_args__ = (db.Index("ix_clinic_rx_template_scope", "tenant_id", "scope_type", "specialty_id", "doctor_id", "active"),)

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    scope_type = db.Column(db.String(20), nullable=False, default="clinic")
    specialty_id = db.Column(db.Integer, db.ForeignKey("clinic_specialty.id"), nullable=True, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True, index=True)
    notes = db.Column(db.Text, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClinicPrescriptionTemplateItem(db.Model):
    __tablename__ = "clinic_prescription_template_item"
    __table_args__ = (db.Index("ix_clinic_rx_template_item_order", "tenant_id", "template_id", "sort_order"),)

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    template_id = db.Column(db.Integer, db.ForeignKey("clinic_prescription_template.id"), nullable=False, index=True)
    medicine_name = db.Column(db.String(200), nullable=False)
    dosage = db.Column(db.String(120), nullable=True)
    frequency = db.Column(db.String(120), nullable=True)
    duration = db.Column(db.String(120), nullable=True)
    instructions = db.Column(db.String(255), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)


class ClinicInvoice(db.Model):
    __tablename__ = "clinic_invoice"
    __table_args__ = (
        db.Index("ix_clinic_invoice_patient", "tenant_id", "patient_id"),
        db.UniqueConstraint("tenant_id", "visit_id", name="uq_clinic_invoice_visit"),
        db.UniqueConstraint("tenant_id", "invoice_number", name="uq_clinic_invoice_number"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=True, index=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("clinic_appointment.id"), nullable=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True)
    invoice_number = db.Column(db.String(40), nullable=False)
    invoice_date = db.Column(db.Date, nullable=False, default=date.today)
    subtotal = db.Column(db.Integer, nullable=False, default=0)
    discount = db.Column(db.Integer, nullable=False, default=0)
    total = db.Column(db.Integer, nullable=False, default=0)
    paid = db.Column(db.Integer, nullable=False, default=0)
    balance = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="open", index=True)
    notes = db.Column(db.Text, nullable=True)
    treatment_plan_id = db.Column(
        db.Integer, db.ForeignKey("clinic_dental_treatment_plan.id"), nullable=True, index=True
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicInvoiceItem(db.Model):
    __tablename__ = "clinic_invoice_item"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("clinic_invoice.id"), nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("clinic_service.id"), nullable=True)
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Integer, nullable=False, default=0)
    line_total = db.Column(db.Integer, nullable=False, default=0)
    treatment_plan_item_id = db.Column(
        db.Integer, db.ForeignKey("clinic_dental_treatment_plan_item.id"), nullable=True, index=True
    )
    dental_session_id = db.Column(
        db.Integer, db.ForeignKey("clinic_dental_session.id"), nullable=True, index=True
    )


class ClinicPayment(db.Model):
    __tablename__ = "clinic_payment"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("clinic_invoice.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False, default=0)
    method = db.Column(db.String(40), nullable=False, default="cash")
    paid_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    notes = db.Column(db.String(255), nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ClinicAuditLog(db.Model):
    __tablename__ = "clinic_audit_log"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True)
    entity_type = db.Column(db.String(60), nullable=False)
    entity_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.String(60), nullable=False)
    summary = db.Column(db.String(255), nullable=False)
    meta_json = db.Column(db.Text, nullable=True)
    actor_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ClinicDoctorTimeOff(db.Model):
    __tablename__ = "clinic_doctor_time_off"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=False, index=True)
    from_date = db.Column(db.Date, nullable=False)
    to_date = db.Column(db.Date, nullable=False)
    from_time = db.Column(db.Time, nullable=True)
    to_time = db.Column(db.Time, nullable=True)
    reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicInventoryItem(db.Model):
    __tablename__ = "clinic_inventory_item"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "sku", name="uq_clinic_inv_sku"),
        db.Index("ix_clinic_inv_name", "tenant_id", "name"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    sku = db.Column(db.String(80), nullable=True)
    barcode = db.Column(db.String(80), nullable=True)
    name = db.Column(db.String(200), nullable=False)
    scientific_name = db.Column(db.String(200), nullable=True)
    category = db.Column(db.String(100), nullable=True)
    description = db.Column(db.Text, nullable=True)
    unit = db.Column(db.String(40), nullable=False, default="piece")
    purchase_price = db.Column(db.Integer, nullable=False, default=0)
    average_cost = db.Column(db.Integer, nullable=False, default=0)
    last_purchase_cost = db.Column(db.Integer, nullable=False, default=0)
    selling_price = db.Column(db.Integer, nullable=False, default=0)
    current_stock = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    minimum_stock = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    maximum_stock = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    reorder_point = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    suggested_reorder_qty = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    expiry_tracking = db.Column(db.Boolean, nullable=False, default=False)
    batch_tracking = db.Column(db.Boolean, nullable=False, default=False)
    serial_tracking = db.Column(db.Boolean, nullable=False, default=False)
    requires_cooling = db.Column(db.Boolean, nullable=False, default=False)
    sensitive_item = db.Column(db.Boolean, nullable=False, default=False)
    prevent_expired_usage = db.Column(db.Boolean, nullable=False, default=True)
    default_supplier_id = db.Column(db.Integer, db.ForeignKey("clinic_supplier.id"), nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicInventoryBatch(db.Model):
    __tablename__ = "clinic_inventory_batch"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("clinic_inventory_item.id"), nullable=False, index=True)
    batch_number = db.Column(db.String(80), nullable=False)
    manufacturing_date = db.Column(db.Date, nullable=True)
    expiry_date = db.Column(db.Date, nullable=True, index=True)
    quantity_received = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    quantity_available = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    purchase_price = db.Column(db.Integer, nullable=False, default=0)
    supplier_id = db.Column(db.Integer, db.ForeignKey("clinic_supplier.id"), nullable=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("clinic_purchase.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ClinicInventoryMovement(db.Model):
    __tablename__ = "clinic_inventory_movement"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("clinic_inventory_item.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("clinic_inventory_batch.id"), nullable=True)
    movement_type = db.Column(db.String(40), nullable=False)  # in / out / adjust / procedure
    quantity = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    stock_before = db.Column(db.Numeric(14, 3), nullable=True)
    stock_after = db.Column(db.Numeric(14, 3), nullable=True)
    unit_cost = db.Column(db.Integer, nullable=False, default=0)
    reason = db.Column(db.String(80), nullable=True)
    branch_id = db.Column(db.Integer, nullable=True)
    reference_type = db.Column(db.String(40), nullable=True)
    reference_id = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicProcedure(db.Model):
    __tablename__ = "clinic_procedure"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    price = db.Column(db.Integer, nullable=False, default=0)
    duration_minutes = db.Column(db.Integer, nullable=False, default=15)
    description = db.Column(db.Text, nullable=True)
    available_for_booking = db.Column(db.Boolean, nullable=False, default=False)
    creates_charge = db.Column(db.Boolean, nullable=False, default=True)
    requires_room = db.Column(db.Boolean, nullable=False, default=False)
    consumes_inventory = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicProcedureSpecialty(db.Model):
    __tablename__ = "clinic_procedure_specialty"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "procedure_id", "specialty_id", name="uq_clinic_procedure_specialty"),
        db.Index("ix_clinic_procedure_specialty_lookup", "tenant_id", "specialty_id", "procedure_id"),
    )
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    procedure_id = db.Column(db.Integer, db.ForeignKey("clinic_procedure.id"), nullable=False, index=True)
    specialty_id = db.Column(db.Integer, db.ForeignKey("clinic_specialty.id"), nullable=False, index=True)


class ClinicProcedureRecipeItem(db.Model):
    __tablename__ = "clinic_procedure_recipe_item"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    procedure_id = db.Column(db.Integer, db.ForeignKey("clinic_procedure.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("clinic_inventory_item.id"), nullable=False, index=True)
    quantity = db.Column(db.Numeric(14, 3), nullable=False, default=1)


class ClinicVisitProcedure(db.Model):
    __tablename__ = "clinic_visit_procedure"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True)
    procedure_id = db.Column(db.Integer, db.ForeignKey("clinic_procedure.id"), nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False, default="requested", index=True)
    quantity = db.Column(db.Numeric(10, 2), nullable=False, default=1)
    performed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    inventory_consumed_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    result = db.Column(db.Text, nullable=True)
    price = db.Column(db.Integer, nullable=False, default=0)
    inventory_deducted = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicLabTest(db.Model):
    __tablename__ = "clinic_lab_test"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    code = db.Column(db.String(40), nullable=True)
    category = db.Column(db.String(100), nullable=True)
    price = db.Column(db.Integer, nullable=False, default=0)
    reference_notes = db.Column(db.Text, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicLabOrder(db.Model):
    __tablename__ = "clinic_lab_order"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=True, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True)
    ordered_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    priority = db.Column(db.String(20), nullable=False, default="normal")
    status = db.Column(db.String(30), nullable=False, default="ordered", index=True)
    notes = db.Column(db.Text, nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicLabOrderItem(db.Model):
    __tablename__ = "clinic_lab_order_item"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("clinic_lab_order.id"), nullable=False, index=True)
    test_id = db.Column(db.Integer, db.ForeignKey("clinic_lab_test.id"), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="ordered")
    value = db.Column(db.String(120), nullable=True)
    unit = db.Column(db.String(40), nullable=True)
    reference_range = db.Column(db.String(120), nullable=True)
    abnormal_flag = db.Column(db.String(20), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    result_at = db.Column(db.DateTime, nullable=True)


class ClinicRadiologyOrder(db.Model):
    __tablename__ = "clinic_radiology_order"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=True, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True)
    modality = db.Column(db.String(40), nullable=False, default="xray")
    body_part = db.Column(db.String(120), nullable=True)
    priority = db.Column(db.String(20), nullable=False, default="normal")
    status = db.Column(db.String(30), nullable=False, default="ordered", index=True)
    price = db.Column(db.Integer, nullable=False, default=0)
    report = db.Column(db.Text, nullable=True)
    impression = db.Column(db.Text, nullable=True)
    recommendations = db.Column(db.Text, nullable=True)
    ordered_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    performed_at = db.Column(db.DateTime, nullable=True)
    reported_at = db.Column(db.DateTime, nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicDoctorSettlement(db.Model):
    __tablename__ = "clinic_doctor_settlement"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=False, index=True)
    period_from = db.Column(db.Date, nullable=False)
    period_to = db.Column(db.Date, nullable=False)
    visits_count = db.Column(db.Integer, nullable=False, default=0)
    gross_revenue = db.Column(db.Integer, nullable=False, default=0)
    doctor_share = db.Column(db.Integer, nullable=False, default=0)
    clinic_share = db.Column(db.Integer, nullable=False, default=0)
    adjustments = db.Column(db.Integer, nullable=False, default=0)
    paid_amount = db.Column(db.Integer, nullable=False, default=0)
    payment_method = db.Column(db.String(40), nullable=False, default="cash")
    balance = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="draft")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClinicSupplier(db.Model):
    __tablename__ = "clinic_supplier"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(40), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    address = db.Column(db.String(300), nullable=True)
    contact_person = db.Column(db.String(120), nullable=True)
    tax_number = db.Column(db.String(60), nullable=True)
    opening_balance = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicPurchase(db.Model):
    __tablename__ = "clinic_purchase"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("clinic_supplier.id"), nullable=False, index=True)
    purchase_number = db.Column(db.String(40), nullable=False)
    supplier_invoice_no = db.Column(db.String(120), nullable=True)
    purchase_date = db.Column(db.Date, nullable=False, default=date.today)
    due_date = db.Column(db.Date, nullable=True)
    subtotal = db.Column(db.Integer, nullable=False, default=0)
    discount = db.Column(db.Integer, nullable=False, default=0)
    discount_percent = db.Column(db.Numeric(5, 2), nullable=True)
    shipping_extra = db.Column(db.Integer, nullable=False, default=0)
    tax_amount = db.Column(db.Integer, nullable=False, default=0)
    other_charges = db.Column(db.Integer, nullable=False, default=0)
    total = db.Column(db.Integer, nullable=False, default=0)
    paid = db.Column(db.Integer, nullable=False, default=0)
    balance = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="open", index=True)
    invoice_status = db.Column(db.String(30), nullable=False, default="approved", index=True)
    payment_status = db.Column(db.String(30), nullable=False, default="unpaid", index=True)
    receipt_status = db.Column(db.String(30), nullable=False, default="pending", index=True)
    purchase_type = db.Column(db.String(30), nullable=False, default="credit")
    warehouse_name = db.Column(db.String(120), nullable=True)
    return_total = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicPurchaseItem(db.Model):
    __tablename__ = "clinic_purchase_item"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("clinic_purchase.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("clinic_inventory_item.id"), nullable=False, index=True)
    batch_number = db.Column(db.String(80), nullable=True)
    expiry_date = db.Column(db.Date, nullable=True)
    quantity = db.Column(db.Numeric(14, 3), nullable=False, default=1)
    free_quantity = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    received_quantity = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    unit_cost = db.Column(db.Integer, nullable=False, default=0)
    line_discount = db.Column(db.Integer, nullable=False, default=0)
    line_discount_percent = db.Column(db.Numeric(5, 2), nullable=True)
    line_total = db.Column(db.Integer, nullable=False, default=0)
    returned_quantity = db.Column(db.Numeric(14, 3), nullable=False, default=0)


class ClinicPurchasePayment(db.Model):
    __tablename__ = "clinic_purchase_payment"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("clinic_purchase.id"), nullable=False, index=True)
    payment_number = db.Column(db.String(40), nullable=False)
    payment_date = db.Column(db.Date, nullable=False, default=date.today)
    amount = db.Column(db.Integer, nullable=False, default=0)
    payment_method = db.Column(db.String(40), nullable=False, default="cash")
    account_name = db.Column(db.String(120), nullable=True)
    reference_no = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ClinicPurchaseReceipt(db.Model):
    __tablename__ = "clinic_purchase_receipt"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("clinic_purchase.id"), nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True)
    receipt_number = db.Column(db.String(40), nullable=False)
    received_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    notes = db.Column(db.Text, nullable=True)
    received_by = db.Column(db.Integer, nullable=True)


class ClinicPurchaseReceiptItem(db.Model):
    __tablename__ = "clinic_purchase_receipt_item"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    receipt_id = db.Column(db.Integer, db.ForeignKey("clinic_purchase_receipt.id"), nullable=False, index=True)
    purchase_item_id = db.Column(db.Integer, db.ForeignKey("clinic_purchase_item.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("clinic_inventory_batch.id"), nullable=True)
    quantity = db.Column(db.Numeric(14, 3), nullable=False)
    unit_cost = db.Column(db.Integer, nullable=False, default=0)
    batch_number = db.Column(db.String(80), nullable=True)
    manufacturing_date = db.Column(db.Date, nullable=True)
    expiry_date = db.Column(db.Date, nullable=True)


class ClinicPurchaseRequest(db.Model):
    __tablename__ = "clinic_purchase_request"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    request_number = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="draft", index=True)
    priority = db.Column(db.String(20), nullable=False, default="normal")
    notes = db.Column(db.Text, nullable=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("clinic_purchase.id"), nullable=True, index=True)
    created_by = db.Column(db.Integer, nullable=True)
    approved_by = db.Column(db.Integer, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClinicPurchaseRequestItem(db.Model):
    __tablename__ = "clinic_purchase_request_item"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    request_id = db.Column(db.Integer, db.ForeignKey("clinic_purchase_request.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("clinic_inventory_item.id"), nullable=False, index=True)
    quantity = db.Column(db.Numeric(14, 3), nullable=False, default=1)
    reason = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.String(255), nullable=True)


class ClinicPurchaseReturn(db.Model):
    __tablename__ = "clinic_purchase_return"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("clinic_purchase.id"), nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("clinic_supplier.id"), nullable=False, index=True)
    return_number = db.Column(db.String(40), nullable=False)
    return_date = db.Column(db.Date, nullable=False, default=date.today)
    status = db.Column(db.String(30), nullable=False, default="approved", index=True)
    notes = db.Column(db.Text, nullable=True)
    total_value = db.Column(db.Integer, nullable=False, default=0)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ClinicPurchaseReturnItem(db.Model):
    __tablename__ = "clinic_purchase_return_item"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    return_id = db.Column(db.Integer, db.ForeignKey("clinic_purchase_return.id"), nullable=False, index=True)
    purchase_item_id = db.Column(db.Integer, db.ForeignKey("clinic_purchase_item.id"), nullable=True, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("clinic_inventory_item.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("clinic_inventory_batch.id"), nullable=True)
    batch_number = db.Column(db.String(80), nullable=True)
    quantity = db.Column(db.Numeric(14, 3), nullable=False)
    unit_cost = db.Column(db.Integer, nullable=False, default=0)
    line_total = db.Column(db.Integer, nullable=False, default=0)
    reason = db.Column(db.String(80), nullable=True)


class ClinicPurchaseAttachment(db.Model):
    __tablename__ = "clinic_purchase_attachment"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("clinic_purchase.id"), nullable=False, index=True)
    category = db.Column(db.String(40), nullable=False, default="invoice")
    file_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(120), nullable=True)
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    uploaded_by = db.Column(db.Integer, nullable=True)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ClinicFollowUp(db.Model):
    __tablename__ = "clinic_follow_up"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=True, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True)
    followup_type = db.Column(db.String(40), nullable=False, default="treatment_review")
    due_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False, default="due", index=True)
    notes = db.Column(db.Text, nullable=True)
    contacted_at = db.Column(db.DateTime, nullable=True)
    last_attempt_at = db.Column(db.DateTime, nullable=True)
    outcome = db.Column(db.String(60), nullable=True)
    scheduled_appointment_id = db.Column(db.Integer, db.ForeignKey("clinic_appointment.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicFollowUpAttempt(db.Model):
    __tablename__ = "clinic_follow_up_attempt"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    followup_id = db.Column(db.Integer, db.ForeignKey("clinic_follow_up.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    contact_result = db.Column(db.String(40), nullable=False)
    outcome = db.Column(db.String(60), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    next_due_date = db.Column(db.Date, nullable=True)
    attempted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicReminder(db.Model):
    __tablename__ = "clinic_reminder"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "idempotency_key", name="uq_clinic_reminder_once"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    reminder_type = db.Column(db.String(40), nullable=False)
    reference_type = db.Column(db.String(40), nullable=False)
    reference_id = db.Column(db.Integer, nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=True)
    channel = db.Column(db.String(20), nullable=False, default="whatsapp")
    scheduled_for = db.Column(db.DateTime, nullable=False, index=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    idempotency_key = db.Column(db.String(120), nullable=False)
    message_body = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ClinicReminderRule(db.Model):
    __tablename__ = "clinic_reminder_rule"
    __table_args__ = (db.UniqueConstraint("tenant_id", "hours_before", "channel", name="uq_clinic_reminder_rule"),)

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    hours_before = db.Column(db.Integer, nullable=False)
    channel = db.Column(db.String(20), nullable=False, default="whatsapp")
    template_body = db.Column(db.Text, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClinicMessageLog(db.Model):
    __tablename__ = "clinic_message_log"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=True)
    recipient = db.Column(db.String(40), nullable=False)
    template_key = db.Column(db.String(60), nullable=False)
    channel = db.Column(db.String(20), nullable=False, default="whatsapp")
    status = db.Column(db.String(30), nullable=False, default="queued")
    message_body = db.Column(db.Text, nullable=True)
    failed_reason = db.Column(db.String(255), nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    reference_type = db.Column(db.String(40), nullable=True)
    reference_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ClinicConversation(db.Model):
    __tablename__ = "clinic_conversation"
    __table_args__ = (
        db.Index("ix_clinic_conversation_inbox", "tenant_id", "status", "last_message_at"),
        db.Index("ix_clinic_conversation_phone", "tenant_id", "contact_phone"),
        db.UniqueConstraint("tenant_id", "channel", "external_thread_id", name="uq_clinic_conversation_external"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=True, index=True)
    channel = db.Column(db.String(20), nullable=False, default="whatsapp")
    external_thread_id = db.Column(db.String(160), nullable=True)
    contact_name = db.Column(db.String(200), nullable=True)
    contact_phone = db.Column(db.String(40), nullable=True)
    assigned_user_id = db.Column(db.Integer, nullable=True, index=True)
    status = db.Column(db.String(30), nullable=False, default="new", index=True)
    unread_count = db.Column(db.Integer, nullable=False, default=0)
    last_message_preview = db.Column(db.String(300), nullable=True)
    last_message_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    opened_by = db.Column(db.Integer, nullable=True)
    opened_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient = db.relationship("ClinicPatient", lazy=True)


class ClinicConversationMessage(db.Model):
    __tablename__ = "clinic_conversation_message"
    __table_args__ = (
        db.Index("ix_clinic_message_timeline", "tenant_id", "conversation_id", "created_at"),
        db.UniqueConstraint("tenant_id", "external_message_id", name="uq_clinic_message_external"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("clinic_conversation.id"), nullable=False, index=True)
    direction = db.Column(db.String(20), nullable=False, default="outgoing")
    message_type = db.Column(db.String(30), nullable=False, default="text")
    channel = db.Column(db.String(20), nullable=False, default="whatsapp")
    content = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="queued")
    sender_user_id = db.Column(db.Integer, nullable=True)
    external_message_id = db.Column(db.String(160), nullable=True)
    attachment_url = db.Column(db.String(500), nullable=True)
    reference_type = db.Column(db.String(40), nullable=True)
    reference_id = db.Column(db.Integer, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    failed_at = db.Column(db.DateTime, nullable=True)
    failed_reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ClinicPublicChatToken(db.Model):
    __tablename__ = "clinic_public_chat_token"
    __table_args__ = (db.Index("ix_clinic_public_chat_token_lookup", "tenant_id", "token_hash"),)

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("clinic_conversation.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ClinicMessageTemplate(db.Model):
    __tablename__ = "clinic_message_template"
    __table_args__ = (db.UniqueConstraint("tenant_id", "shortcut", name="uq_clinic_template_shortcut"),)

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    shortcut = db.Column(db.String(60), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.Text, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClinicBookingRequest(db.Model):
    __tablename__ = "clinic_booking_request"
    __table_args__ = (db.Index("ix_clinic_booking_request_queue", "tenant_id", "status", "created_at"),)

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("clinic_service.id"), nullable=True, index=True)
    specialty_id = db.Column(db.Integer, db.ForeignKey("clinic_specialty.id"), nullable=True, index=True)
    requested_start = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="pending_approval", index=True)
    source = db.Column(db.String(40), nullable=False, default="public_booking")
    notes = db.Column(db.Text, nullable=True)
    approved_by = db.Column(db.Integer, nullable=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("clinic_appointment.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClinicPublicBookingToken(db.Model):
    __tablename__ = "clinic_public_booking_token"
    __table_args__ = (db.UniqueConstraint("tenant_id", "token_hash", name="uq_clinic_booking_token"),)

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("clinic_appointment.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ClinicCommunicationTask(db.Model):
    __tablename__ = "clinic_communication_task"
    __table_args__ = (db.Index("ix_clinic_comms_task_due", "tenant_id", "status", "due_at"),)

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("clinic_conversation.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=True, index=True)
    title = db.Column(db.String(220), nullable=False)
    due_at = db.Column(db.DateTime, nullable=True)
    assigned_user_id = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="open")
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClinicVisitBillLine(db.Model):
    __tablename__ = "clinic_visit_bill_line"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=False, index=True)
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Integer, nullable=False, default=0)
    line_total = db.Column(db.Integer, nullable=False, default=0)
    line_type = db.Column(db.String(40), nullable=False, default="other")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicBookingAttempt(db.Model):
    __tablename__ = "clinic_booking_attempt"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    ip_address = db.Column(db.String(64), nullable=True)
    phone = db.Column(db.String(40), nullable=True)
    success = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ClinicBookingOtp(db.Model):
    __tablename__ = "clinic_booking_otp"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    phone = db.Column(db.String(40), nullable=False, index=True)
    code_hash = db.Column(db.String(128), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    verified_at = db.Column(db.DateTime, nullable=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ClinicExpense(db.Model):
    __tablename__ = "clinic_expense"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(80), nullable=False, default="تشغيل")
    amount = db.Column(db.Integer, nullable=False, default=0)
    expense_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    payment_method = db.Column(db.String(40), nullable=False, default="cash")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicRefund(db.Model):
    __tablename__ = "clinic_refund"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("clinic_invoice.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("clinic_payment.id"), nullable=True)
    amount = db.Column(db.Integer, nullable=False, default=0)
    reason = db.Column(db.String(255), nullable=True)
    method = db.Column(db.String(40), nullable=False, default="cash")
    refunded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ClinicAttachment(db.Model):
    __tablename__ = "clinic_attachment"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=True, index=True)
    category = db.Column(db.String(40), nullable=False, default="other")
    file_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(120), nullable=True)
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    document_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    uploaded_by = db.Column(db.Integer, nullable=True)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ClinicConsent(db.Model):
    __tablename__ = "clinic_consent"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=True)
    consent_type = db.Column(db.String(80), nullable=False, default="treatment")
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=True)
    signed_name = db.Column(db.String(200), nullable=True)
    signed_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="pending", index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicCashSession(db.Model):
    __tablename__ = "clinic_cash_session"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    business_date = db.Column(db.Date, nullable=False, index=True)
    opening_cash = db.Column(db.Integer, nullable=False, default=0)
    closing_cash = db.Column(db.Integer, nullable=True)
    expected_cash = db.Column(db.Integer, nullable=True)
    cash_collections = db.Column(db.Integer, nullable=False, default=0)
    cash_refunds = db.Column(db.Integer, nullable=False, default=0)
    cash_expenses = db.Column(db.Integer, nullable=False, default=0)
    supplier_payments = db.Column(db.Integer, nullable=False, default=0)
    doctor_payments = db.Column(db.Integer, nullable=False, default=0)
    other_cash_in = db.Column(db.Integer, nullable=False, default=0)
    other_cash_out = db.Column(db.Integer, nullable=False, default=0)
    difference = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    notes = db.Column(db.Text, nullable=True)
    opened_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    closed_at = db.Column(db.DateTime, nullable=True)
    opened_by = db.Column(db.Integer, nullable=True)
    closed_by = db.Column(db.Integer, nullable=True)


class AccountingPosting(db.Model):
    """Idempotent bridge between the clinic subledger and the general ledger."""

    __tablename__ = "accounting_posting"
    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id", "source_module", "source_type", "source_id", "source_event",
            name="uq_accounting_posting_source_event",
        ),
        db.Index(
            "ix_accounting_posting_source",
            "tenant_id", "source_module", "source_type", "source_id",
        ),
        db.CheckConstraint(
            "status IN ('unposted', 'posted', 'reversed', 'error')",
            name="ck_accounting_posting_status",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    source_module = db.Column(db.String(40), nullable=False, default="clinics")
    source_type = db.Column(db.String(80), nullable=False)
    source_id = db.Column(db.Integer, nullable=False)
    source_event = db.Column(db.String(80), nullable=False)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="unposted", index=True)
    posted_at = db.Column(db.DateTime, nullable=True)
    posted_by = db.Column(db.Integer, nullable=True)
    reversed_at = db.Column(db.DateTime, nullable=True)
    reversal_journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    journal_entry = db.relationship("JournalEntry", foreign_keys=[journal_entry_id])
    reversal_journal_entry = db.relationship("JournalEntry", foreign_keys=[reversal_journal_entry_id])


class ClinicDentalRecord(db.Model):
    """Per-visit dental chart header (one odontogram context per visit)."""
    __tablename__ = "clinic_dental_record"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "visit_id", name="uq_clinic_dental_record_visit"),
        db.Index("ix_clinic_dental_record_patient", "tenant_id", "patient_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True)
    specialty_id = db.Column(db.Integer, db.ForeignKey("clinic_specialty.id"), nullable=True)
    dentition_mode = db.Column(db.String(20), nullable=False, default="permanent")  # permanent|primary|mixed
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicDentalToothFinding(db.Model):
    """Tooth finding belonging to a specific visit dental record."""
    __tablename__ = "clinic_dental_tooth_finding"
    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id", "dental_record_id", "tooth_number",
            name="uq_clinic_dental_tooth_finding",
        ),
        db.Index("ix_clinic_dental_tooth_patient", "tenant_id", "patient_id", "tooth_number"),
        db.Index("ix_clinic_dental_tooth_visit", "tenant_id", "visit_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=False, index=True)
    dental_record_id = db.Column(db.Integer, db.ForeignKey("clinic_dental_record.id"), nullable=False, index=True)
    tooth_number = db.Column(db.String(4), nullable=False)
    dentition = db.Column(db.String(20), nullable=False, default="permanent")  # permanent|primary
    status = db.Column(db.String(40), nullable=False, default="healthy")
    surfaces_json = db.Column(db.Text, nullable=True)  # JSON list of surface codes
    notes = db.Column(db.Text, nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicDentalToothEvent(db.Model):
    """Append-only tooth history. Current chart state stays on findings."""
    __tablename__ = "clinic_dental_tooth_event"
    __table_args__ = (
        db.Index("ix_clinic_dental_tooth_event_patient", "tenant_id", "patient_id", "tooth_number"),
        db.Index("ix_clinic_dental_tooth_event_visit", "tenant_id", "visit_id"),
        db.Index("ix_clinic_dental_tooth_event_date", "tenant_id", "event_date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=True, index=True)
    tooth_number = db.Column(db.String(4), nullable=False, index=True)
    condition_code = db.Column(db.String(40), nullable=False, default="other")
    surfaces_json = db.Column(db.Text, nullable=True)
    procedure_code = db.Column(db.String(80), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    event_type = db.Column(db.String(40), nullable=False, default="condition_change", index=True)
    # v29 events can represent concurrent active findings. Historical v28
    # events remain immutable and are not treated as active projections.
    is_active = db.Column(db.Boolean, nullable=False, default=False, index=True)
    finding_key = db.Column(db.String(80), nullable=True, index=True)
    supersedes_event_id = db.Column(
        db.Integer, db.ForeignKey("clinic_dental_tooth_event.id"), nullable=True, index=True
    )
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by = db.Column(db.Integer, nullable=True)
    event_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClinicDentalToothProcedure(db.Model):
    """Links an existing visit procedure execution to a tooth context."""
    __tablename__ = "clinic_dental_tooth_procedure"
    __table_args__ = (
        db.Index("ix_clinic_dental_tooth_proc_visit", "tenant_id", "visit_id"),
        db.Index("ix_clinic_dental_tooth_proc_finding", "tenant_id", "tooth_finding_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=False, index=True)
    tooth_finding_id = db.Column(db.Integer, db.ForeignKey("clinic_dental_tooth_finding.id"), nullable=True, index=True)
    tooth_number = db.Column(db.String(4), nullable=False)
    visit_procedure_id = db.Column(db.Integer, db.ForeignKey("clinic_visit_procedure.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)


class ClinicDentalTreatmentPlan(db.Model):
    """Patient-level dental treatment plan (clinical intent, not billing)."""
    __tablename__ = "clinic_dental_treatment_plan"
    __table_args__ = (
        db.Index("ix_clinic_dental_tp_patient", "tenant_id", "patient_id", "status"),
        db.Index("ix_clinic_dental_tp_doctor", "tenant_id", "created_by_doctor_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    created_by_doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True, index=True)
    specialty_id = db.Column(db.Integer, db.ForeignKey("clinic_specialty.id"), nullable=True)
    source_visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=True)
    name = db.Column(db.String(200), nullable=False, default="خطة علاج الأسنان")
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="draft", index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    accepted_by = db.Column(db.Integer, nullable=True)
    selected_option_id = db.Column(db.Integer, nullable=True, index=True)
    acceptance_method = db.Column(db.String(40), nullable=True)
    signature_attachment_id = db.Column(
        db.Integer, db.ForeignKey("clinic_attachment.id"), nullable=True, index=True
    )
    estimated_discount = db.Column(db.Integer, nullable=False, default=0)
    cancellation_reason = db.Column(db.Text, nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicDentalTreatmentOption(db.Model):
    """Alternative grouping inside one patient-level treatment plan."""
    __tablename__ = "clinic_dental_treatment_option"
    __table_args__ = (
        db.Index("ix_clinic_dental_option_plan", "tenant_id", "treatment_plan_id", "status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    treatment_plan_id = db.Column(
        db.Integer, db.ForeignKey("clinic_dental_treatment_plan.id"), nullable=False, index=True
    )
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    option_type = db.Column(db.String(30), nullable=False, default="alternative")
    is_recommended = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(30), nullable=False, default="proposed", index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicDentalTreatmentPlanItem(db.Model):
    __tablename__ = "clinic_dental_treatment_plan_item"
    __table_args__ = (
        db.Index("ix_clinic_dental_tpi_plan", "tenant_id", "plan_id", "status"),
        db.Index("ix_clinic_dental_tpi_tooth", "tenant_id", "plan_id", "tooth_number"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("clinic_dental_treatment_plan.id"), nullable=False, index=True)
    treatment_option_id = db.Column(
        db.Integer, db.ForeignKey("clinic_dental_treatment_option.id"), nullable=True, index=True
    )
    tooth_number = db.Column(db.String(4), nullable=True)
    tooth_numbers_json = db.Column(db.Text, nullable=True)
    whole_mouth = db.Column(db.Boolean, nullable=False, default=False)
    procedure_id = db.Column(db.Integer, db.ForeignKey("clinic_procedure.id"), nullable=True, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("clinic_service.id"), nullable=True, index=True)
    title = db.Column(db.String(200), nullable=False, default="")
    description = db.Column(db.Text, nullable=True)
    priority = db.Column(db.String(20), nullable=False, default="normal")
    status = db.Column(db.String(30), nullable=False, default="planned", index=True)
    estimated_sessions = db.Column(db.Integer, nullable=False, default=1)
    estimated_price = db.Column(db.Integer, nullable=False, default=0)
    quantity = db.Column(db.Numeric(10, 2), nullable=False, default=1)
    discount = db.Column(db.Integer, nullable=False, default=0)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    completed_by = db.Column(db.Integer, nullable=True)
    cancelled_by = db.Column(db.Integer, nullable=True)
    cancellation_reason = db.Column(db.Text, nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicDentalTreatmentPlanItemLink(db.Model):
    """Links a planned item to an actual ClinicVisitProcedure execution."""
    __tablename__ = "clinic_dental_treatment_plan_item_link"
    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id", "treatment_plan_item_id", "visit_procedure_id",
            name="uq_clinic_dental_tpi_vp",
        ),
        db.Index("ix_clinic_dental_tpi_link_item", "tenant_id", "treatment_plan_item_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    treatment_plan_item_id = db.Column(
        db.Integer, db.ForeignKey("clinic_dental_treatment_plan_item.id"), nullable=False, index=True
    )
    visit_procedure_id = db.Column(
        db.Integer, db.ForeignKey("clinic_visit_procedure.id"), nullable=False, index=True
    )
    linked_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    linked_by = db.Column(db.Integer, nullable=True)


class ClinicDentalSession(db.Model):
    """A scheduled/performed session; execution remains ClinicVisitProcedure."""
    __tablename__ = "clinic_dental_session"
    __table_args__ = (
        db.Index("ix_clinic_dental_session_plan", "tenant_id", "plan_id", "status"),
        db.Index("ix_clinic_dental_session_item", "tenant_id", "treatment_plan_item_id", "session_number"),
        db.UniqueConstraint(
            "tenant_id", "treatment_plan_item_id", "session_number",
            name="uq_clinic_dental_session_number",
        ),
        db.UniqueConstraint("tenant_id", "visit_procedure_id", name="uq_clinic_dental_session_vp"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("clinic_dental_treatment_plan.id"), nullable=False, index=True)
    treatment_plan_item_id = db.Column(
        db.Integer, db.ForeignKey("clinic_dental_treatment_plan_item.id"), nullable=False, index=True
    )
    appointment_id = db.Column(db.Integer, db.ForeignKey("clinic_appointment.id"), nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=True, index=True)
    visit_procedure_id = db.Column(
        db.Integer, db.ForeignKey("clinic_visit_procedure.id"), nullable=True, index=True
    )
    session_number = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(30), nullable=False, default="planned", index=True)
    scheduled_for = db.Column(db.DateTime, nullable=True, index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    next_recommendation = db.Column(db.Text, nullable=True)
    cancellation_reason = db.Column(db.Text, nullable=True)
    completed_by = db.Column(db.Integer, nullable=True)
    cancelled_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicDentalImage(db.Model):
    """Dental metadata referencing the shared attachment store."""
    __tablename__ = "clinic_dental_image"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "attachment_id", name="uq_clinic_dental_image_attachment"),
        db.Index("ix_clinic_dental_image_patient", "tenant_id", "patient_id", "image_type"),
        db.Index("ix_clinic_dental_image_visit", "tenant_id", "visit_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    attachment_id = db.Column(db.Integer, db.ForeignKey("clinic_attachment.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=True, index=True)
    treatment_plan_item_id = db.Column(
        db.Integer, db.ForeignKey("clinic_dental_treatment_plan_item.id"), nullable=True, index=True
    )
    treatment_plan_id = db.Column(
        db.Integer, db.ForeignKey("clinic_dental_treatment_plan.id"), nullable=True, index=True
    )
    dental_session_id = db.Column(
        db.Integer, db.ForeignKey("clinic_dental_session.id"), nullable=True, index=True
    )
    tooth_number = db.Column(db.String(4), nullable=True, index=True)
    image_type = db.Column(db.String(40), nullable=False, default="other", index=True)
    captured_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicPediatricProfile(db.Model):
    """Patient-level pediatric birth/feeding profile (one per patient)."""
    __tablename__ = "clinic_pediatric_profile"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "patient_id", name="uq_clinic_pediatric_profile_patient"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    gestational_age_weeks = db.Column(db.Numeric(4, 1), nullable=True)
    birth_weight = db.Column(db.Numeric(6, 2), nullable=True)  # kg
    birth_length = db.Column(db.Numeric(6, 2), nullable=True)  # cm
    birth_head_circumference = db.Column(db.Numeric(6, 2), nullable=True)  # cm
    delivery_type = db.Column(db.String(30), nullable=True)
    nicu_admission = db.Column(db.Boolean, nullable=False, default=False)
    nicu_days = db.Column(db.Integer, nullable=True)
    neonatal_complications = db.Column(db.Text, nullable=True)
    feeding_type = db.Column(db.String(40), nullable=True)
    feeding_notes = db.Column(db.Text, nullable=True)
    weaning_status = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicPediatricVaccinationRecord(db.Model):
    __tablename__ = "clinic_pediatric_vaccination"
    __table_args__ = (
        db.Index("ix_clinic_ped_vax_patient", "tenant_id", "patient_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    vaccine_name = db.Column(db.String(200), nullable=False)
    dose_label = db.Column(db.String(80), nullable=True)
    dose_number = db.Column(db.Integer, nullable=True)
    scheduled_date = db.Column(db.Date, nullable=True)
    administered_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(40), nullable=False, default="recorded")
    source = db.Column(db.String(40), nullable=False, default="clinic")
    notes = db.Column(db.Text, nullable=True)
    attachment_id = db.Column(db.Integer, db.ForeignKey("clinic_attachment.id"), nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicPediatricDevelopmentRecord(db.Model):
    """Visit-scoped developmental documentation (no automatic scoring)."""
    __tablename__ = "clinic_pediatric_development"
    __table_args__ = (
        db.Index("ix_clinic_ped_dev_patient", "tenant_id", "patient_id", "recorded_at"),
        db.Index("ix_clinic_ped_dev_visit", "tenant_id", "visit_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=True, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True)
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    domains_json = db.Column(db.Text, nullable=True)  # domain → {status, notes}
    notes = db.Column(db.Text, nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicGynecologyProfile(db.Model):
    """Patient-level reproductive / gynecologic history (one per patient)."""
    __tablename__ = "clinic_gynecology_profile"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "patient_id", name="uq_clinic_gyn_profile_patient"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    menarche_age = db.Column(db.Integer, nullable=True)
    cycle_regular = db.Column(db.Boolean, nullable=True)
    cycle_length_days = db.Column(db.Integer, nullable=True)
    bleeding_duration_days = db.Column(db.Integer, nullable=True)
    last_menstrual_period = db.Column(db.Date, nullable=True)  # general menstrual LMP (not pregnancy dating)
    menstrual_notes = db.Column(db.Text, nullable=True)
    contraception_notes = db.Column(db.Text, nullable=True)
    gynecologic_history = db.Column(db.Text, nullable=True)
    previous_gynecologic_surgeries = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicPregnancy(db.Model):
    """Pregnancy episode — one patient may have many over time."""
    __tablename__ = "clinic_pregnancy"
    __table_args__ = (
        db.Index("ix_clinic_pregnancy_patient", "tenant_id", "patient_id", "status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    created_by_doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True)
    status = db.Column(db.String(30), nullable=False, default="active")
    lmp_date = db.Column(db.Date, nullable=True)
    edd_date = db.Column(db.Date, nullable=True)
    dating_method = db.Column(db.String(30), nullable=True)
    gravida_at_start = db.Column(db.Integer, nullable=True)
    para_at_start = db.Column(db.Integer, nullable=True)
    abortions_at_start = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.Date, nullable=True)
    ended_at = db.Column(db.Date, nullable=True)
    outcome = db.Column(db.String(40), nullable=True)
    delivery_type = db.Column(db.String(30), nullable=True)
    gestational_duration_weeks = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicPregnancyObservation(db.Model):
    """Visit-linked antenatal observation (vitals stay on ClinicVital)."""
    __tablename__ = "clinic_pregnancy_observation"
    __table_args__ = (
        db.Index("ix_clinic_preg_obs_pregnancy", "tenant_id", "pregnancy_id", "created_at"),
        db.Index("ix_clinic_preg_obs_visit", "tenant_id", "visit_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    pregnancy_id = db.Column(db.Integer, db.ForeignKey("clinic_pregnancy.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=True, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True)
    gestational_age_weeks = db.Column(db.Integer, nullable=True)
    gestational_age_days = db.Column(db.Integer, nullable=True)
    fundal_height_cm = db.Column(db.Numeric(6, 2), nullable=True)
    fetal_heart_rate = db.Column(db.Integer, nullable=True)
    fetal_movement_notes = db.Column(db.Text, nullable=True)
    presentation = db.Column(db.String(80), nullable=True)
    edema_notes = db.Column(db.Text, nullable=True)
    clinical_notes = db.Column(db.Text, nullable=True)
    # Optional structured ultrasound documentation (not an ultrasound engine)
    ultrasound_json = db.Column(db.Text, nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicChronicCondition(db.Model):
    """Patient-level chronic disease registry (one row per condition episode)."""
    __tablename__ = "clinic_chronic_condition"
    __table_args__ = (
        db.Index("ix_clinic_chronic_patient", "tenant_id", "patient_id", "status"),
        db.Index("ix_clinic_chronic_code", "tenant_id", "patient_id", "condition_code"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    condition_code = db.Column(db.String(60), nullable=False, default="other")
    condition_name = db.Column(db.String(200), nullable=False)
    diagnosis_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="active")
    severity = db.Column(db.String(30), nullable=True)
    source = db.Column(db.String(40), nullable=False, default="clinician")
    notes = db.Column(db.Text, nullable=True)
    detail_json = db.Column(db.Text, nullable=True)  # disease-pack clinician fields
    linked_diagnosis_id = db.Column(db.Integer, db.ForeignKey("clinic_diagnosis.id"), nullable=True)
    created_by_doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicPatientMedication(db.Model):
    """Clinician-confirmed current / longitudinal medication status."""
    __tablename__ = "clinic_patient_medication"
    __table_args__ = (
        db.Index("ix_clinic_patient_med", "tenant_id", "patient_id", "status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    drug_name = db.Column(db.String(200), nullable=False)
    dose_text = db.Column(db.String(120), nullable=True)
    frequency = db.Column(db.String(120), nullable=True)
    route = db.Column(db.String(60), nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="active")  # active|stopped|historical
    source = db.Column(db.String(40), nullable=False, default="clinician")
    notes = db.Column(db.Text, nullable=True)
    prescription_item_id = db.Column(db.Integer, db.ForeignKey("clinic_prescription_item.id"), nullable=True)
    created_by_doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicCardiologyProfile(db.Model):
    """Patient-level cardiology history context (conditions stay on ClinicChronicCondition)."""
    __tablename__ = "clinic_cardiology_profile"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "patient_id", name="uq_clinic_cardio_profile_patient"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    family_cardiac_history = db.Column(db.Text, nullable=True)
    smoking_status = db.Column(db.String(30), nullable=True)  # never|former|current|unknown
    smoking_notes = db.Column(db.Text, nullable=True)
    previous_mi_date = db.Column(db.Date, nullable=True)
    previous_pci_notes = db.Column(db.Text, nullable=True)
    previous_cabg_notes = db.Column(db.Text, nullable=True)
    device_type = db.Column(db.String(40), nullable=True)  # none|pacemaker|icd|crt|other
    device_implant_date = db.Column(db.Date, nullable=True)
    device_history = db.Column(db.Text, nullable=True)
    other_cardiac_history = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicCardiologyECG(db.Model):
    """Clinician-entered ECG structured record (no automatic interpretation)."""
    __tablename__ = "clinic_cardiology_ecg"
    __table_args__ = (
        db.Index("ix_clinic_cardio_ecg_patient", "tenant_id", "patient_id", "recorded_at"),
        db.Index("ix_clinic_cardio_ecg_visit", "tenant_id", "visit_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=True, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True)
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    heart_rate = db.Column(db.Integer, nullable=True)
    rhythm = db.Column(db.String(120), nullable=True)
    axis = db.Column(db.String(80), nullable=True)
    pr_interval_ms = db.Column(db.Integer, nullable=True)
    qrs_duration_ms = db.Column(db.Integer, nullable=True)
    qtc_ms = db.Column(db.Integer, nullable=True)
    st_t_notes = db.Column(db.Text, nullable=True)
    interpretation = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    attachment_id = db.Column(db.Integer, db.ForeignKey("clinic_attachment.id"), nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


class ClinicCardiologyEcho(db.Model):
    """Clinician/reporter-entered Echo summary (no automatic EF classification)."""
    __tablename__ = "clinic_cardiology_echo"
    __table_args__ = (
        db.Index("ix_clinic_cardio_echo_patient", "tenant_id", "patient_id", "recorded_at"),
        db.Index("ix_clinic_cardio_echo_visit", "tenant_id", "visit_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("clinic_patient.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("clinic_visit.id"), nullable=True, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("clinic_doctor.id"), nullable=True)
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    lvef_percent = db.Column(db.Numeric(5, 2), nullable=True)
    lv_notes = db.Column(db.Text, nullable=True)
    rv_notes = db.Column(db.Text, nullable=True)
    la_notes = db.Column(db.Text, nullable=True)
    ra_notes = db.Column(db.Text, nullable=True)
    valve_notes = db.Column(db.Text, nullable=True)
    pericardium_notes = db.Column(db.Text, nullable=True)
    other_measurements_json = db.Column(db.Text, nullable=True)
    impression = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    radiology_order_id = db.Column(db.Integer, db.ForeignKey("clinic_radiology_order.id"), nullable=True)
    attachment_id = db.Column(db.Integer, db.ForeignKey("clinic_attachment.id"), nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)


CLINIC_MODELS = (
    ClinicSettings,
    ClinicPatient,
    ClinicDoctor,
    ClinicSpecialty,
    ClinicDoctorSpecialty,
    ClinicVisitTemplate,
    ClinicVisitTemplateSection,
    ClinicVisitTemplateField,
    ClinicRoom,
    ClinicService,
    ClinicServiceSpecialty,
    ClinicDoctorService,
    ClinicDoctorSchedule,
    ClinicDoctorTimeOff,
    ClinicAppointment,
    ClinicAppointmentStatusHistory,
    ClinicVisit,
    ClinicVisitFieldValue,
    ClinicVital,
    ClinicDiagnosis,
    ClinicPrescription,
    ClinicPrescriptionItem,
    ClinicPrescriptionTemplate,
    ClinicPrescriptionTemplateItem,
    ClinicInvoice,
    ClinicInvoiceItem,
    ClinicPayment,
    ClinicAuditLog,
    ClinicInventoryItem,
    ClinicInventoryBatch,
    ClinicInventoryMovement,
    ClinicProcedure,
    ClinicProcedureSpecialty,
    ClinicProcedureRecipeItem,
    ClinicVisitProcedure,
    ClinicVisitBillLine,
    ClinicLabTest,
    ClinicLabOrder,
    ClinicLabOrderItem,
    ClinicRadiologyOrder,
    ClinicDoctorSettlement,
    ClinicSupplier,
    ClinicPurchase,
    ClinicPurchaseItem,
    ClinicPurchasePayment,
    ClinicPurchaseReceipt,
    ClinicPurchaseReceiptItem,
    ClinicPurchaseRequest,
    ClinicPurchaseRequestItem,
    ClinicPurchaseReturn,
    ClinicPurchaseReturnItem,
    ClinicPurchaseAttachment,
    ClinicFollowUp,
    ClinicFollowUpAttempt,
    ClinicReminder,
    ClinicReminderRule,
    ClinicMessageLog,
    ClinicConversation,
    ClinicConversationMessage,
    ClinicPublicChatToken,
    ClinicMessageTemplate,
    ClinicBookingRequest,
    ClinicPublicBookingToken,
    ClinicCommunicationTask,
    ClinicBookingAttempt,
    ClinicBookingOtp,
    ClinicExpense,
    ClinicRefund,
    ClinicAttachment,
    ClinicConsent,
    ClinicCashSession,
    AccountingPosting,
    ClinicDentalRecord,
    ClinicDentalToothFinding,
    ClinicDentalToothEvent,
    ClinicDentalToothProcedure,
    ClinicDentalTreatmentPlan,
    ClinicDentalTreatmentOption,
    ClinicDentalTreatmentPlanItem,
    ClinicDentalTreatmentPlanItemLink,
    ClinicDentalSession,
    ClinicDentalImage,
    ClinicPediatricProfile,
    ClinicPediatricVaccinationRecord,
    ClinicPediatricDevelopmentRecord,
    ClinicGynecologyProfile,
    ClinicPregnancy,
    ClinicPregnancyObservation,
    ClinicChronicCondition,
    ClinicPatientMedication,
    ClinicCardiologyProfile,
    ClinicCardiologyECG,
    ClinicCardiologyEcho,
)

APPOINTMENT_STATUSES = (
    "pending",
    "confirmed",
    "arrived",
    "waiting",
    "in_consultation",
    "completed",
    "cancelled",
    "rescheduled",
    "no_show",
)

CLINIC_TYPES = (
    ("single_doctor", "عيادة طبيب واحد"),
    ("multi_doctor", "عيادة متعددة الأطباء"),
    ("medical_center", "مجمع طبي"),
    ("dental", "عيادة أسنان"),
    ("dermatology", "جلدية"),
    ("cosmetic", "تجميل"),
    ("pediatrics", "أطفال"),
    ("gynecology", "نسائية"),
    ("ophthalmology", "عيون"),
    ("ent", "أنف وأذن وحنجرة"),
    ("physiotherapy", "علاج طبيعي"),
    ("general_practice", "طب عام"),
    ("custom", "تخصص مخصص"),
)

WEEKDAY_LABELS = (
    "الإثنين",
    "الثلاثاء",
    "الأربعاء",
    "الخميس",
    "الجمعة",
    "السبت",
    "الأحد",
)

RADIOLOGY_MODALITIES = (
    ("xray", "أشعة سينية"),
    ("ultrasound", "سونار"),
    ("ct", "مقطعية"),
    ("mri", "رنين مغناطيسي"),
    ("mammography", "ماموغرام"),
    ("other", "أخرى"),
)
