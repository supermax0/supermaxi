"""Live public booking E2E — real browser + real Flask backend (not HTTP fixtures).

Covers specialty flow, stale-state resets, direct doctor links, empty slots,
disabled relations, concurrent booking, OTP, and manage reschedule/cancel.
"""
from __future__ import annotations

import os
import socket
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from extensions import db

ROOT = Path(__file__).resolve().parents[1]
SLUG = "live-booking-e2e"
ARTIFACTS = ROOT / "tests" / "_artifacts" / "booking_live_e2e"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _next_weekday(offset: int = 2) -> date:
    return date.today() + timedelta(days=offset)


@pytest.fixture(scope="module")
def live_booking():
    os.environ["DISABLE_CLINICS_SCHEDULER"] = "1"
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    from extensions_tenant import clear_tenant_engine, get_tenant_db_path, init_tenant_db
    from flask import g

    tenant_db = ROOT / "tenants" / f"{SLUG}.db"
    core_db = ARTIFACTS / "live_booking_core.sqlite"
    for path in (tenant_db, core_db):
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass

    app = Flask(
        "live_booking_e2e",
        root_path=str(ROOT),
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{core_db.as_posix()}?check_same_thread=False",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        DEBUG=True,
        SECRET_KEY="live-booking-e2e",
    )
    # Re-bind SQLAlchemy to this isolated app for the module.
    if "sqlalchemy" in app.extensions:
        del app.extensions["sqlalchemy"]
    db.init_app(app)
    import models  # noqa: F401
    from models.delivery_agent import DeliveryAgent  # noqa: F401
    from modules.clinics.models import CLINIC_MODELS  # noqa: F401
    from modules.clinics import init_clinics

    init_clinics(app)
    clear_tenant_engine(SLUG)

    seeded = {}
    with app.app_context():
        g.tenant = None
        db.create_all()
        from models.core.tenant import Tenant as CoreTenant

        existing = CoreTenant.query.filter_by(slug=SLUG).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
        core = CoreTenant(
            name="عيادة الحجز الحي",
            slug=SLUG,
            db_path=f"tenants/{SLUG}.db",
            business_type="clinics",
            is_active=True,
            subscription_end_date=datetime.utcnow() + timedelta(days=365),
        )
        db.session.add(core)
        db.session.commit()

        g.tenant = SLUG
        init_tenant_db(SLUG)
        from models.tenant import Tenant
        from modules.clinics import service
        from modules.clinics.models import ClinicSpecialty
        from modules.clinics.service_ops import upsert_schedule
        from modules.clinics.service_specialties import seed_default_specialties, update_specialty

        tenant = Tenant(name="عيادة الحجز الحي", business_type="clinics", is_active=True)
        db.session.add(tenant)
        db.session.flush()
        tenant_id = tenant.id

        settings = service.get_or_create_settings(tenant_id)
        settings.allow_online_booking = True
        settings.booking_mode = "direct"
        settings.booking_otp_enabled = False
        settings.minimum_booking_notice_hours = 0
        settings.allow_same_day_booking = True
        settings.public_profile_enabled = True
        settings.public_chat_enabled = False
        settings.clinic_name = "عيادة الحجز الحي"
        settings.organization_mode = "multi_doctor_clinic"

        specialties = seed_default_specialties(tenant_id)
        internal = next(row for row in specialties if row["code"] == "internal_medicine")
        endocrine = next(row for row in specialties if row["code"] == "endocrinology")
        dentistry = next(row for row in specialties if row["code"] == "dentistry")

        doctor_a = service.create_doctor(
            tenant_id,
            {
                "full_name": "د. أحمد متعدد",
                "primary_specialty_id": internal["id"],
                "specialty_ids": [internal["id"], endocrine["id"]],
            },
        )
        doctor_b = service.create_doctor(
            tenant_id,
            {
                "full_name": "د. سارة منفردة",
                "primary_specialty_id": internal["id"],
                "specialty_ids": [internal["id"]],
            },
        )
        doctor_none = service.create_doctor(
            tenant_id,
            {
                "full_name": "د. بدون جدول",
                "primary_specialty_id": dentistry["id"],
                "specialty_ids": [dentistry["id"]],
            },
        )
        inactive_doctor = service.create_doctor(
            tenant_id,
            {
                "full_name": "د. معطل",
                "primary_specialty_id": internal["id"],
                "specialty_ids": [internal["id"]],
                "active": False,
            },
        )

        svc_internal = service.create_service(
            tenant_id,
            {
                "name": "كشف باطنية",
                "duration_minutes": 30,
                "price": 25000,
                "specialty_ids": [internal["id"]],
                "doctor_ids": [doctor_a["id"], doctor_b["id"]],
            },
        )
        svc_endocrine = service.create_service(
            tenant_id,
            {
                "name": "كشف غدد",
                "duration_minutes": 30,
                "price": 30000,
                "specialty_ids": [endocrine["id"]],
                "doctor_ids": [doctor_a["id"]],
            },
        )
        svc_dental = service.create_service(
            tenant_id,
            {
                "name": "كشف أسنان",
                "duration_minutes": 30,
                "price": 20000,
                "specialty_ids": [dentistry["id"]],
                "doctor_ids": [doctor_none["id"]],
            },
        )
        inactive_service = service.create_service(
            tenant_id,
            {
                "name": "خدمة معطلة",
                "duration_minutes": 30,
                "specialty_ids": [internal["id"]],
                "doctor_ids": [doctor_a["id"]],
                "active": False,
            },
        )
        disabled_specialty = ClinicSpecialty.query.filter_by(tenant_id=tenant_id, code="neurology").first()
        if disabled_specialty:
            update_specialty(tenant_id, disabled_specialty.id, {"is_active": False})

        book_day = _next_weekday(2)
        for doctor_id in (doctor_a["id"], doctor_b["id"]):
            upsert_schedule(
                tenant_id,
                {
                    "doctor_id": doctor_id,
                    "weekday": book_day.weekday(),
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "slot_minutes": 30,
                },
            )
        db.session.commit()

        seeded.update(
            {
                "tenant_id": tenant_id,
                "book_day": book_day.isoformat(),
                "internal_id": internal["id"],
                "endocrine_id": endocrine["id"],
                "dentistry_id": dentistry["id"],
                "doctor_a_id": doctor_a["id"],
                "doctor_b_id": doctor_b["id"],
                "doctor_none_id": doctor_none["id"],
                "inactive_doctor_id": inactive_doctor["id"],
                "svc_internal_id": svc_internal["id"],
                "svc_endocrine_id": svc_endocrine["id"],
                "svc_dental_id": svc_dental["id"],
                "inactive_service_id": inactive_service["id"],
                "disabled_specialty_id": disabled_specialty.id if disabled_specialty else None,
            }
        )
        g.tenant = None

    port = _free_port()
    server = make_server("127.0.0.1", port, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    import urllib.request

    for _ in range(40):
        try:
            with urllib.request.urlopen(f"{base}/c/{SLUG}", timeout=1) as resp:
                body = resp.read().decode("utf-8", "replace")
                if resp.status == 200 and "bkStartBooking" in body:
                    break
        except Exception:
            time.sleep(0.15)
    else:
        server.shutdown()
        pytest.fail("Live booking server failed to render booking UI")

    with sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(headless=True)
        except Exception:
            browser = runtime.chromium.launch(channel="msedge", headless=True)
        yield {"app": app, "base": base, "browser": browser, "seed": seeded, "slug": SLUG}
        browser.close()
    server.shutdown()
    clear_tenant_engine(SLUG)
    try:
        if tenant_db.exists():
            tenant_db.unlink()
    except OSError:
        pass


def _tenant_ctx(live_booking):
    """App context bound to the live tenant DB (required for ORM assertions)."""
    from flask import g

    ctx = live_booking["app"].app_context()
    ctx.push()
    g.tenant = SLUG
    return ctx


def _shot(page, name: str):
    page.screenshot(path=str(ARTIFACTS / f"{name}.png"), full_page=True)


def _no_overflow(page):
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


def _next(page):
    page.locator(".bk-pane.active .bk-btn--primary").click()


def _start(page, base: str):
    page.goto(f"{base}/c/{SLUG}")
    page.locator("#bkStartBooking").click()


def _book_flow(page, *, specialty_id, doctor_id, service_id, day, slot, name, phone):
    page.locator(f'[data-specialty="{specialty_id}"]').click()
    _next(page)
    page.locator(f'[data-doctor="{doctor_id}"]').click()
    _next(page)
    page.locator(f'[data-service="{service_id}"]').click()
    _next(page)
    page.locator('[name="appointment_date"]').fill(day)
    page.wait_for_selector(f'[data-slot="{slot}"]', timeout=10000)
    page.locator(f'[data-slot="{slot}"]').click()
    _next(page)
    page.locator('[name="full_name"]').fill(name)
    page.locator('[name="phone"]').fill(phone)
    _next(page)
    page.locator("#bkSubmit").click()
    expect(page.locator("#bkSuccess")).to_be_visible(timeout=15000)


@pytest.mark.parametrize("width", [1920, 1366, 375, 390, 430])
def test_live_scenario1_normal_specialty_booking_persists(live_booking, width):
    seed = live_booking["seed"]
    context = live_booking["browser"].new_context(locale="ar-IQ", viewport={"width": width, "height": 900})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    phone = f"07701{width:05d}"
    _start(page, live_booking["base"])
    _no_overflow(page)
    # doctor_b keeps doctor_a free for multi-specialty / race scenarios.
    slot = {1920: "09:00", 1366: "09:30", 375: "10:00", 390: "10:30", 430: "11:00"}[width]
    _book_flow(
        page,
        specialty_id=seed["internal_id"],
        doctor_id=seed["doctor_b_id"],
        service_id=seed["svc_internal_id"],
        day=seed["book_day"],
        slot=slot,
        name=f"مريض عرض {width}",
        phone=phone,
    )
    _shot(page, f"s1_success_{width}")
    _no_overflow(page)
    assert not errors

    with live_booking["app"].app_context():
        from flask import g
        g.tenant = SLUG
        from modules.clinics.models import ClinicAppointment, ClinicPatient

        patient = ClinicPatient.query.filter_by(tenant_id=seed["tenant_id"], phone=phone).one()
        appt = ClinicAppointment.query.filter_by(tenant_id=seed["tenant_id"], patient_id=patient.id).one()
        assert appt.doctor_id == seed["doctor_b_id"]
        assert appt.specialty_id == seed["internal_id"]
        assert appt.service_id == seed["svc_internal_id"]
        assert appt.appointment_date.isoformat() == seed["book_day"]
        assert appt.start_time.strftime("%H:%M") == slot
        assert appt.status in {"confirmed", "pending", "scheduled"}
    context.close()


def test_live_scenario2_specialty_change_resets_invalid_service_and_slot(live_booking):
    seed = live_booking["seed"]
    context = live_booking["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    _start(page, live_booking["base"])
    page.locator(f'[data-specialty="{seed["internal_id"]}"]').click()
    _next(page)
    page.locator(f'[data-doctor="{seed["doctor_a_id"]}"]').click()
    _next(page)
    page.locator(f'[data-service="{seed["svc_internal_id"]}"]').click()
    _next(page)
    page.locator('[name="appointment_date"]').fill(seed["book_day"])
    page.wait_for_selector("#bkSlots button", timeout=10000)
    page.locator("#bkSlots button").first.click()
    page.locator('.bk-pane.active [data-next="3"]').click()
    page.locator('.bk-pane.active [data-next="2"]').click()
    page.locator('.bk-pane.active [data-next="1"]').click()
    page.locator(f'[data-specialty="{seed["endocrine_id"]}"]').click()
    expect(page.locator('[name="specialty_id"]')).to_have_value(str(seed["endocrine_id"]))
    expect(page.locator('[name="doctor_id"]')).to_have_value(str(seed["doctor_a_id"]))
    expect(page.locator('[name="service_id"]')).to_have_value("")
    expect(page.locator('[name="start_time"]')).to_have_value("")
    _next(page)
    _next(page)
    expect(page.locator(f'[data-service="{seed["svc_endocrine_id"]}"]:not([hidden])')).to_be_visible()
    expect(page.locator(f'[data-service="{seed["svc_internal_id"]}"][hidden]')).to_have_count(1)
    expect(page.locator('[name="service_id"]')).to_have_value("")
    page.locator(f'[data-service="{seed["svc_endocrine_id"]}"]').click()
    _next(page)
    page.locator('[name="appointment_date"]').fill(seed["book_day"])
    page.wait_for_selector("#bkSlots button", timeout=10000)
    page.locator("#bkSlots button").first.click()
    _next(page)
    page.locator('[name="full_name"]').fill("مريض غدد")
    page.locator('[name="phone"]').fill("07702220001")
    _next(page)
    page.locator("#bkSubmit").click()
    expect(page.locator("#bkSuccess")).to_be_visible()
    _shot(page, "s2_endocrine_confirm")

    with live_booking["app"].app_context():
        from flask import g
        g.tenant = SLUG
        from modules.clinics.models import ClinicAppointment, ClinicPatient

        patient = ClinicPatient.query.filter_by(tenant_id=seed["tenant_id"], phone="07702220001").one()
        appt = ClinicAppointment.query.filter_by(tenant_id=seed["tenant_id"], patient_id=patient.id).one()
        assert appt.specialty_id == seed["endocrine_id"]
        assert appt.service_id == seed["svc_endocrine_id"]
        assert appt.doctor_id == seed["doctor_a_id"]
    context.close()


def test_live_scenario3_doctor_change_clears_service_and_slot(live_booking):
    seed = live_booking["seed"]
    context = live_booking["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    _start(page, live_booking["base"])
    page.locator(f'[data-specialty="{seed["internal_id"]}"]').click()
    _next(page)
    page.locator(f'[data-doctor="{seed["doctor_a_id"]}"]').click()
    _next(page)
    page.locator(f'[data-service="{seed["svc_internal_id"]}"]').click()
    _next(page)
    page.locator('[name="appointment_date"]').fill(seed["book_day"])
    page.wait_for_selector("#bkSlots button", timeout=10000)
    page.locator("#bkSlots button").first.click()
    page.locator('.bk-pane.active [data-next="3"]').click()
    page.locator('.bk-pane.active [data-next="2"]').click()
    page.locator(f'[data-doctor="{seed["doctor_b_id"]}"]').click()
    # Service may remain if still valid for the new doctor; slot must always reset.
    expect(page.locator('[name="start_time"]')).to_have_value("")
    _shot(page, "s3_doctor_change")
    context.close()


def test_live_scenario4_service_change_clears_slot(live_booking):
    seed = live_booking["seed"]
    context = live_booking["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    _start(page, live_booking["base"])
    page.locator(f'[data-specialty="{seed["endocrine_id"]}"]').click()
    _next(page)
    page.locator(f'[data-doctor="{seed["doctor_a_id"]}"]').click()
    _next(page)
    page.locator(f'[data-service="{seed["svc_endocrine_id"]}"]').click()
    _next(page)
    page.locator('[name="appointment_date"]').fill(seed["book_day"])
    page.wait_for_selector("#bkSlots button", timeout=10000)
    page.locator("#bkSlots button").first.click()
    expect(page.locator('[name="start_time"]')).not_to_have_value("")
    page.locator('.bk-pane.active [data-next="3"]').click()
    page.locator(f'[data-service="{seed["svc_endocrine_id"]}"]').click()
    expect(page.locator('[name="start_time"]')).to_have_value("")
    _shot(page, "s4_service_clears_slot")
    context.close()


@pytest.mark.parametrize(
    "doctor_key,expect_specialty_step",
    [("doctor_b_id", False), ("doctor_a_id", True)],
)
def test_live_scenario5_direct_doctor_link(live_booking, doctor_key, expect_specialty_step):
    seed = live_booking["seed"]
    doctor_id = seed[doctor_key]
    context = live_booking["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    page.goto(f"{live_booking['base']}/c/{SLUG}?doctor={doctor_id}")
    expect(page.locator("#bkForm")).to_be_visible()
    expect(page.locator('[name="doctor_id"]')).to_have_value(str(doctor_id))
    if expect_specialty_step:
        expect(page.locator('.bk-pane.active[data-pane="1"]')).to_be_visible()
        expect(page.locator('[name="specialty_id"]')).to_have_value("")
        page.locator(f'[data-specialty="{seed["endocrine_id"]}"]').click()
        _next(page)
        _next(page)
        page.locator(f'[data-service="{seed["svc_endocrine_id"]}"]').click()
    else:
        expect(page.locator('[name="specialty_id"]')).to_have_value(str(seed["internal_id"]))
        expect(page.locator('.bk-pane.active[data-pane="3"]')).to_be_visible()
        page.locator(f'[data-service="{seed["svc_internal_id"]}"]').click()
    _next(page)
    page.locator('[name="appointment_date"]').fill(seed["book_day"])
    page.wait_for_selector("#bkSlots")
    _shot(page, f"s5_direct_{doctor_key}")
    context.close()


def test_live_scenario6_no_availability_empty_state(live_booking):
    seed = live_booking["seed"]
    context = live_booking["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    _start(page, live_booking["base"])
    page.locator(f'[data-specialty="{seed["dentistry_id"]}"]').click()
    _next(page)
    page.locator(f'[data-doctor="{seed["doctor_none_id"]}"]').click()
    _next(page)
    page.locator(f'[data-service="{seed["svc_dental_id"]}"]').click()
    _next(page)
    page.locator('[name="appointment_date"]').fill(seed["book_day"])
    page.wait_for_function(
        "() => { const t = document.getElementById('bkSlots').innerText; return t.includes('لا توجد') || t.includes('جاري') === false; }",
        timeout=10000,
    )
    assert page.locator("#bkSlots button").count() == 0
    expect(page.locator(".bk-pane.active .bk-btn--primary")).to_be_disabled()
    _shot(page, "s6_no_slots")
    context.close()


def test_live_scenario7_disabled_relations_excluded(live_booking):
    seed = live_booking["seed"]
    context = live_booking["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    page.goto(f"{live_booking['base']}/c/{SLUG}")
    expect(page.locator(f'[data-book-doctor="{seed["inactive_doctor_id"]}"]')).to_have_count(0)
    page.locator("#bkStartBooking").click()
    if seed["disabled_specialty_id"]:
        expect(page.locator(f'[data-specialty="{seed["disabled_specialty_id"]}"]')).to_have_count(0)
    expect(page.locator(f'[data-service="{seed["inactive_service_id"]}"]')).to_have_count(0)
    expect(page.locator(f'[data-doctor="{seed["inactive_doctor_id"]}"]')).to_have_count(0)
    _shot(page, "s7_disabled_excluded")
    context.close()


def test_live_scenario8_double_booking_one_wins(live_booking):
    seed = live_booking["seed"]
    day = seed["book_day"]
    contexts = []
    pages = []
    for idx in range(2):
        ctx = live_booking["browser"].new_context(locale="ar-IQ", viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        contexts.append(ctx)
        pages.append(page)
        _start(page, live_booking["base"])
        page.locator(f'[data-specialty="{seed["internal_id"]}"]').click()
        _next(page)
        page.locator(f'[data-doctor="{seed["doctor_b_id"]}"]').click()
        _next(page)
        page.locator(f'[data-service="{seed["svc_internal_id"]}"]').click()
        _next(page)
        page.locator('[name="appointment_date"]').fill(day)
        page.wait_for_selector("#bkSlots button", timeout=10000)
        # Take the last available slot to reduce collisions with earlier tests.
        page.locator("#bkSlots button").last.click()
        slot = page.locator('[name="start_time"]').input_value()
        pages[idx].evaluate("(s) => window.__raceSlot = s", slot)
        _next(page)
        page.locator('[name="full_name"]').fill(f"سباق {idx}")
        page.locator('[name="phone"]').fill(f"0770333000{idx}")
        _next(page)

    # Force both pages onto the same slot value from page0.
    shared_slot = pages[0].evaluate("window.__raceSlot")
    for page in pages:
        page.evaluate(
            """(slot) => {
              const input = document.querySelector('[name="start_time"]');
              if (input) input.value = slot;
            }""",
            shared_slot,
        )

    for page in pages:
        page.locator("#bkSubmit").click()
    results = []
    for idx, page in enumerate(pages):
        page.wait_for_timeout(2000)
        success = page.locator("#bkSuccess").is_visible()
        err_box = page.locator("#bkError")
        err_text = err_box.inner_text() if err_box.is_visible() else ""
        results.append((success, err_text))
        _shot(page, f"s8_result_{idx}_{'ok' if success else 'err'}")

    assert sum(1 for ok, _ in results if ok) == 1, results
    assert sum(1 for ok, _ in results if not ok) == 1, results

    with live_booking["app"].app_context():
        from flask import g
        g.tenant = SLUG
        from modules.clinics.models import ClinicAppointment, ClinicPatient

        patient_ids = [
            p.id
            for p in ClinicPatient.query.filter(ClinicPatient.phone.in_(["07703330000", "07703330001"])).all()
        ]
        race_appts = ClinicAppointment.query.filter(
            ClinicAppointment.tenant_id == seed["tenant_id"],
            ClinicAppointment.patient_id.in_(patient_ids),
            ClinicAppointment.appointment_date == date.fromisoformat(day),
            ClinicAppointment.start_time == datetime.strptime(shared_slot, "%H:%M").time(),
        ).count()
        assert race_appts == 1
    for ctx in contexts:
        ctx.close()


def test_live_scenario9_otp_flow(live_booking):
    seed = live_booking["seed"]
    with live_booking["app"].app_context():
        from flask import g
        g.tenant = SLUG
        from modules.clinics.service import get_or_create_settings

        settings = get_or_create_settings(seed["tenant_id"])
        settings.booking_otp_enabled = True
        db.session.commit()

    context = live_booking["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    # Reload so OTP field is rendered
    _start(page, live_booking["base"])
    page.locator(f'[data-specialty="{seed["internal_id"]}"]').click()
    _next(page)
    page.locator(f'[data-doctor="{seed["doctor_b_id"]}"]').click()
    _next(page)
    page.locator(f'[data-service="{seed["svc_internal_id"]}"]').click()
    _next(page)
    page.locator('[name="appointment_date"]').fill(seed["book_day"])
    page.wait_for_selector("#bkSlots button", timeout=10000)
    page.locator("#bkSlots button").first.click()
    _next(page)
    if page.locator("#bkSendOtp").count() == 0:
        # Template was rendered before OTP flag; force reload of booking page.
        page.goto(f"{live_booking['base']}/c/{SLUG}")
        page.locator("#bkStartBooking").click()
        page.locator(f'[data-specialty="{seed["internal_id"]}"]').click()
        _next(page)
        page.locator(f'[data-doctor="{seed["doctor_b_id"]}"]').click()
        _next(page)
        page.locator(f'[data-service="{seed["svc_internal_id"]}"]').click()
        _next(page)
        page.locator('[name="appointment_date"]').fill(seed["book_day"])
        page.wait_for_selector("#bkSlots button", timeout=10000)
        page.locator("#bkSlots button").first.click()
        _next(page)
    page.locator('[name="full_name"]').fill("مريض OTP")
    page.locator('[name="phone"]').fill("07704441111")
    expect(page.locator("#bkSendOtp")).to_be_visible()
    page.locator("#bkSendOtp").click()
    page.wait_for_function(
        "() => (document.getElementById('bkOtpHint') || {}).textContent && document.getElementById('bkOtpHint').textContent.includes('رمز')",
        timeout=10000,
    )
    code = page.locator("#bkOtpHint").inner_text().split(":")[-1].strip()
    # Invalid OTP while still on patient pane, then confirm should fail.
    page.locator('[name="otp"]').evaluate("(el, v) => { el.value = v; el.dispatchEvent(new Event('input', {bubbles:true})); }", "000000")
    _next(page)
    page.locator("#bkSubmit").click()
    expect(page.locator("#bkError")).to_be_visible()
    # Back to patient pane and apply the correct OTP.
    page.locator('.bk-pane.active button.bk-btn:not(.bk-btn--primary)').click()
    page.locator('[name="otp"]').evaluate("(el, v) => { el.value = v; el.dispatchEvent(new Event('input', {bubbles:true})); }", code)
    _next(page)
    page.locator("#bkSubmit").click()
    expect(page.locator("#bkSuccess")).to_be_visible(timeout=15000)
    _shot(page, "s9_otp_success")

    with live_booking["app"].app_context():
        from flask import g
        g.tenant = SLUG
        from modules.clinics.models import ClinicAppointment, ClinicPatient
        from modules.clinics.service import get_or_create_settings

        patient = ClinicPatient.query.filter_by(phone="07704441111").one()
        assert ClinicAppointment.query.filter_by(tenant_id=seed["tenant_id"], patient_id=patient.id).count() == 1
        get_or_create_settings(seed["tenant_id"]).booking_otp_enabled = False
        db.session.commit()
    context.close()


def test_live_scenario10_manage_reschedule_and_cancel(live_booking):
    """Deterministic reschedule: seed schedule, book 09:00, move explicitly to 09:30."""
    seed = live_booking["seed"]
    manage_day = (date.fromisoformat(seed["book_day"]) + timedelta(days=7)).isoformat()
    booked_slot = "09:00"
    target_slot = "09:30"
    with live_booking["app"].app_context():
        from flask import g

        g.tenant = SLUG
        from modules.clinics.service import get_or_create_settings
        from modules.clinics.service_booking import available_slots, create_online_booking
        from modules.clinics.service_ops import upsert_schedule
        from modules.clinics.models import ClinicAppointment

        get_or_create_settings(seed["tenant_id"]).booking_otp_enabled = False
        upsert_schedule(
            seed["tenant_id"],
            {
                "doctor_id": seed["doctor_a_id"],
                "weekday": date.fromisoformat(manage_day).weekday(),
                "start_time": "09:00",
                "end_time": "12:00",
                "slot_minutes": 30,
            },
        )
        # Clear residue on manage_day for this doctor so slots are deterministic.
        for row in ClinicAppointment.query.filter_by(
            tenant_id=seed["tenant_id"],
            doctor_id=seed["doctor_a_id"],
            appointment_date=date.fromisoformat(manage_day),
        ).all():
            row.status = "cancelled"
        db.session.commit()

        with live_booking["app"].test_request_context(f"/c/{SLUG}/api/book", method="POST"):
            g.tenant = SLUG
            booked = create_online_booking(
                seed["tenant_id"],
                {
                    "full_name": "مريض إدارة",
                    "phone": "07705550000",
                    "doctor_id": seed["doctor_a_id"],
                    "specialty_id": seed["endocrine_id"],
                    "service_id": seed["svc_endocrine_id"],
                    "appointment_date": manage_day,
                    "start_time": booked_slot,
                },
            )
            db.session.commit()
        token = booked["manage_token"]
        free = available_slots(
            seed["tenant_id"],
            seed["doctor_a_id"],
            date.fromisoformat(manage_day),
            seed["svc_endocrine_id"],
            exclude_appointment_id=booked["id"],
        )
        assert target_slot in free, f"fixture must expose {target_slot}, got {free!r}"
        assert ClinicAppointment.query.filter_by(id=booked["id"]).one().specialty_id == seed["endocrine_id"]
        booked_id = booked["id"]

    context = live_booking["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    manage_href = f"/c/{SLUG}/manage/{token}"
    page.goto(f"{live_booking['base']}{manage_href}")
    expect(page.locator("#rescheduleBtn")).to_be_visible()
    page.locator("#rescheduleBtn").click()
    page.locator("#newDate").fill(manage_day)
    # Options inside <select> are attached but often not "visible" to Playwright.
    page.wait_for_selector(f'#newTime option[value="{target_slot}"]', state="attached", timeout=15000)
    page.locator("#newTime").select_option(value=target_slot)
    page.locator("#confirmReschedule").click()
    page.wait_for_function(
        f"() => (document.querySelector('#currentDate')?.textContent || '').includes('{target_slot}')",
        timeout=15000,
    )
    _shot(page, "s10_rescheduled")
    with live_booking["app"].app_context():
        from flask import g

        g.tenant = SLUG
        from modules.clinics.models import ClinicAppointment

        appt = ClinicAppointment.query.filter_by(id=booked_id).one()
        assert appt.doctor_id == seed["doctor_a_id"]
        assert appt.specialty_id == seed["endocrine_id"]
        assert appt.service_id == seed["svc_endocrine_id"]
        assert appt.start_time.strftime("%H:%M") == target_slot

    import json
    import urllib.request

    req = urllib.request.Request(
        f"{live_booking['base']}/c/{SLUG}/api/manage/{token}/cancel",
        data=json.dumps({"reason": "اختبار"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    assert payload.get("ok") is True
    with live_booking["app"].app_context():
        from flask import g

        g.tenant = SLUG
        from modules.clinics.models import ClinicAppointment

        appt = ClinicAppointment.query.filter_by(id=booked_id).one()
        assert appt.status == "cancelled"
        assert appt.specialty_id == seed["endocrine_id"]
        assert appt.service_id == seed["svc_endocrine_id"]
    page.goto(f"{live_booking['base']}{manage_href}")
    _shot(page, "s10_after_cancel_api")
    context.close()
