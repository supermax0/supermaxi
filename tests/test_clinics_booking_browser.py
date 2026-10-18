"""Real Edge UI tests with deterministic HTTP fixtures, not live backend E2E."""
import json
from pathlib import Path

import pytest
from flask import Flask, render_template
from playwright.sync_api import sync_playwright, expect


@pytest.fixture(scope="module")
def booking_browser():
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(channel="msedge", headless=True)
        yield browser
        browser.close()


@pytest.fixture()
def booking_page(booking_browser):
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(root / "templates"))
    clinic = dict(clinic_name="عيادة اختبار", welcome_text="حجز تجريبي", booking_enabled=True,
                  chat_enabled=False, maximum_advance_booking_days=60, otp_required=False,
                  specialties=[dict(id=i, name_ar=name) for i, name in [(1, "باطنية"), (2, "غدد")]],
                  doctors=[dict(id=1, full_name="طبيب متعدد", specialty_ids=[1, 2]),
                           dict(id=2, full_name="طبيب منفرد", specialty_ids=[1])],
                  services=[dict(id=1, name="خدمة باطنية", duration_minutes=30, price=None, specialty_ids=[1], doctor_ids=[1]),
                            dict(id=2, name="خدمة غدد", duration_minutes=30, price=None, specialty_ids=[2], doctor_ids=[1]),
                            dict(id=3, name="خدمة الطبيب الثاني", duration_minutes=30, price=None, specialty_ids=[1], doctor_ids=[2])])
    with app.test_request_context():
        html = render_template("clinics/public_booking.html", clinic=clinic, tenant_slug="fixture", error=None)
    context = booking_browser.new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    errors, submitted = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def route(request):
        url = request.request.url
        if "/api/slots" in url:
            request.fulfill(json={"ok": True, "data": ["10:00", "11:00"]})
        elif "/api/book" in url:
            submitted.append(request.request.post_data_json)
            request.fulfill(json={"ok": True, "data": {"mode": "direct", "booking_number": "TEST-1", "manage_token": "fixture-token"}})
        elif "/static/clinics/booking.css" in url:
            request.fulfill(content_type="text/css", body=(root / "static/clinics/booking.css").read_text(encoding="utf-8"))
        elif url.startswith("http://clinics.test/c/"):
            request.fulfill(content_type="text/html", body=html)
        else:
            request.abort()

    page.route("**/*", route)
    yield page, errors, submitted
    context.close()


def next_step(page):
    page.locator(".bk-pane.active .bk-btn--primary").click()


def no_overflow(page):
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


@pytest.mark.parametrize("width", [1920, 1366, 1024, 768, 430, 390, 375])
def test_booking_confirm_mobile_and_desktop(booking_page, width):
    page, errors, submitted = booking_page
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("http://clinics.test/c/fixture")
    page.locator("#bkStartBooking").click()
    page.locator('[data-specialty="1"]').click()
    no_overflow(page)
    next_step(page)
    page.locator('[data-doctor="1"]').click()
    next_step(page)
    page.locator('[data-service="1"]').click()
    next_step(page)
    page.locator('[data-slot="10:00"]').click()
    no_overflow(page)
    next_step(page)
    page.locator('[name="full_name"]').fill("مريض تجريبي")
    page.locator('[name="phone"]').fill("07700000000")
    next_step(page)
    no_overflow(page)
    page.locator("#bkSubmit").click()
    expect(page.locator("#bkSuccess")).to_be_visible()
    assert submitted[0]["specialty_id"] == "1"
    assert submitted[0]["doctor_id"] == "1"
    assert submitted[0]["service_id"] == "1"
    assert submitted[0]["start_time"] == "10:00"
    assert not errors


@pytest.mark.parametrize("doctor_id, pane", [(1, 1), (2, 3)])
def test_direct_doctor_link(booking_page, doctor_id, pane):
    page, errors, _ = booking_page
    page.goto(f"http://clinics.test/c/fixture?doctor={doctor_id}")
    expect(page.locator(f'.bk-pane.active[data-pane="{pane}"]')).to_be_visible()
    expect(page.locator('[name="doctor_id"]')).to_have_value(str(doctor_id))
    if doctor_id == 2:
        expect(page.locator('[name="specialty_id"]')).to_have_value("1")
    assert not errors


@pytest.mark.parametrize("change", ["specialty", "doctor"])
def test_selection_changes_clear_stale_state(booking_page, change):
    page, errors, _ = booking_page
    page.goto("http://clinics.test/c/fixture?doctor=1")
    page.locator('[data-specialty="1"]').click()
    next_step(page)
    next_step(page)
    page.locator('[data-service="1"]').click()
    next_step(page)
    page.locator('[data-slot="10:00"]').click()
    page.locator('.bk-pane.active [data-next="3"]').click()
    page.locator('.bk-pane.active [data-next="2"]').click()
    if change == "specialty":
        page.locator('.bk-pane.active [data-next="1"]').click()
        page.locator('[data-specialty="2"]').click()
        expect(page.locator('[name="specialty_id"]')).to_have_value("2")
    else:
        page.locator('[data-doctor="2"]').click()
    expect(page.locator('[name="service_id"]')).to_have_value("")
    expect(page.locator('[name="start_time"]')).to_have_value("")
    assert not errors


def test_specialty_builder_uses_form_rule_controls(booking_browser):
    root = Path(__file__).resolve().parents[1]
    context = booking_browser.new_context(locale="ar-IQ")
    page = context.new_page()
    page.set_content('<main id="root"></main>')
    page.add_script_tag(content=(root / "static/clinics/specialty-builder.js").read_text(encoding="utf-8"))
    draft = {"id": 7, "name": "نموذج", "status": "draft", "sections": [{"title_ar": "قسم", "fields": [
        {"key": "answer", "label_ar": "الإجابة", "field_type": "text", "options": [], "validation": {}, "visibility_rules": {}},
        {"key": "details", "label_ar": "التفاصيل", "field_type": "text", "options": [], "validation": {}, "visibility_rules": {}},
    ]}]}
    page.evaluate("""async draft => {
      const api = async path => path.endsWith('/templates') ? [{id:7,name:'نموذج',version:1,status:'draft'}] : draft;
      await window.ClinicsSpecialtyBuilder(document.querySelector('#root'), {id:1,name_ar:'اختصاص'}, {
        api, esc:value=>String(value ?? '').replaceAll('&','&amp;').replaceAll('"','&quot;'),
        showNotice:()=>{}, back:()=>{}, fieldHtml:()=>''
      });
    }""", draft)
    page.locator('[data-open="7"]').click()
    expect(page.locator('text=قاعدة الإظهار JSON')).to_have_count(0)
    page.locator('[data-add-rule="0:1"]').click()
    expect(page.locator('[data-field="1"] [data-rule-field]')).to_be_visible()
    expect(page.locator('[data-field="1"] [data-rule-operator]')).to_be_visible()
    expect(page.locator('[data-field="1"] [data-rule-value]')).to_be_visible()
    context.close()
