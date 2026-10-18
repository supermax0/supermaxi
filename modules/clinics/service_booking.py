"""Public online booking for Finora Clinics."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
import hashlib
import secrets

from flask import request
from sqlalchemy import func

from extensions import db
from models.tenant import Tenant
from modules.clinics.models import (
    ClinicAppointment,
    ClinicBookingAttempt,
    ClinicBookingRequest,
    ClinicDoctor,
    ClinicPatient,
    ClinicService,
    ClinicSettings,
    ClinicPublicBookingToken,
    ClinicConversation,
    ClinicConversationMessage,
    ClinicPublicChatToken,
)
from modules.clinics.schema import ensure_clinics_schema
from modules.clinics.service import (
    _audit,
    _parse_date,
    _parse_time,
    _today,
    appointment_dict,
    create_appointment,
    create_patient,
    get_or_create_settings,
    list_doctors,
    list_services,
)
from modules.clinics.service_ops import assert_doctor_available
from modules.clinics.service_specialties import (
    assert_doctor_specialty,
    doctor_specialties,
    list_specialties,
    primary_specialty_id,
)


def _tenant_id() -> int:
    row = Tenant.query.first()
    return int(row.id) if row else 1


def _client_ip() -> str:
    return (request.headers.get("X-Forwarded-For") or request.remote_addr or "0.0.0.0").split(",")[0].strip()


def _normalize_public_phone(phone: str) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())[-15:]
    if digits.startswith("0"):
        digits = "964" + digits[1:]
    return digits


def _check_rate_limit(tenant_id: int) -> None:
    settings = get_or_create_settings(tenant_id)
    limit = int(settings.booking_rate_limit_per_hour or 10)
    if limit <= 0:
        return
    since = datetime.utcnow() - timedelta(hours=1)
    count = (
        ClinicBookingAttempt.query.filter(
            ClinicBookingAttempt.tenant_id == tenant_id,
            ClinicBookingAttempt.ip_address == _client_ip(),
            ClinicBookingAttempt.created_at >= since,
        ).count()
    )
    if count >= limit:
        raise ValueError("تم تجاوز حد الحجوزات المسموح — حاول لاحقاً")


def _log_booking_attempt(tenant_id: int, phone: str, success: bool) -> None:
    db.session.add(
        ClinicBookingAttempt(
            tenant_id=tenant_id,
            ip_address=_client_ip(),
            phone=phone or None,
            success=bool(success),
        )
    )


def public_clinic_info(tenant_id: int) -> dict:
    settings = get_or_create_settings(tenant_id)
    if not bool(getattr(settings, "public_profile_enabled", True)):
        raise ValueError("الصفحة العامة غير مفعّلة لهذه العيادة")
    doctors = [{
        "id": row["id"],
        "full_name": row["full_name"],
        "specialty": row["specialty"],
        "primary_specialty_id": row.get("primary_specialty_id"),
        "specialty_ids": row.get("specialty_ids") or [],
        "color": row["color"],
    } for row in list_doctors(tenant_id, active_only=True)]
    services = [{
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "specialty_ids": row["specialty_ids"],
        "doctor_ids": row["doctor_ids"],
        "duration_minutes": row["duration_minutes"],
        "description": row["description"],
        "price": row["price"] if bool(getattr(settings, "public_show_prices", False)) else None,
    } for row in list_services(tenant_id, active_only=True)]
    return {
        "clinic_name": settings.clinic_name or "عيادة Finora",
        "welcome_text": settings.booking_welcome_text or "احجز موعدك بسهولة وأمان",
        "doctors": doctors,
        "specialties": [{key: item[key] for key in ("id", "code", "name_ar", "name_en", "icon")}
                        for item in list_specialties(tenant_id, active_only=True)],
        "services": services,
        "slot_minutes": settings.appointment_slot_minutes,
        "otp_required": bool(getattr(settings, "booking_otp_enabled", False)),
        "booking_mode": getattr(settings, "booking_mode", "direct") or "direct",
        "booking_enabled": bool(settings.allow_online_booking),
        "chat_enabled": bool(getattr(settings, "public_chat_enabled", True)),
        "allow_same_day_booking": bool(getattr(settings, "allow_same_day_booking", True)),
        "maximum_advance_booking_days": int(getattr(settings, "maximum_advance_booking_days", 60) or 60),
        "whatsapp_number": getattr(settings, "clinic_whatsapp_number", None) or "",
        "phone": getattr(settings, "clinic_whatsapp_number", None) or "",
        "logo_url": getattr(settings, "public_logo_url", None) or "",
        "location": getattr(settings, "public_location", None) or "",
        "working_hours": getattr(settings, "public_working_hours", None) or "",
    }


def available_slots(
    tenant_id: int,
    doctor_id: int,
    day: date,
    service_id: int | None = None,
    exclude_appointment_id: int | None = None,
    specialty_id: int | None = None,
) -> list[str]:
    from modules.clinics.service import assert_service_selection
    if specialty_id:
        assert_doctor_specialty(tenant_id, doctor_id, specialty_id)
    assert_service_selection(tenant_id, service_id, doctor_id, specialty_id)
    settings = get_or_create_settings(tenant_id)
    now = datetime.now()
    if day < _today():
        return []
    if day == _today() and not bool(getattr(settings, "allow_same_day_booking", True)):
        return []
    if day > _today() + timedelta(days=int(getattr(settings, "maximum_advance_booking_days", 60) or 60)):
        return []
    doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id, active=True).first()
    if not doctor:
        raise ValueError("الطبيب غير متاح")
    slot_minutes = settings.appointment_slot_minutes or 15
    if service_id:
        service = ClinicService.query.filter_by(tenant_id=tenant_id, id=service_id, active=True).first()
        if service:
            slot_minutes = max(slot_minutes, int(service.duration_minutes or slot_minutes))

    from modules.clinics.models import ClinicDoctorSchedule

    schedules = ClinicDoctorSchedule.query.filter_by(
        tenant_id=tenant_id, doctor_id=doctor_id, weekday=day.weekday(), active=True
    ).all()
    if not schedules:
        # Public availability must never invent working hours. Reception may
        # still create an exceptional appointment, but the portal only exposes
        # explicitly configured schedules.
        return []
    windows = [(s.start_time, s.end_time) for s in schedules]

    taken = ClinicAppointment.query.filter(
        ClinicAppointment.tenant_id == tenant_id,
        ClinicAppointment.doctor_id == doctor_id,
        ClinicAppointment.appointment_date == day,
        ClinicAppointment.status.notin_(("cancelled", "rescheduled", "no_show")),
    ).all()
    if exclude_appointment_id:
        taken = [a for a in taken if a.id != int(exclude_appointment_id)]

    def overlaps(start: time, end: time, other_start: time, other_end: time) -> bool:
        return start < other_end and other_start < end

    slots: list[str] = []
    notice_cutoff = now + timedelta(hours=int(getattr(settings, "minimum_booking_notice_hours", 0) or 0))
    for w_start, w_end in windows:
        cursor = datetime.combine(day, w_start)
        end_dt = datetime.combine(day, w_end)
        while cursor + timedelta(minutes=slot_minutes) <= end_dt:
            slot_start = cursor.time()
            slot_end = (cursor + timedelta(minutes=slot_minutes)).time()
            try:
                assert_doctor_available(tenant_id, doctor_id, day, slot_start, slot_end)
            except ValueError:
                cursor += timedelta(minutes=slot_minutes)
                continue
            conflict = any(
                overlaps(slot_start, slot_end, a.start_time, a.end_time or a.start_time)
                for a in taken
            )
            if cursor <= notice_cutoff:
                cursor += timedelta(minutes=slot_minutes)
                continue
            if not conflict:
                slots.append(slot_start.strftime("%H:%M"))
            cursor += timedelta(minutes=slot_minutes)
    return slots


def first_available_doctor(tenant_id: int, service_id: int | None = None, from_day: date | None = None, specialty_id: int | None = None) -> dict:
    settings = get_or_create_settings(tenant_id)
    start = from_day or _today()
    doctors = ClinicDoctor.query.filter_by(tenant_id=tenant_id, active=True).order_by(ClinicDoctor.full_name).all()
    if specialty_id:
        from modules.clinics.models import ClinicDoctorSpecialty
        assert_doctor_specialty(tenant_id, None, specialty_id)
        ids = {row.doctor_id for row in ClinicDoctorSpecialty.query.filter_by(tenant_id=tenant_id, specialty_id=specialty_id).all()}
        doctors = [doctor for doctor in doctors if doctor.id in ids]
    max_days = min(30, int(getattr(settings, "maximum_advance_booking_days", 60) or 60))
    for offset in range(max_days + 1):
        day = start + timedelta(days=offset)
        candidates = []
        for doctor in doctors:
            from modules.clinics.service import assert_service_selection
            try:
                assert_service_selection(tenant_id, service_id, doctor.id, specialty_id)
            except ValueError:
                continue
            slots = available_slots(tenant_id, doctor.id, day, service_id, specialty_id=specialty_id)
            if slots:
                candidates.append((slots[0], doctor))
        if candidates:
            slot, doctor = sorted(candidates, key=lambda item: item[0])[0]
            return {"doctor_id": doctor.id, "doctor_name": doctor.full_name, "specialty": doctor.specialty or "", "date": day.isoformat(), "time": slot}
    raise ValueError("لا يوجد موعد متاح خلال الفترة القادمة")


def create_online_booking(tenant_id: int, payload: dict) -> dict:
    ensure_clinics_schema()
    settings = get_or_create_settings(tenant_id)
    if not settings.allow_online_booking:
        raise ValueError("الحجز الإلكتروني غير مفعّل")
    _check_rate_limit(tenant_id)

    full_name = str(payload.get("full_name") or "").strip()
    phone = str(payload.get("phone") or "").strip()
    if not full_name or not phone:
        raise ValueError("الاسم والهاتف مطلوبان")

    if settings.booking_otp_enabled:
        from modules.clinics.service_extras import verify_booking_otp

        verify_booking_otp(tenant_id, phone, payload.get("otp") or "")

    day = _parse_date(payload.get("appointment_date") or _today().isoformat(), "تاريخ الموعد")
    start = _parse_time(payload.get("start_time"), "وقت الموعد")
    doctor_id = int(payload["doctor_id"]) if payload.get("doctor_id") else None
    service_id = int(payload["service_id"]) if payload.get("service_id") else None
    specialty_id = int(payload["specialty_id"]) if payload.get("specialty_id") else primary_specialty_id(tenant_id, doctor_id)
    from modules.clinics.service import assert_service_selection
    assert_service_selection(tenant_id, service_id, doctor_id, specialty_id)

    if doctor_id:
        assert_doctor_specialty(tenant_id, doctor_id, specialty_id)
        assert_doctor_available(tenant_id, doctor_id, day, start)
    if start.strftime("%H:%M") not in available_slots(tenant_id, doctor_id, day, service_id, specialty_id=specialty_id):
        alternatives = available_slots(tenant_id, doctor_id, day, service_id, specialty_id=specialty_id)[:3]
        suffix = f" الأوقات المتاحة: {', '.join(alternatives)}" if alternatives else ""
        raise ValueError("عذراً، تم حجز هذا الوقت للتو." + suffix)

    normalized_phone = _normalize_public_phone(phone)
    patient = next(
        (candidate for candidate in ClinicPatient.query.filter_by(tenant_id=tenant_id).filter(ClinicPatient.phone.isnot(None)).all()
         if _normalize_public_phone(candidate.phone) == normalized_phone),
        None,
    )
    if phone and patient:
        service = ClinicService.query.filter_by(tenant_id=tenant_id, id=service_id).first() if service_id else None
        duration = int(service.duration_minutes if service else settings.appointment_slot_minutes or 15)
        requested_end = (datetime.combine(day, start) + timedelta(minutes=duration)).time()
        same_patient_day = (
            ClinicAppointment.query.join(ClinicPatient, ClinicPatient.id == ClinicAppointment.patient_id)
            .filter(
                ClinicAppointment.tenant_id == tenant_id,
                ClinicAppointment.appointment_date == day,
                ClinicAppointment.status.notin_(("cancelled", "no_show", "rescheduled")),
                ClinicAppointment.patient_id == patient.id,
            ).all()
        )
        if any(a.start_time < requested_end and start < (a.end_time or a.start_time) for a in same_patient_day):
            raise ValueError("لديك موعد آخر متعارض مع هذا الوقت")

    if not patient:
        patient_data = create_patient(tenant_id, {"full_name": full_name, "phone": phone})
        patient_id = patient_data["id"]
    else:
        patient_id = patient.id
        if patient.full_name != full_name:
            patient.full_name = full_name

    active_count = ClinicAppointment.query.filter(
        ClinicAppointment.tenant_id == tenant_id,
        ClinicAppointment.patient_id == patient_id,
        ClinicAppointment.appointment_date >= _today(),
        ClinicAppointment.status.in_(("pending", "confirmed", "scheduled")),
    ).count()
    if active_count >= int(getattr(settings, "max_active_appointments_per_patient", 3) or 3):
        raise ValueError("تم بلوغ الحد الأقصى للمواعيد النشطة")

    source = str(payload.get("source") or "public_booking").strip().lower()
    if source not in {"public_booking", "whatsapp", "web_chat", "instagram", "facebook", "external"}:
        source = "public_booking"
    if getattr(settings, "booking_mode", "direct") == "approval":
        booking_request = ClinicBookingRequest(
            tenant_id=tenant_id, patient_id=patient_id, doctor_id=doctor_id, service_id=service_id,
            specialty_id=specialty_id,
            requested_start=datetime.combine(day, start), status="pending_approval", source=source,
            notes=str(payload.get("notes") or "").strip() or None,
        )
        db.session.add(booking_request); db.session.flush()
        _log_booking_attempt(tenant_id, phone, True)
        _audit(tenant_id, None, "booking_request", booking_request.id, "create", f"طلب حجز إلكتروني {full_name}")
        return {"mode": "approval", "request_id": booking_request.id, "status": "pending_approval", "patient_name": full_name, "appointment_date": day.isoformat(), "start_time": start.strftime("%H:%M")}

    appt_payload = {
        "patient_id": patient_id,
        "doctor_id": doctor_id,
        "service_id": service_id,
        "specialty_id": specialty_id,
        "appointment_date": day.isoformat(),
        "start_time": start.strftime("%H:%M"),
        "appointment_type": "online",
        "status": "confirmed",
        "source": source,
        "notes": str(payload.get("notes") or "").strip() or None,
    }
    result = create_appointment(tenant_id, appt_payload)
    appt = ClinicAppointment.query.filter_by(tenant_id=tenant_id, id=result["id"]).first()
    if appt:
        appt.source = source
    _log_booking_attempt(tenant_id, phone, True)
    _audit(tenant_id, None, "appointment", result["id"], "online_booking", f"حجز إلكتروني {full_name}")

    try:
        from modules.clinics.service_comms import queue_appointment_confirmation

        queue_appointment_confirmation(tenant_id, result["id"])
    except Exception:
        pass

    raw_token = issue_manage_token(tenant_id, result["id"])
    result.update({"mode": "direct", "manage_token": raw_token, "booking_number": f"APT-{result['id']:05d}"})
    return result


def _token_hash(raw: str) -> str:
    return hashlib.sha256(str(raw).encode("utf-8")).hexdigest()


def issue_manage_token(tenant_id: int, appointment_id: int) -> str:
    raw = secrets.token_urlsafe(32)
    db.session.add(ClinicPublicBookingToken(tenant_id=tenant_id, appointment_id=appointment_id, token_hash=_token_hash(raw), expires_at=datetime.utcnow() + timedelta(days=180)))
    db.session.flush()
    return raw


def _appointment_for_token(tenant_id: int, raw_token: str) -> ClinicAppointment:
    token = ClinicPublicBookingToken.query.filter_by(tenant_id=tenant_id, token_hash=_token_hash(raw_token)).first()
    if not token or token.revoked_at or token.expires_at <= datetime.utcnow():
        raise ValueError("رابط إدارة الموعد غير صالح")
    appt = ClinicAppointment.query.filter_by(tenant_id=tenant_id, id=token.appointment_id).first()
    if not appt: raise ValueError("الموعد غير موجود")
    return appt


def public_manage_info(tenant_id: int, raw_token: str) -> dict:
    appt = _appointment_for_token(tenant_id, raw_token)
    return {
        "id": appt.id,
        "booking_number": f"APT-{appt.id:05d}",
        "patient_name": appt.patient.full_name if appt.patient else "",
        "doctor_id": appt.doctor_id,
        "doctor_name": appt.doctor.full_name if appt.doctor else "",
        "service_id": appt.service_id,
        "service_name": appt.service.name if appt.service else "",
        "appointment_date": appt.appointment_date.isoformat(),
        "start_time": appt.start_time.strftime("%H:%M"),
        "status": appt.status,
    }


def public_reschedule(tenant_id: int, raw_token: str, payload: dict) -> dict:
    from modules.clinics.service import reschedule_appointment
    settings = get_or_create_settings(tenant_id)
    if not getattr(settings, "allow_public_reschedule", True): raise ValueError("إعادة الجدولة غير متاحة إلكترونياً")
    appt = _appointment_for_token(tenant_id, raw_token)
    day = _parse_date(payload.get("appointment_date"), "التاريخ")
    start = _parse_time(payload.get("start_time"), "الوقت")
    if start.strftime("%H:%M") not in available_slots(tenant_id, appt.doctor_id, day, appt.service_id, appt.id): raise ValueError("عذراً، هذا الوقت لم يعد متاحاً")
    old = f"{appt.appointment_date.isoformat()} {appt.start_time.strftime('%H:%M')}"
    result = reschedule_appointment(tenant_id, appt.id, {"appointment_date": day.isoformat(), "start_time": start.strftime("%H:%M"), "source": "public_patient"})
    _audit(tenant_id, None, "appointment", appt.id, "public_reschedule", "إعادة جدولة عبر الرابط", meta={"old_datetime": old, "new_datetime": f"{day.isoformat()} {start.strftime('%H:%M')}"})
    return result


def public_cancel(tenant_id: int, raw_token: str, reason: str = "") -> dict:
    from modules.clinics.service import change_appointment_status
    settings = get_or_create_settings(tenant_id)
    if not getattr(settings, "allow_public_cancellation", True): raise ValueError("الإلغاء غير متاح إلكترونياً")
    appt = _appointment_for_token(tenant_id, raw_token)
    start_at = datetime.combine(appt.appointment_date, appt.start_time)
    if start_at - datetime.now() < timedelta(hours=int(getattr(settings, "cancellation_deadline_hours", 4) or 0)): raise ValueError("انتهت مهلة الإلغاء الإلكتروني")
    result = change_appointment_status(tenant_id, appt.id, "cancelled", note=str(reason or "إلغاء من المريض"))
    _audit(tenant_id, None, "appointment", appt.id, "public_cancel", "إلغاء عبر الرابط", meta={"reason": reason})
    return result


def create_public_chat(tenant_id: int, payload: dict) -> dict:
    """Create a rate-limited inbox conversation without exposing private data."""
    _check_rate_limit(tenant_id)
    name = str(payload.get("full_name") or "").strip()
    phone = str(payload.get("phone") or "").strip()
    message = str(payload.get("message") or "").strip()
    if not name or not phone or not message:
        raise ValueError("الاسم والهاتف والرسالة مطلوبة")
    if len(message) > 2000:
        raise ValueError("الرسالة أطول من الحد المسموح")
    settings = get_or_create_settings(tenant_id)
    if not bool(getattr(settings, "public_chat_enabled", True)):
        raise ValueError("الدردشة غير متاحة حالياً")
    from modules.clinics.service_engagement import receive_inbound

    thread_key = secrets.token_urlsafe(18)
    result = receive_inbound(
        tenant_id, phone=phone, content=message, channel="web_chat",
        external_thread_id=f"web_chat:{thread_key}",
        external_message_id=f"web_chat:{secrets.token_urlsafe(18)}", contact_name=name,
    )
    raw_token = secrets.token_urlsafe(32)
    db.session.add(ClinicPublicChatToken(
        tenant_id=tenant_id,
        conversation_id=result["conversation_id"],
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        expires_at=datetime.utcnow() + timedelta(days=7),
    ))
    _log_booking_attempt(tenant_id, phone, True)
    _audit(tenant_id, None, "conversation", result["conversation_id"], "public_web_chat", "رسالة من بوابة الحجز")
    return {"chat_token": raw_token, "received": True}


def _public_chat_token(tenant_id: int, raw_token: str) -> ClinicPublicChatToken:
    token_hash = hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()
    row = ClinicPublicChatToken.query.filter_by(tenant_id=tenant_id, token_hash=token_hash).first()
    if not row or row.expires_at < datetime.utcnow():
        raise ValueError("انتهت جلسة المحادثة")
    return row


def public_chat_messages(tenant_id: int, raw_token: str) -> list[dict]:
    token = _public_chat_token(tenant_id, raw_token)
    rows = ClinicConversationMessage.query.filter(
        ClinicConversationMessage.tenant_id == tenant_id,
        ClinicConversationMessage.conversation_id == token.conversation_id,
        ClinicConversationMessage.message_type == "text",
    ).order_by(ClinicConversationMessage.created_at, ClinicConversationMessage.id).limit(200).all()
    return [{
        "id": row.id,
        "direction": row.direction,
        "message": row.content,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    } for row in rows]


def send_public_chat_message(tenant_id: int, raw_token: str, payload: dict) -> dict:
    token = _public_chat_token(tenant_id, raw_token)
    content = str(payload.get("message") or "").strip()
    if not content or len(content) > 2000:
        raise ValueError("اكتب رسالة لا تتجاوز 2000 حرف")
    conversation = ClinicConversation.query.filter_by(tenant_id=tenant_id, id=token.conversation_id).first()
    if not conversation:
        raise ValueError("المحادثة غير متاحة")
    message = ClinicConversationMessage(
        tenant_id=tenant_id, conversation_id=conversation.id, direction="incoming",
        message_type="text", channel="web_chat", content=content, status="received",
        external_message_id=f"web_chat:{secrets.token_urlsafe(18)}",
    )
    # Keep the public write deliberately small: no patient details are accepted.
    db.session.add(message)
    conversation.unread_count = int(conversation.unread_count or 0) + 1
    conversation.status = "new" if conversation.status == "closed" else conversation.status
    conversation.last_message_preview = content[:300]
    conversation.last_message_at = datetime.utcnow()
    db.session.flush()
    return {"id": message.id, "received": True}
