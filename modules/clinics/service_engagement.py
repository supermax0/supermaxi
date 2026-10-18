"""Unified patient communications and booking operations.

The module deliberately composes the existing patient, appointment, availability,
follow-up, WhatsApp and audit services instead of duplicating their rules.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import or_

from extensions import db
from models.employee import Employee
from modules.clinics.models import (
    ClinicAppointment,
    ClinicBookingRequest,
    ClinicCommunicationTask,
    ClinicConversation,
    ClinicConversationMessage,
    ClinicDoctor,
    ClinicFollowUp,
    ClinicMessageTemplate,
    ClinicPatient,
    ClinicReminder,
    ClinicReminderRule,
    ClinicService,
    ClinicVisit,
)
from modules.clinics.service import _audit, _parse_date, _today, create_appointment, create_patient, patient_dict
from modules.clinics.service_comms import _normalize_phone, send_whatsapp


CONVERSATION_STATUSES = {"new", "waiting_reply", "waiting_patient", "in_progress", "resolved", "closed"}
DEFAULT_TEMPLATES = (
    ("/اهلا", "ترحيب", "أهلاً وسهلاً بكم في عيادة {{clinic_name}}"),
    ("/الحجز", "رابط الحجز", "يمكنكم حجز موعد من الرابط:\n{{booking_link}}"),
    ("/الدوام", "أوقات الدوام", "أوقات دوام العيادة:\n{{clinic_hours}}"),
    ("/الموقع", "موقع العيادة", "موقع العيادة:\n{{clinic_location}}"),
    ("/تأكيد", "تأكيد موعد", "موعدكم {{appointment_date}} الساعة {{appointment_time}} مع {{doctor_name}}"),
)


def _employee_names(tenant_id: int) -> dict[int, str]:
    return {r.id: r.name for r in Employee.query.filter_by(tenant_id=tenant_id, is_active=True).all()}


def ensure_default_templates(tenant_id: int) -> None:
    if ClinicMessageTemplate.query.filter_by(tenant_id=tenant_id).first():
        return
    for shortcut, title, body in DEFAULT_TEMPLATES:
        db.session.add(ClinicMessageTemplate(tenant_id=tenant_id, shortcut=shortcut, title=title, body=body))
    db.session.flush()


def fill_message_placeholders(tenant_id: int, body: str, conversation: ClinicConversation | None = None) -> str:
    """Replace {{clinic_name}} / {{booking_link}} style tokens before send or preview."""
    from flask import g, request

    from modules.clinics.service import get_or_create_settings

    text = str(body or "")
    if "{{" not in text and "{patient_name}" not in text:
        return text
    settings = get_or_create_settings(tenant_id)
    slug = (getattr(g, "tenant", None) or "").strip()
    try:
        origin = (request.url_root or "").rstrip("/")
    except Exception:
        origin = ""
    booking_link = f"{origin}/c/{slug}" if origin and slug else (f"/c/{slug}" if slug else "")
    patient = conversation.patient if conversation and conversation.patient_id else None
    next_appt = None
    if conversation and conversation.patient_id:
        next_appt = (
            ClinicAppointment.query.filter(
                ClinicAppointment.tenant_id == tenant_id,
                ClinicAppointment.patient_id == conversation.patient_id,
                ClinicAppointment.appointment_date >= _today(),
                ClinicAppointment.status.in_(("pending", "confirmed", "scheduled")),
            )
            .order_by(ClinicAppointment.appointment_date, ClinicAppointment.start_time)
            .first()
        )
    doctor_name = ""
    appointment_date = ""
    appointment_time = ""
    if next_appt:
        appointment_date = next_appt.appointment_date.isoformat() if next_appt.appointment_date else ""
        appointment_time = next_appt.start_time.strftime("%H:%M") if next_appt.start_time else ""
        if next_appt.doctor_id:
            doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=next_appt.doctor_id).first()
            doctor_name = doctor.full_name if doctor else ""
    values = {
        "clinic_name": settings.clinic_name or "العيادة",
        "booking_link": booking_link,
        "clinic_hours": getattr(settings, "public_working_hours", None) or "حسب جدول العيادة",
        "clinic_location": getattr(settings, "public_location", None) or "راجع موقع العيادة",
        "patient_name": (patient.full_name if patient else (conversation.contact_name if conversation else "")) or "المريض",
        "phone": (patient.phone if patient else (conversation.contact_phone if conversation else "")) or "",
        "doctor_name": doctor_name or "الطبيب",
        "appointment_date": appointment_date or "—",
        "appointment_time": appointment_time or "—",
    }
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
        text = text.replace("{" + key + "}", str(value))
    return text


def expand_message_shortcut(tenant_id: int, content: str, conversation: ClinicConversation | None = None) -> str:
    """If the composer is only a /shortcut, expand it to the rendered template body."""
    raw = str(content or "").strip()
    if not raw.startswith("/"):
        return fill_message_placeholders(tenant_id, raw, conversation)
    ensure_default_templates(tenant_id)
    shortcut = raw.split(None, 1)[0]
    row = ClinicMessageTemplate.query.filter_by(tenant_id=tenant_id, shortcut=shortcut, active=True).first()
    if not row:
        return fill_message_placeholders(tenant_id, raw, conversation)
    return fill_message_placeholders(tenant_id, row.body, conversation)


def _message_dict(row: ClinicConversationMessage, names: dict[int, str]) -> dict:
    return {
        "id": row.id, "direction": row.direction, "type": row.message_type,
        "channel": row.channel, "content": row.content, "status": row.status,
        "sender_name": names.get(row.sender_user_id, ""), "attachment_url": row.attachment_url or "",
        "failed_reason": row.failed_reason or "", "reference_type": row.reference_type or "",
        "reference_id": row.reference_id, "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def _conversation_dict(row: ClinicConversation, names: dict[int, str], sensitive: bool = True) -> dict:
    patient = row.patient
    return {
        "id": row.id, "patient_id": row.patient_id,
        "display_name": patient.full_name if patient else (row.contact_name or row.contact_phone or "رقم غير مسجل"),
        "patient_file": patient.file_number if patient else "", "phone": (patient.phone if patient else (row.contact_phone or "")) if sensitive else "",
        "channel": row.channel, "status": row.status, "unread_count": row.unread_count or 0,
        "assigned_user_id": row.assigned_user_id, "assigned_name": names.get(row.assigned_user_id, "غير مسند"),
        "last_message": row.last_message_preview or "", "last_message_at": row.last_message_at.isoformat() if row.last_message_at else "",
        "opened_by": row.opened_by, "opened_by_name": names.get(row.opened_by, ""),
    }


def list_conversations(tenant_id: int, filters: dict, sensitive: bool = True) -> list[dict]:
    names = _employee_names(tenant_id)
    query = ClinicConversation.query.filter_by(tenant_id=tenant_id)
    status = str(filters.get("status") or "").strip()
    channel = str(filters.get("channel") or "").strip()
    assigned = filters.get("assigned_user_id")
    q = str(filters.get("q") or "").strip()
    if status == "unread": query = query.filter(ClinicConversation.unread_count > 0)
    elif status: query = query.filter_by(status=status)
    if channel: query = query.filter_by(channel=channel)
    if assigned: query = query.filter_by(assigned_user_id=int(assigned))
    if q:
        like = f"%{q}%"
        query = query.outerjoin(ClinicPatient, ClinicPatient.id == ClinicConversation.patient_id).filter(or_(
            ClinicPatient.full_name.ilike(like), ClinicPatient.phone.ilike(like),
            ClinicConversation.contact_phone.ilike(like), ClinicConversation.last_message_preview.ilike(like),
        ))
    return [_conversation_dict(r, names, sensitive) for r in query.order_by(ClinicConversation.last_message_at.desc()).limit(200).all()]


def patient_context(tenant_id: int, patient_id: int | None, sensitive: bool = True) -> dict | None:
    if not patient_id:
        return None
    patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first()
    if not patient:
        return None
    last_visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).order_by(ClinicVisit.visit_date.desc()).first()
    next_appt = ClinicAppointment.query.filter(
        ClinicAppointment.tenant_id == tenant_id, ClinicAppointment.patient_id == patient_id,
        ClinicAppointment.appointment_date >= _today(), ClinicAppointment.status.in_(("pending", "confirmed", "scheduled")),
    ).order_by(ClinicAppointment.appointment_date, ClinicAppointment.start_time).first()
    followups = ClinicFollowUp.query.filter(
        ClinicFollowUp.tenant_id == tenant_id, ClinicFollowUp.patient_id == patient_id,
        ClinicFollowUp.status.in_(("due", "scheduled", "contacted")),
    ).count()
    data = patient_dict(patient)
    if not sensitive:
        for key in ("phone", "secondary_phone", "gender", "date_of_birth", "age", "national_id", "address", "city", "emergency_contact", "emergency_phone"):
            data.pop(key, None)
    data.update({
        "last_visit": last_visit.visit_date.isoformat() if last_visit else "",
        "next_appointment": ({"id": next_appt.id, "date": next_appt.appointment_date.isoformat(), "time": next_appt.start_time.strftime("%H:%M"), "doctor": next_appt.doctor.full_name if next_appt.doctor else ""} if next_appt else None),
        "open_followups": followups,
    })
    return data


def conversation_detail(tenant_id: int, conversation_id: int, actor_id=None, sensitive: bool = True) -> dict:
    row = ClinicConversation.query.filter_by(tenant_id=tenant_id, id=conversation_id).first()
    if not row: raise ValueError("المحادثة غير موجودة")
    row.unread_count = 0
    row.opened_by, row.opened_at = actor_id, datetime.utcnow()
    names = _employee_names(tenant_id)
    messages = ClinicConversationMessage.query.filter_by(tenant_id=tenant_id, conversation_id=row.id).order_by(ClinicConversationMessage.created_at).limit(500).all()
    return {"conversation": _conversation_dict(row, names, sensitive), "messages": [_message_dict(m, names) for m in messages], "patient": patient_context(tenant_id, row.patient_id, sensitive)}


def create_conversation(tenant_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    patient_id = int(payload.get("patient_id") or 0) or None
    patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first() if patient_id else None
    phone = str(payload.get("phone") or (patient.phone if patient else "")).strip()
    if not phone: raise ValueError("رقم الهاتف مطلوب")
    row = ClinicConversation(tenant_id=tenant_id, branch_id=branch_id, patient_id=patient_id, channel=str(payload.get("channel") or "whatsapp"), contact_name=str(payload.get("contact_name") or "").strip() or None, contact_phone=phone, assigned_user_id=actor_id, status="new")
    db.session.add(row); db.session.flush()
    _audit(tenant_id, actor_id, "conversation", row.id, "create", "إنشاء محادثة", branch_id=branch_id)
    return _conversation_dict(row, _employee_names(tenant_id))


def receive_inbound(tenant_id: int, *, phone: str, content: str, channel="whatsapp", external_thread_id=None, external_message_id=None, contact_name=None) -> dict:
    normalized = _normalize_phone(phone)
    patient = None
    for candidate in ClinicPatient.query.filter_by(tenant_id=tenant_id).filter(ClinicPatient.phone.isnot(None)).all():
        if _normalize_phone(candidate.phone) == normalized:
            patient = candidate; break
    row = ClinicConversation.query.filter_by(tenant_id=tenant_id, channel=channel, external_thread_id=external_thread_id).first() if external_thread_id else None
    if not row:
        row = ClinicConversation.query.filter_by(tenant_id=tenant_id, channel=channel, contact_phone=phone).filter(ClinicConversation.status != "closed").order_by(ClinicConversation.id.desc()).first()
    if not row:
        row = ClinicConversation(tenant_id=tenant_id, patient_id=patient.id if patient else None, channel=channel, external_thread_id=external_thread_id, contact_name=contact_name, contact_phone=phone, status="new")
        db.session.add(row); db.session.flush()
    elif patient and not row.patient_id:
        row.patient_id = patient.id
    if external_message_id and ClinicConversationMessage.query.filter_by(tenant_id=tenant_id, external_message_id=external_message_id).first():
        return {"conversation_id": row.id, "duplicate": True}
    msg = ClinicConversationMessage(tenant_id=tenant_id, conversation_id=row.id, direction="incoming", channel=channel, content=str(content or "").strip(), status="delivered", external_message_id=external_message_id, delivered_at=datetime.utcnow())
    db.session.add(msg)
    row.last_message_preview, row.last_message_at = msg.content[:300], datetime.utcnow()
    row.unread_count = int(row.unread_count or 0) + 1
    if row.status in ("resolved", "closed", "waiting_patient"): row.status = "waiting_reply"
    return {"conversation_id": row.id, "patient_id": row.patient_id, "duplicate": False}


def send_message(tenant_id: int, conversation_id: int, payload: dict, actor_id=None) -> dict:
    conversation = ClinicConversation.query.filter_by(tenant_id=tenant_id, id=conversation_id).first()
    if not conversation: raise ValueError("المحادثة غير موجودة")
    raw_content = str(payload.get("content") or "").strip()
    message_type = str(payload.get("type") or "text")
    if not raw_content: raise ValueError("نص الرسالة مطلوب")
    content = (
        raw_content
        if message_type == "internal_note"
        else expand_message_shortcut(tenant_id, raw_content, conversation)
    )
    result = {}
    failed_reason = None
    if message_type == "internal_note":
        status = "internal"
    elif conversation.channel == "whatsapp":
        result = send_whatsapp(tenant_id, conversation.contact_phone or "", content, template_key="conversation_reply", patient_id=conversation.patient_id, ref_type="conversation", ref_id=conversation.id)
        status = "sent" if result.get("ok") else ("skipped" if result.get("skipped") else "failed")
        if status != "sent":
            failed_reason = result.get("error") or ("واتساب غير مفعّل أو غير مهيأ" if result.get("skipped") else "تعذر إرسال الرسالة")
    elif conversation.channel == "web_chat":
        status = "sent"
    else:
        status = "sent"
    msg = ClinicConversationMessage(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        direction="internal" if message_type == "internal_note" else "outgoing",
        message_type=message_type,
        channel=conversation.channel,
        content=content,
        status=status,
        sender_user_id=actor_id,
        external_message_id=(result.get("external_message_id") if conversation.channel == "whatsapp" and message_type != "internal_note" else None),
        sent_at=datetime.utcnow() if status == "sent" else None,
        failed_reason=failed_reason,
    )
    db.session.add(msg); db.session.flush()
    conversation.last_message_preview, conversation.last_message_at = content[:300], datetime.utcnow()
    if message_type != "internal_note": conversation.status = "waiting_patient"
    _audit(tenant_id, actor_id, "conversation", conversation.id, "message_sent", "إرسال رسالة")
    payload_out = _message_dict(msg, _employee_names(tenant_id))
    if status == "skipped":
        payload_out["warning"] = failed_reason or "تم حفظ الرسالة داخلياً لكن واتساب غير مفعّل"
    elif status == "failed":
        payload_out["warning"] = failed_reason or "فشل إرسال الرسالة عبر واتساب"
    return payload_out


def update_conversation(tenant_id: int, conversation_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicConversation.query.filter_by(tenant_id=tenant_id, id=conversation_id).first()
    if not row: raise ValueError("المحادثة غير موجودة")
    if "status" in payload:
        status = str(payload.get("status") or "")
        if status not in CONVERSATION_STATUSES: raise ValueError("حالة المحادثة غير صحيحة")
        row.status = status
    if "assigned_user_id" in payload:
        assigned = int(payload.get("assigned_user_id") or 0) or None
        if assigned and not Employee.query.filter_by(tenant_id=tenant_id, id=assigned, is_active=True).first(): raise ValueError("الموظف غير موجود")
        row.assigned_user_id = assigned
    _audit(tenant_id, actor_id, "conversation", row.id, "update", "تحديث المحادثة")
    return _conversation_dict(row, _employee_names(tenant_id))


def attach_patient(tenant_id: int, conversation_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    row = ClinicConversation.query.filter_by(tenant_id=tenant_id, id=conversation_id).first()
    if not row: raise ValueError("المحادثة غير موجودة")
    normalized = _normalize_phone(payload.get("phone") or row.contact_phone)
    patient = next((p for p in ClinicPatient.query.filter_by(tenant_id=tenant_id).filter(ClinicPatient.phone.isnot(None)).all() if _normalize_phone(p.phone) == normalized), None)
    if not patient:
        created = create_patient(tenant_id, payload, actor_id=actor_id, branch_id=branch_id)
        patient = ClinicPatient.query.get(created["id"])
    row.patient_id = patient.id
    return patient_dict(patient)


def _resolve_conversation_patient(tenant_id: int, conversation: ClinicConversation) -> ClinicPatient:
    """Ensure the conversation has a linked patient, auto-matching by phone when possible."""
    if conversation.patient_id:
        patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=conversation.patient_id).first()
        if patient:
            return patient
        conversation.patient_id = None
    phone = conversation.contact_phone or ""
    normalized = _normalize_phone(phone)
    if normalized:
        for candidate in ClinicPatient.query.filter_by(tenant_id=tenant_id).filter(ClinicPatient.phone.isnot(None)).all():
            if _normalize_phone(candidate.phone) == normalized:
                conversation.patient_id = candidate.id
                return candidate
    raise ValueError("اربط المحادثة بمريض أولاً قبل إنشاء المتابعة")


def create_followup(tenant_id: int, conversation_id: int, payload: dict, actor_id=None) -> dict:
    conversation = ClinicConversation.query.filter_by(tenant_id=tenant_id, id=conversation_id).first()
    if not conversation:
        raise ValueError("المحادثة غير موجودة")
    patient = _resolve_conversation_patient(tenant_id, conversation)
    due_raw = str(payload.get("due_date") or "").strip()
    due = _parse_date(due_raw or (_today() + timedelta(days=1)).isoformat(), "موعد المتابعة")
    # Frontend historically sent type=callback (a status), map to a valid follow-up type.
    raw_type = str(payload.get("followup_type") or payload.get("type") or "administrative").strip()
    type_aliases = {"callback": "administrative", "call": "administrative", "phone": "administrative"}
    followup_type = type_aliases.get(raw_type, raw_type) or "administrative"
    if len(followup_type) > 40:
        followup_type = followup_type[:40]
    status = "scheduled" if due > _today() else "due"
    notes = str(payload.get("notes") or "").strip() or None
    row = ClinicFollowUp(
        tenant_id=tenant_id,
        patient_id=patient.id,
        due_date=due,
        followup_type=followup_type,
        status=status,
        notes=notes,
        created_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    event = ClinicConversationMessage(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        direction="internal",
        message_type="event",
        channel="system",
        content=f"تم إنشاء متابعة بتاريخ {due.isoformat()}",
        status="internal",
        sender_user_id=actor_id,
        reference_type="followup",
        reference_id=row.id,
    )
    db.session.add(event)
    db.session.flush()
    conversation.last_message_preview = event.content[:300]
    conversation.last_message_at = datetime.utcnow()
    return {"id": row.id, "due_date": due.isoformat(), "status": status, "followup_type": followup_type, "patient_id": patient.id}


def create_task(tenant_id: int, conversation_id: int, payload: dict, actor_id=None) -> dict:
    conversation = ClinicConversation.query.filter_by(tenant_id=tenant_id, id=conversation_id).first()
    if not conversation: raise ValueError("المحادثة غير موجودة")
    title = str(payload.get("title") or "").strip()
    if not title: raise ValueError("عنوان المهمة مطلوب")
    due_at = datetime.fromisoformat(payload["due_at"]) if payload.get("due_at") else None
    row = ClinicCommunicationTask(tenant_id=tenant_id, conversation_id=conversation.id, patient_id=conversation.patient_id, title=title, due_at=due_at, assigned_user_id=int(payload.get("assigned_user_id") or 0) or actor_id, created_by=actor_id)
    db.session.add(row); db.session.flush()
    db.session.add(ClinicConversationMessage(tenant_id=tenant_id, conversation_id=conversation.id, direction="internal", message_type="event", channel="system", content=f"تم إنشاء مهمة: {title}", status="internal", sender_user_id=actor_id, reference_type="task", reference_id=row.id))
    return {"id": row.id, "title": row.title}


def templates(tenant_id: int) -> list[dict]:
    ensure_default_templates(tenant_id)
    return [{"id": r.id, "shortcut": r.shortcut, "title": r.title, "body": r.body, "active": bool(r.active)} for r in ClinicMessageTemplate.query.filter_by(tenant_id=tenant_id).order_by(ClinicMessageTemplate.id).all()]


def save_template(tenant_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicMessageTemplate.query.filter_by(tenant_id=tenant_id, id=int(payload.get("id") or 0)).first() if payload.get("id") else ClinicMessageTemplate(tenant_id=tenant_id)
    shortcut = str(payload.get("shortcut") or "").strip()
    body = str(payload.get("body") or "").strip()
    if not shortcut.startswith("/") or not body: raise ValueError("الاختصار ونص الرسالة مطلوبان")
    row.shortcut, row.title, row.body = shortcut, str(payload.get("title") or shortcut).strip(), body
    row.active, row.updated_by = bool(payload.get("active", True)), actor_id
    if not row.id: row.created_by = actor_id; db.session.add(row)
    db.session.flush()
    return {"id": row.id, "shortcut": row.shortcut, "title": row.title, "body": row.body, "active": row.active}


def booking_requests(tenant_id: int, status=None) -> list[dict]:
    query = ClinicBookingRequest.query.filter_by(tenant_id=tenant_id)
    if status: query = query.filter_by(status=status)
    rows = query.order_by(ClinicBookingRequest.created_at.desc()).limit(300).all()
    patients = {p.id: p for p in ClinicPatient.query.filter(ClinicPatient.id.in_([r.patient_id for r in rows] or [-1])).all()}
    doctors = {d.id: d for d in ClinicDoctor.query.filter(ClinicDoctor.id.in_([r.doctor_id for r in rows if r.doctor_id] or [-1])).all()}
    services = {s.id: s for s in ClinicService.query.filter(ClinicService.id.in_([r.service_id for r in rows if r.service_id] or [-1])).all()}
    return [{"id": r.id, "patient_id": r.patient_id, "patient_name": patients.get(r.patient_id).full_name if patients.get(r.patient_id) else "", "phone": patients.get(r.patient_id).phone if patients.get(r.patient_id) else "", "doctor_id": r.doctor_id, "doctor_name": doctors.get(r.doctor_id).full_name if doctors.get(r.doctor_id) else "", "service_id": r.service_id, "service_name": services.get(r.service_id).name if services.get(r.service_id) else "", "specialty_id": getattr(r, "specialty_id", None), "requested_start": r.requested_start.isoformat(), "status": r.status, "source": r.source, "appointment_id": r.appointment_id, "created_at": r.created_at.isoformat()} for r in rows]


def decide_booking_request(tenant_id: int, request_id: int, action: str, payload: dict, actor_id=None, branch_id=None) -> dict:
    row = ClinicBookingRequest.query.filter_by(tenant_id=tenant_id, id=request_id).first()
    if not row or row.status != "pending_approval": raise ValueError("طلب الحجز غير متاح")
    if action == "reject": row.status = "rejected"; return {"id": row.id, "status": row.status}
    start = datetime.fromisoformat(payload["suggested_start"]) if payload.get("suggested_start") else row.requested_start
    if action == "suggest": row.requested_start, row.status = start, "suggested"; return {"id": row.id, "status": row.status}
    if action != "approve": raise ValueError("إجراء غير مدعوم")
    appt = create_appointment(tenant_id, {"patient_id": row.patient_id, "doctor_id": row.doctor_id, "service_id": row.service_id, "specialty_id": getattr(row, "specialty_id", None), "appointment_date": start.date().isoformat(), "start_time": start.strftime("%H:%M"), "source": row.source, "status": "confirmed", "notes": row.notes}, actor_id=actor_id, branch_id=branch_id)
    row.status, row.approved_by, row.appointment_id = "approved", actor_id, appt["id"]
    return {"id": row.id, "status": row.status, "appointment": appt}


def reminder_center(tenant_id: int) -> dict:
    today = _today()
    rows = ClinicReminder.query.filter_by(tenant_id=tenant_id).order_by(ClinicReminder.scheduled_for.desc()).limit(300).all()
    patient_ids = [r.patient_id for r in rows if r.patient_id]
    patients = {p.id: p for p in ClinicPatient.query.filter(ClinicPatient.id.in_(patient_ids or [-1])).all()}
    rules = ClinicReminderRule.query.filter_by(tenant_id=tenant_id).order_by(ClinicReminderRule.hours_before.desc()).all()
    return {"stats": {"scheduled_today": sum(1 for r in rows if r.scheduled_for and r.scheduled_for.date() == today and r.status == "pending"), "sent": sum(1 for r in rows if r.status in ("sent", "delivered", "read")), "failed": sum(1 for r in rows if r.status == "failed")}, "rules": [{"id": r.id, "name": r.name, "hours_before": r.hours_before, "channel": r.channel, "template_body": r.template_body, "active": bool(r.active)} for r in rules], "items": [{"id": r.id, "patient_name": patients.get(r.patient_id).full_name if patients.get(r.patient_id) else "", "type": r.reminder_type, "channel": r.channel, "scheduled_for": r.scheduled_for.isoformat(), "status": r.status, "appointment_id": r.reference_id if r.reference_type == "appointment" else None} for r in rows]}


def save_reminder_rule(tenant_id: int, payload: dict, actor_id=None) -> dict:
    rule_id = int(payload.get("id") or 0)
    row = ClinicReminderRule.query.filter_by(tenant_id=tenant_id, id=rule_id).first() if rule_id else ClinicReminderRule(tenant_id=tenant_id)
    hours = max(1, int(payload.get("hours_before") or 24))
    channel = str(payload.get("channel") or "whatsapp")
    if channel != "whatsapp":
        raise ValueError("لا يوجد تكامل فعلي لـ SMS أو Email؛ استخدم WhatsApp المهيأ")
    body = str(payload.get("template_body") or "").strip()
    if not body:
        raise ValueError("نص التذكير مطلوب")
    row.name = str(payload.get("name") or f"تذكير قبل {hours} ساعة").strip()
    row.hours_before, row.channel, row.template_body = hours, channel, body
    row.active, row.updated_by = bool(payload.get("active", True)), actor_id
    if not row.id:
        row.created_by = actor_id
        db.session.add(row)
    db.session.flush()
    _audit(tenant_id, actor_id, "reminder_rule", row.id, "update" if rule_id else "create", row.name)
    return {"id": row.id, "name": row.name, "hours_before": row.hours_before, "channel": row.channel, "template_body": row.template_body, "active": row.active}


def engagement_snapshot(tenant_id: int) -> dict:
    today = _today()
    conversations = ClinicConversation.query.filter_by(tenant_id=tenant_id)
    today_appts = ClinicAppointment.query.filter_by(tenant_id=tenant_id, appointment_date=today).count()
    new_requests = ClinicBookingRequest.query.filter_by(tenant_id=tenant_id, status="pending_approval").count()
    reminders_today = ClinicReminder.query.filter(ClinicReminder.tenant_id == tenant_id, ClinicReminder.scheduled_for >= datetime.combine(today, datetime.min.time()), ClinicReminder.scheduled_for < datetime.combine(today + timedelta(days=1), datetime.min.time())).count()
    from modules.clinics.service import settings_payload, list_doctors, list_services
    from modules.clinics.service_comms import comms_dashboard
    ensure_default_templates(tenant_id)
    comms = comms_dashboard(tenant_id)
    return {"kpis": {"new_messages": conversations.with_entities(db.func.coalesce(db.func.sum(ClinicConversation.unread_count), 0)).scalar() or 0, "waiting_reply": conversations.filter(ClinicConversation.status.in_(("new", "waiting_reply"))).count(), "today_bookings": today_appts, "new_booking_requests": new_requests, "today_reminders": reminders_today}, "whatsapp": {"enabled": bool(comms["whatsapp_enabled"]), "configured": bool(comms.get("whatsapp_configured")), "status": comms.get("whatsapp_connection_status") or ("connected" if comms["whatsapp_enabled"] else "error"), "last_sync": comms.get("whatsapp_last_sync", ""), "error": comms.get("whatsapp_error", "")}, "staff": [{"id": i, "name": n} for i, n in _employee_names(tenant_id).items()], "doctors": list_doctors(tenant_id, True), "services": list_services(tenant_id, True), "settings": settings_payload(tenant_id)}
