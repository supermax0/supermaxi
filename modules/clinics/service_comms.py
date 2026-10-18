"""Reminders, follow-ups, and WhatsApp messaging for clinics."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from flask import current_app

from extensions import db
from modules.clinics.models import (
    ClinicAppointment,
    ClinicDoctor,
    ClinicFollowUp,
    ClinicMessageLog,
    ClinicPatient,
    ClinicReminder,
    ClinicReminderRule,
    ClinicVisit,
)
from modules.clinics.service import (
    _audit,
    _parse_date,
    _today,
    get_or_create_settings,
    patient_dict,
)


MESSAGE_TEMPLATES = {
    "appointment_confirmation": (
        "مرحباً {patient_name}\n"
        "تم تأكيد موعدك مع {doctor_name}\n"
        "بتاريخ {date} الساعة {time}"
    ),
    "appointment_reminder": (
        "نذكرك بموعدك مع {doctor_name}\n"
        "اليوم {date} الساعة {time}"
    ),
    "follow_up": (
        "حان موعد مراجعتك مع {doctor_name}\n"
        "يرجى التواصل مع العيادة لحجز موعد"
    ),
    "lab_result": "نتيجة الفحص أصبحت جاهزة. يرجى مراجعة العيادة.",
}


def _render_template(key: str, **ctx) -> str:
    tpl = MESSAGE_TEMPLATES.get(key, "")
    try:
        return tpl.format(**ctx)
    except Exception:
        return tpl


def _normalize_phone(phone: str) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if digits.startswith("0"):
        digits = "964" + digits[1:]
    if digits.startswith("964"):
        return digits
    if digits:
        return digits
    return ""


def log_message(
    tenant_id: int,
    *,
    recipient: str,
    template_key: str,
    body: str,
    patient_id=None,
    reference_type=None,
    reference_id=None,
    status: str = "queued",
    failed_reason: str | None = None,
) -> ClinicMessageLog:
    row = ClinicMessageLog(
        tenant_id=tenant_id,
        patient_id=patient_id,
        recipient=recipient,
        template_key=template_key,
        channel="whatsapp",
        status=status,
        message_body=body,
        failed_reason=failed_reason,
        sent_at=datetime.utcnow() if status == "sent" else None,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    db.session.add(row)
    db.session.flush()
    return row


def send_whatsapp(tenant_id: int, phone: str, body: str, *, template_key: str, patient_id=None, ref_type=None, ref_id=None) -> dict:
    settings = get_or_create_settings(tenant_id)
    normalized = _normalize_phone(phone)
    if not normalized:
        log_message(
            tenant_id,
            recipient=phone or "",
            template_key=template_key,
            body=body,
            patient_id=patient_id,
            reference_type=ref_type,
            reference_id=ref_id,
            status="failed",
            failed_reason="رقم هاتف غير صالح",
        )
        return {"ok": False, "error": "رقم هاتف غير صالح"}

    if not settings.whatsapp_notifications_enabled:
        log_message(
            tenant_id,
            recipient=normalized,
            template_key=template_key,
            body=body,
            patient_id=patient_id,
            reference_type=ref_type,
            reference_id=ref_id,
            status="skipped",
            failed_reason="واتساب غير مفعّل",
        )
        return {"ok": False, "skipped": True}

    try:
        external_message_id = None
        # Prefer the tenant-scoped WhatsApp channel already configured in
        # Finora Sales AI. This preserves its encrypted credentials, webhook
        # identity and delivery receipts instead of creating a second adapter.
        try:
            from modules.ai_sales.channels import channel_client, outbound_message_id
            from modules.ai_sales.models import AISalesChannelAccount

            channel = (
                AISalesChannelAccount.query.filter_by(channel_type="whatsapp", is_active=True)
                .filter(AISalesChannelAccount.access_token_encrypted.isnot(None))
                .order_by(AISalesChannelAccount.last_webhook_at.desc(), AISalesChannelAccount.id.desc())
                .first()
            )
            if channel:
                external_message_id = outbound_message_id(channel_client(channel).send_text(normalized, body)) or None
        except Exception:
            current_app.logger.exception("Tenant WhatsApp channel send failed")
        if not external_message_id:
            from social_ai.messaging import send_whatsapp_message
            external_message_id = send_whatsapp_message(normalized, body)
        if not external_message_id:
            log_message(
                tenant_id, recipient=normalized, template_key=template_key, body=body,
                patient_id=patient_id, reference_type=ref_type, reference_id=ref_id,
                status="failed", failed_reason="لم يؤكد WhatsApp Cloud API إرسال الرسالة",
            )
            return {"ok": False, "error": "تعذر إرسال رسالة WhatsApp"}
        log_message(
            tenant_id,
            recipient=normalized,
            template_key=template_key,
            body=body,
            patient_id=patient_id,
            reference_type=ref_type,
            reference_id=ref_id,
            status="sent",
        )
        return {"ok": True, "external_message_id": external_message_id}
    except Exception as exc:
        log_message(
            tenant_id,
            recipient=normalized,
            template_key=template_key,
            body=body,
            patient_id=patient_id,
            reference_type=ref_type,
            reference_id=ref_id,
            status="failed",
            failed_reason=str(exc),
        )
        return {"ok": False, "error": str(exc)}


def queue_appointment_confirmation(tenant_id: int, appointment_id: int) -> None:
    appt = ClinicAppointment.query.filter_by(tenant_id=tenant_id, id=appointment_id).first()
    if not appt or not appt.patient:
        return
    doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=appt.doctor_id).first() if appt.doctor_id else None
    body = _render_template(
        "appointment_confirmation",
        patient_name=appt.patient.full_name,
        doctor_name=doctor.full_name if doctor else "الطبيب",
        date=appt.appointment_date.isoformat() if appt.appointment_date else "",
        time=appt.start_time.strftime("%H:%M") if appt.start_time else "",
    )
    key = f"confirm:{appointment_id}"
    if ClinicReminder.query.filter_by(tenant_id=tenant_id, idempotency_key=key).first():
        return
    db.session.add(
        ClinicReminder(
            tenant_id=tenant_id,
            reminder_type="appointment_confirmation",
            reference_type="appointment",
            reference_id=appointment_id,
            patient_id=appt.patient_id,
            scheduled_for=datetime.utcnow(),
            status="pending",
            idempotency_key=key,
            message_body=body,
        )
    )


def process_pending_reminders(tenant_id: int) -> dict:
    now = datetime.utcnow()
    rows = (
        ClinicReminder.query.filter(
            ClinicReminder.tenant_id == tenant_id,
            ClinicReminder.status == "pending",
            ClinicReminder.scheduled_for <= now,
        )
        .order_by(ClinicReminder.id.asc())
        .limit(50)
        .all()
    )
    sent = failed = 0
    for row in rows:
        if row.channel != "whatsapp":
            row.status = "failed"
            failed += 1
            continue
        patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=row.patient_id).first() if row.patient_id else None
        phone = patient.phone if patient else ""
        result = send_whatsapp(
            tenant_id,
            phone,
            row.message_body or "",
            template_key=row.reminder_type,
            patient_id=row.patient_id,
            ref_type=row.reference_type,
            ref_id=row.reference_id,
        )
        if result.get("ok"):
            row.status = "sent"
            row.sent_at = datetime.utcnow()
            sent += 1
        elif result.get("skipped"):
            row.status = "skipped"
        else:
            row.status = "failed"
            failed += 1
    return {"processed": len(rows), "sent": sent, "failed": failed}


def schedule_appointment_reminders(tenant_id: int, day: date | None = None) -> int:
    settings = get_or_create_settings(tenant_id)
    rules = ClinicReminderRule.query.filter_by(tenant_id=tenant_id, active=True).order_by(ClinicReminderRule.hours_before.desc()).all()
    if not rules:
        template = MESSAGE_TEMPLATES["appointment_reminder"]
        for hours in sorted({24, int(settings.reminder_hours_before or 24), 2}, reverse=True):
            rule = ClinicReminderRule(tenant_id=tenant_id, name=f"تذكير قبل {hours} ساعة", hours_before=hours, channel="whatsapp", template_body=template)
            db.session.add(rule)
            rules.append(rule)
        db.session.flush()
    now = datetime.utcnow()
    max_hours = max((r.hours_before for r in rules), default=24)
    through = (day or _today()) + timedelta(days=max(2, (max_hours // 24) + 2))
    appts = ClinicAppointment.query.filter(
        ClinicAppointment.tenant_id == tenant_id,
        ClinicAppointment.appointment_date >= (day or _today()),
        ClinicAppointment.appointment_date <= through,
        ClinicAppointment.status.in_(("pending", "confirmed", "scheduled")),
    ).all()
    created = 0
    for appt in appts:
        for rule in rules:
            scheduled = datetime.combine(appt.appointment_date, appt.start_time or time(9, 0)) - timedelta(hours=rule.hours_before)
            if scheduled < now - timedelta(hours=1):
                continue
            key = f"appointment:{appt.id}:rule:{rule.id}:at:{scheduled.isoformat()}"
            if ClinicReminder.query.filter_by(tenant_id=tenant_id, idempotency_key=key).first():
                continue
            patient = appt.patient
            doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=appt.doctor_id).first() if appt.doctor_id else None
            ctx = {"patient_name": patient.full_name if patient else "", "doctor_name": doctor.full_name if doctor else "الطبيب", "date": appt.appointment_date.isoformat(), "time": appt.start_time.strftime("%H:%M") if appt.start_time else ""}
            try: body = rule.template_body.format(**ctx)
            except Exception: body = rule.template_body
            db.session.add(ClinicReminder(
                tenant_id=tenant_id, reminder_type=f"appointment_reminder_{rule.hours_before}h",
                reference_type="appointment", reference_id=appt.id, patient_id=appt.patient_id,
                channel=rule.channel, scheduled_for=scheduled, status="pending",
                idempotency_key=key, message_body=body,
            ))
            created += 1
    return created


def followup_dict(row: ClinicFollowUp, tenant_id: int) -> dict:
    patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=row.patient_id).first()
    doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=row.doctor_id).first() if row.doctor_id else None
    return {
        "id": row.id,
        "patient_id": row.patient_id,
        "patient_name": patient.full_name if patient else "",
        "patient_phone": patient.phone if patient else "",
        "doctor_id": row.doctor_id,
        "doctor_name": doctor.full_name if doctor else "",
        "visit_id": row.visit_id,
        "due_date": row.due_date.isoformat(),
        "status": row.status,
        "notes": row.notes or "",
        "contacted_at": row.contacted_at.isoformat() if row.contacted_at else "",
    }


def list_followups(tenant_id: int, status: str | None = None) -> list[dict]:
    query = ClinicFollowUp.query.filter_by(tenant_id=tenant_id)
    if status:
        query = query.filter_by(status=status)
    else:
        query = query.filter(ClinicFollowUp.status.in_(("due", "contacted", "scheduled")))
    rows = query.order_by(ClinicFollowUp.due_date.asc()).limit(200).all()
    return [followup_dict(r, tenant_id) for r in rows]


def create_followup_from_visit(tenant_id: int, visit_id: int, payload: dict, actor_id=None) -> dict:
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    settings = get_or_create_settings(tenant_id)
    days = int(payload.get("followup_after_days") or settings.default_followup_days or 7)
    due = _parse_date(payload.get("due_date"), "موعد المتابعة") if payload.get("due_date") else (_today() + timedelta(days=days))
    row = ClinicFollowUp(
        tenant_id=tenant_id,
        patient_id=visit.patient_id,
        visit_id=visit_id,
        doctor_id=visit.doctor_id,
        due_date=due,
        status="due",
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
    )
    db.session.add(row)
    visit.follow_up_date = due
    db.session.flush()
    _audit(tenant_id, actor_id, "follow_up", row.id, "create", "متابعة مريض")
    return followup_dict(row, tenant_id)


def update_followup(tenant_id: int, followup_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicFollowUp.query.filter_by(tenant_id=tenant_id, id=followup_id).first()
    if not row:
        raise ValueError("المتابعة غير موجودة")
    if "status" in payload:
        row.status = str(payload.get("status") or row.status)
        if row.status == "contacted" and not row.contacted_at:
            row.contacted_at = datetime.utcnow()
    if "notes" in payload:
        row.notes = str(payload.get("notes") or "").strip() or None
    if "due_date" in payload and payload.get("due_date"):
        row.due_date = _parse_date(payload.get("due_date"), "موعد المتابعة")
    row.updated_at = datetime.utcnow()
    return followup_dict(row, tenant_id)


def list_message_logs(tenant_id: int, limit: int = 100) -> list[dict]:
    rows = (
        ClinicMessageLog.query.filter_by(tenant_id=tenant_id)
        .order_by(ClinicMessageLog.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "recipient": r.recipient,
            "template_key": r.template_key,
            "status": r.status,
            "message_body": r.message_body or "",
            "failed_reason": r.failed_reason or "",
            "sent_at": r.sent_at.isoformat() if r.sent_at else "",
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in rows
    ]


def comms_dashboard(tenant_id: int) -> dict:
    settings = get_or_create_settings(tenant_id)
    today = _today()
    credentials_ready = bool(
        current_app.config.get("WHATSAPP_ACCESS_TOKEN")
        and current_app.config.get("WHATSAPP_PHONE_NUMBER_ID")
    )
    channel_state = None
    try:
        from modules.ai_sales.models import AISalesChannelAccount
        channel_state = (
            AISalesChannelAccount.query.filter_by(channel_type="whatsapp", is_active=True)
            .order_by(AISalesChannelAccount.last_webhook_at.desc(), AISalesChannelAccount.id.desc())
            .first()
        )
        credentials_ready = credentials_ready or bool(channel_state and channel_state.access_token_encrypted)
    except Exception:
        channel_state = None
    connected = bool(
        settings.whatsapp_notifications_enabled
        and credentials_ready
        and (not channel_state or channel_state.connection_status in ("connected", "verified", "ready"))
    )
    return {
        "whatsapp_enabled": connected,
        "whatsapp_configured": credentials_ready,
        "whatsapp_connection_status": channel_state.connection_status if channel_state else ("configured" if credentials_ready else "error"),
        "whatsapp_last_sync": channel_state.last_webhook_at.isoformat() if channel_state and channel_state.last_webhook_at else "",
        "whatsapp_error": (channel_state.last_error or "") if channel_state else ("" if credentials_ready else "مفتاح WhatsApp Cloud API أو معرف الرقم غير مضبوط"),
        "pending_reminders": ClinicReminder.query.filter_by(tenant_id=tenant_id, status="pending").count(),
        "due_followups": ClinicFollowUp.query.filter_by(tenant_id=tenant_id, status="due").filter(
            ClinicFollowUp.due_date <= today
        ).count(),
        "recent_messages": list_message_logs(tenant_id, limit=10),
        "booking_url_hint": "/c/{tenant_slug}",
    }
