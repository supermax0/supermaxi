from datetime import date, timedelta

import pytest
from flask import Flask

from extensions import db


@pytest.fixture()
def engagement_db():
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite:///:memory:", SQLALCHEMY_TRACK_MODIFICATIONS=False, TESTING=True, SECRET_KEY="test")
    db.init_app(app)
    import models  # noqa: F401
    from models.delivery_agent import DeliveryAgent  # noqa: F401
    from modules.clinics import models as clinic_models  # noqa: F401
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_inbound_message_matches_patient_and_is_idempotent(engagement_db):
    from modules.clinics.service import create_patient
    from modules.clinics.service_engagement import conversation_detail, receive_inbound

    with engagement_db.app_context():
        patient = create_patient(1, {"full_name": "محمد حسن", "phone": "07701234567"})
        first = receive_inbound(1, phone="+9647701234567", content="أريد موعداً", external_message_id="wa-1")
        duplicate = receive_inbound(1, phone="+9647701234567", content="أريد موعداً", external_message_id="wa-1")
        db.session.flush()
        detail = conversation_detail(1, first["conversation_id"])
        assert first["patient_id"] == patient["id"]
        assert duplicate["duplicate"] is True
        assert len(detail["messages"]) == 1


def test_unknown_conversation_can_create_and_attach_patient(engagement_db):
    from modules.clinics.service_engagement import attach_patient, receive_inbound

    with engagement_db.app_context():
        inbound = receive_inbound(1, phone="07709998888", content="مرحباً", channel="web")
        patient = attach_patient(1, inbound["conversation_id"], {"full_name": "زهراء علي", "phone": "07709998888"})
        assert patient["phone"] == "07709998888"


def test_public_booking_approval_and_direct_secure_token(engagement_db):
    from modules.clinics.service import create_doctor, create_service, get_or_create_settings
    from modules.clinics.service_booking import create_online_booking, public_manage_info
    from modules.clinics.service_ops import upsert_schedule

    with engagement_db.app_context(), engagement_db.test_request_context("/book/test/api/book", method="POST"):
        settings = get_or_create_settings(1)
        settings.allow_online_booking = True
        settings.minimum_booking_notice_hours = 0
        doctor = create_doctor(1, {"full_name": "د. علي"})
        service = create_service(1, {"name": "مراجعة", "duration_minutes": 30})
        day = (date.today() + timedelta(days=2)).isoformat()
        upsert_schedule(1, {"doctor_id": doctor["id"], "weekday": (date.today() + timedelta(days=2)).weekday(), "start_time": "09:00", "end_time": "17:00", "slot_minutes": 30})
        settings.booking_mode = "approval"
        pending = create_online_booking(1, {"full_name": "أحمد كريم", "phone": "07701110000", "doctor_id": doctor["id"], "service_id": service["id"], "appointment_date": day, "start_time": "10:00"})
        assert pending["status"] == "pending_approval"
        settings.booking_mode = "direct"
        booked = create_online_booking(1, {"full_name": "سارة كريم", "phone": "07702220000", "doctor_id": doctor["id"], "service_id": service["id"], "appointment_date": day, "start_time": "11:00"})
        assert booked["manage_token"]
        assert public_manage_info(1, booked["manage_token"])["booking_number"].startswith("APT-")


def test_public_web_chat_enters_real_inbox(engagement_db):
    from modules.clinics.service import get_or_create_settings
    from modules.clinics.service_booking import create_public_chat, public_chat_messages, send_public_chat_message
    from modules.clinics.models import ClinicConversation

    with engagement_db.app_context(), engagement_db.test_request_context("/book/test/api/chat", method="POST"):
        get_or_create_settings(1).booking_rate_limit_per_hour = 10
        result = create_public_chat(1, {"full_name": "نور", "phone": "07703334444", "message": "أريد موعداً"})
        db.session.flush()
        assert "conversation_id" not in result
        assert ClinicConversation.query.one().channel == "web_chat"
        assert public_chat_messages(1, result["chat_token"])[0]["message"] == "أريد موعداً"
        send_public_chat_message(1, result["chat_token"], {"message": "هل يوجد موعد غداً؟"})
        assert len(public_chat_messages(1, result["chat_token"])) == 2


def test_booking_qr_always_targets_public_portal():
    from modules.clinics.service_extras import booking_qr_payload

    basic = booking_qr_payload("alshifa-clinic", "https://www.finora.company")
    doctor = booking_qr_payload("alshifa-clinic", "https://www.finora.company", doctor_id=23)
    service = booking_qr_payload("alshifa-clinic", "https://www.finora.company", service_id=8)
    assert basic["url"] == "https://www.finora.company/c/alshifa-clinic"
    assert doctor["url"].endswith("/c/alshifa-clinic?doctor=23")
    assert service["url"].endswith("/c/alshifa-clinic?service=8")
    assert all("/clinics" not in item["url"] and "/book/" not in item["url"] for item in (basic, doctor, service))


def test_public_profile_does_not_expose_doctor_private_fields(engagement_db):
    from modules.clinics.service import create_doctor, create_service, get_or_create_settings
    from modules.clinics.service_booking import public_clinic_info

    with engagement_db.app_context():
        get_or_create_settings(1).public_show_prices = False
        create_doctor(1, {"full_name": "د. سارة", "phone": "07700000000", "license_number": "SECRET", "commission_pct": 20})
        create_service(1, {"name": "فحص", "price": 25000, "doctor_commission_pct": 15})
        info = public_clinic_info(1)
        assert set(info["doctors"][0]) == {"id", "full_name", "specialty", "color", "primary_specialty_id", "specialty_ids"}
        for specialty in info["specialties"]:
            assert set(specialty) == {"id", "code", "name_ar", "name_en", "icon"}
        assert "doctor_commission_pct" not in info["services"][0]
        assert info["services"][0]["price"] is None


def test_message_placeholders_and_shortcut_expand(engagement_db):
    from modules.clinics.service import get_or_create_settings
    from modules.clinics.service_engagement import expand_message_shortcut, fill_message_placeholders

    with engagement_db.app_context(), engagement_db.test_request_context("https://www.finora.company/clinics"):
        settings = get_or_create_settings(1)
        settings.clinic_name = "عيادة الشفاء"
        settings.public_location = "الكرادة"
        settings.public_working_hours = "9ص-5م"
        filled = fill_message_placeholders(1, "أهلاً في {{clinic_name}} — {{clinic_location}} — {{clinic_hours}}")
        assert filled == "أهلاً في عيادة الشفاء — الكرادة — 9ص-5م"
        expanded = expand_message_shortcut(1, "/اهلا")
        assert "عيادة الشفاء" in expanded
        assert "{{clinic_name}}" not in expanded


def test_reminder_rules_are_idempotent(engagement_db):
    from modules.clinics.service import create_appointment, create_doctor, create_patient, get_or_create_settings
    from modules.clinics.service_comms import schedule_appointment_reminders
    from modules.clinics.models import ClinicReminder

    with engagement_db.app_context():
        get_or_create_settings(1).reminder_hours_before = 24
        patient = create_patient(1, {"full_name": "مريم", "phone": "07704445555"})
        doctor = create_doctor(1, {"full_name": "د. نور"})
        day = date.today() + timedelta(days=2)
        create_appointment(1, {"patient_id": patient["id"], "doctor_id": doctor["id"], "appointment_date": day.isoformat(), "start_time": "12:00"})
        first = schedule_appointment_reminders(1)
        second = schedule_appointment_reminders(1)
        assert first == 2
        assert second == 0
        assert ClinicReminder.query.filter_by(tenant_id=1).count() == 2
